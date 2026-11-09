from __future__ import annotations

from collections import deque
import base64
import os
import struct

import pytest
from websocket import WebSocketTimeoutException

from imo import IMOClient, IMOLoginError, IMOTimeoutError, IMOTransportError
from imo._web_transport import FrameDecoder, WebTransport, encode_frame


def test_frame_decoder_handles_partial_and_batched_binary_frames():
    first = encode_frame({"msg": "Salam, мир"})
    second = encode_frame({"ack": 7})
    decoder = FrameDecoder()
    assert decoder.feed(first[:2]) == []
    assert decoder.feed(first[2:8]) == []
    assert decoder.feed(first[8:] + second) == [{"msg": "Salam, мир"}, {"ack": 7}]
    with pytest.raises(IMOTransportError, match="length"):
        decoder.feed(struct.pack(">I", 0))
    with pytest.raises(IMOTransportError, match="payload"):
        FrameDecoder().feed(b"\0\0\0\3bad")


class ScriptedSocket:
    def __init__(self, *, cancelled=False, timeout_on_send=False, history_message=None):
        self.decoder = FrameDecoder()
        self.incoming = deque()
        self.calls = []
        self.acks = []
        self.ssid = None
        self.seq = 0
        self.cancelled = cancelled
        self.timeout_on_send = timeout_on_send
        self.history_message = history_message
        self.closed = False

    def settimeout(self, value):
        assert value > 0

    def shutdown(self):
        self.closed = True

    def recv(self):
        if not self.incoming:
            raise WebSocketTimeoutException()
        return self.incoming.popleft()

    def envelope(self, body):
        packet = {"seq": self.seq, "to": {"ssid": self.ssid}, "data": body}
        self.seq += 1
        return packet

    def downlink(self, *packets):
        self.incoming.append(encode_frame({"data": {"messages": list(packets)}}))

    def send_binary(self, data):
        (frame,) = self.decoder.feed(data)
        body = frame["data"]
        if frame["method"] == "name_channel":
            self.ssid = body["ssid"]
            assert frame["headers"]["compression"] == ["zlib"]
            self.incoming.append(encode_frame({"method": "name_channel", "data": {}}))
            return
        self.acks.append(body["ack"])
        if not body["messages"]:
            return
        (packet,) = body["messages"]
        assert packet["seq"] == len(self.calls)
        system = packet["to"]["system"]
        request = packet["data"]
        method, params = request["method"], request["data"]
        self.calls.append((system, method, params))
        if method == "request_qr_code":
            assert params == {"ssid": self.ssid}
            reply = self.envelope({"request_id": request["request_id"], "response": {
                "status": "success", "result": {"qr_link": "fixture-qr", "code_ttl": 60},
            }})
            scan = self.envelope({"type": "session", "name": "qr_code_scanned", "edata": {"bind_ttl": 60}})
            complete = self.envelope({"type": "session", "name": (
                "qr_code_login_cancelled" if self.cancelled else "qr_code_login_completed"
            )})
            self.downlink(complete)  # an out-of-order push must wait for the missing sequence
            self.downlink(reply, scan, scan)
            return
        if method == "cookie_login":
            assert params["reason"] == "scan_login"
            assert params["ssid"] == self.ssid
            self.downlink(self.envelope({"type": "account", "name": "signed_on",
                                         "uid": "fixture-uid", "edata": {"alias": "Test", "private_field": "secret"}}))
            return
        assert params["uid"] == "fixture-uid"
        if method == "sync_full_buddies":
            more = params["cursor"] == "0"
            result = {"has_more": more, "next_cursor": "second" if more else "",
                      "buddies": [{"buid": "contact-a" if more else "contact-b", "alias": "Test Contact"}]}
            reply = {"status": "success", "result": result}
        elif method == "get_conversation":
            assert params["buid"] == "contact-a"
            assert params["end_time"] == "900"
            assert params["from_end"] is True and params["limit"] == 5
            reply = [self.history_message or {"msg": "old message", "timestamp_nano_str": "800"}]
        elif method == "get_photo":
            assert system == "pixeldownload" and params["ssid"] == self.ssid
            data = {"photo-history": b"photo", "voice-event": b"voice"}[params["object_id"]]
            reply = {"base64": base64.b64encode(data).decode("ascii"), "total": len(data)}
        elif method == "sync_chat_changes":
            reply = {"status": "success", "result": [
                {"type": "update", "buid": "a", "change_ts": "1"},
                {"type": "update", "buid": "b", "change_ts": "2"},
                {"type": "update", "buid": "a", "change_ts": "3"},
                {"type": "update", "buid": "gone", "change_ts": "4"},
                {"type": "delete", "buid": "gone", "change_ts": "5"},
            ]}
        elif method == "send_im":
            assert params["msg"] == "Salam"
            assert params["imdata"]["type"] == "im"
            if self.timeout_on_send:
                return
            reply = {"timestamp_nano_str": "901"}
        elif method == "logout":
            reply = {"status": "success"}
        else:
            raise AssertionError(method)
        self.downlink(self.envelope({"request_id": request["request_id"], "response": reply}))


@pytest.fixture
def scripted(monkeypatch):
    def install(**options):
        sock = ScriptedSocket(**options)
        def connect(url, *, origin, timeout):
            assert url == "wss://sgp-webstream.imo.im/wss_webstream"
            assert origin == "https://web.imo.im"
            return sock
        monkeypatch.setattr("imo._web_transport.create_connection", connect)
        return sock
    return install


def login(client):
    qr = client.begin_qr_login()
    assert qr.ttl == 60 and qr.payload == "fixture-qr"
    assert "fixture-qr" not in repr(qr)
    client.wait_for_login()


def test_qr_and_account_operations(scripted):
    sock = scripted()
    with IMOClient() as client:
        with pytest.raises(IMOLoginError):
            client.get_contacts()
        login(client)
        assert client.get_me() == {"uid": "fixture-uid", "alias": "Test"}
        assert [item.buid for item in client.get_contacts()] == ["contact-a", "contact-b"]
        assert [item["buid"] for item in client.get_chats()] == ["a", "b"]
        assert client.get_history("contact-a", limit=5, before="900")[0]["msg"] == "old message"
        assert client.send_message("contact-a", "Salam").timestamp_nano == "901"
        sock.downlink(sock.envelope({"type": "conv", "name": "recv_im", "edata": {"msg": "incoming"}}))
        assert client.receive_message() == {"msg": "incoming"}
        client.logout()
        assert not client.is_authenticated
    assert sock.closed
    assert sock.acks == sorted(sock.acks)


def test_cancelled_qr_releases_socket(scripted):
    sock = scripted(cancelled=True)
    with IMOClient() as client:
        client.begin_qr_login()
        with pytest.raises(IMOLoginError, match="cancelled"):
            client.wait_for_login()
        assert not client.is_authenticated
    assert sock.closed


def test_download_attachments_from_history_and_incoming_push(scripted, tmp_path):
    row = {"timestamp_nano_str": "800", "imdata": {
        "type": "photo_uploaded_2", "objects": [{"object_id": "imo/photo-history", "ext": "jpg"}],
    }}
    sock = scripted(history_message=row)
    with IMOClient() as client:
        login(client)
        (record,) = client.get_history("contact-a", limit=5, before="900")
        (photo,) = client.download_attachments(record, tmp_path)
        sock.downlink(sock.envelope({"type": "conv", "name": "recv_im", "edata": {
            "buid": "contact-a", "imdata": {
                "type": "audio_uploaded", "objects": [{"object_id": "imo/voice-event", "ext": "ogg"}],
            },
        }}))
        (audio,) = client.download_attachments(client.receive_message(), tmp_path)
    assert (photo.name, photo.read_bytes()) == ("photo.jpg", b"photo")
    assert (audio.name, audio.read_bytes()) == ("audio.ogg", b"voice")


def test_send_timeout_is_not_retried(scripted):
    sock = scripted(timeout_on_send=True)
    with IMOClient() as client:
        login(client)
        with pytest.raises(IMOTimeoutError):
            client.send_message("contact-a", "Salam")
        assert [method for _, method, _ in sock.calls].count("send_im") == 1
        assert not client.is_authenticated
    assert sock.closed


def test_server_signoff_ends_local_session(scripted):
    sock = scripted()
    with IMOClient() as client:
        login(client)
        sock.downlink(sock.envelope({"type": "session", "name": "signoff_all"}))
        with pytest.raises(IMOLoginError, match="ended"):
            client.receive_message()
        assert not client.is_authenticated


def test_transport_rejects_unknown_region():
    with pytest.raises(ValueError, match="region"):
        WebTransport("other", 1)

@pytest.mark.skipif(os.environ.get("IMO_WEB_LIVE") != "1", reason="Set IMO_WEB_LIVE=1 for a real QR request")
def test_real_server_issues_qr_without_existing_session():
    with IMOClient() as client:
        challenge = client.begin_qr_login()
        assert challenge.ttl > 0
        assert challenge.payload
        assert not client.is_authenticated
