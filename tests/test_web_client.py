from __future__ import annotations

from collections import deque
import base64
import os
import struct
import time
from types import SimpleNamespace

import pytest
from websocket import WebSocketTimeoutException

from imo import Chat, IMOClient, IMOLoginError, IMORequestError, IMOTimeoutError, IMOTransportError, WebMessage
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
    def __init__(self, *, cancelled=False, timeout_on_send=False, history_message=None, history_pages=None,
                 unconfirmed=(), buddies=None, file_server_response=None):
        self.unconfirmed = set(unconfirmed)
        self.buddies = buddies
        self.file_server_response = file_server_response
        self.decoder = FrameDecoder()
        self.incoming = deque()
        self.calls = []
        self.acks = []
        self.ssid = None
        self.seq = 0
        self.cancelled = cancelled
        self.timeout_on_send = timeout_on_send
        self.history_message = history_message
        self.history_pages = history_pages
        self.closed = False

    def settimeout(self, value):
        assert value > 0

    def shutdown(self):
        self.closed = True

    def recv(self):
        if not self.incoming:
            raise WebSocketTimeoutException()
        result = self.incoming.popleft()
        if result is None:
            raise WebSocketTimeoutException()
        return result

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
        if method == "keep_alive":
            assert system == "dispatcher" and params == {"ssid": self.ssid}
            return
        assert params["uid"] == "fixture-uid"
        if method == "sync_full_buddies" and self.buddies is not None:
            reply = {"status": "success", "result": {"has_more": False, "buddies": self.buddies}}
        elif method == "sync_full_buddies":
            more = params["cursor"] == "0"
            result = {"has_more": more, "next_cursor": "second" if more else "",
                      "buddies": [{"buid": "contact-a" if more else "contact-b", "alias": "Test Contact"}]}
            reply = {"status": "success", "result": result}
        elif method == "get_conversation":
            assert params["buid"] == "contact-a"
            assert params["from_end"] is True
            if self.history_pages is None:
                assert params["end_time"] == "900" and params["limit"] == 5
                reply = [self.history_message or {"msg": "old message", "timestamp_nano_str": "800"}]
            else:
                reply = self.history_pages[(params["end_time"], params["limit"])]
        elif method == "get_photo":
            assert system == "pixeldownload" and params["ssid"] == self.ssid
            data = {"photo-history": b"photo", "voice-event": b"voice"}[params["object_id"]]
            reply = {"base64": base64.b64encode(data).decode("ascii"), "total": len(data)}
        elif method == "request_file_server" and self.file_server_response is not None:
            assert system == "feproxy"
            reply = {"res": self.file_server_response}
        elif method == "sync_chat_changes":
            reply = {"status": "success", "result": [
                {"type": "update", "buid": "a", "change_ts": "1"},
                {"type": "update", "buid": "b", "change_ts": "2"},
                {"type": "update", "buid": "a", "change_ts": "3",
                 "last_message": {"msg": "Latest", "timestamp_nano_str": "200"}},
                {"type": "update", "buid": "gone", "change_ts": "4"},
                {"type": "delete", "buid": "gone", "change_ts": "5"},
            ]}
        elif method == "get_group_members":
            assert system == "pin" and params == {"gid": "group", "uid": "fixture-uid"}
            reply = [
                {"uid": "owner;suffix", "display": "Owner", "icon": "icon", "is_owner": True},
                {"buid": "member", "display": "Member"},
                {"uid": "deleted", "isDeleteAccount": True},
                {"display": "Missing ID"},
            ]
        elif method == "send_im":
            assert params["msg"] == "Salam"
            assert params["imdata"]["type"] == "im"
            if self.timeout_on_send:
                return
            reply = {} if params["buid"] in self.unconfirmed else {"timestamp_nano_str": "901"}
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


def test_connect_uses_callback_and_is_idempotent(scripted):
    socket = scripted()
    shown = []
    with IMOClient() as client:
        client.connect(show_qr=shown.append)
        client.connect(show_qr=shown.append)
        assert client.is_authenticated
        assert [item.payload for item in shown] == ["fixture-qr"]
        assert [method for _, method, _ in socket.calls] == ["request_qr_code", "cookie_login"]


def test_default_connect_renders_terminal_qr(scripted, capsys):
    pytest.importorskip("qrcode")
    scripted()
    with IMOClient() as client:
        client.connect()
        rendered = capsys.readouterr().err
        assert "60s" in rendered
        assert "fixture-qr" not in rendered


def test_connect_closes_if_qr_display_is_interrupted(scripted):
    socket = scripted()

    def interrupt(challenge):
        raise KeyboardInterrupt

    client = IMOClient()
    with pytest.raises(KeyboardInterrupt):
        client.connect(show_qr=interrupt)
    assert socket.closed and not client.is_authenticated


def row(ts, msg, **fields):
    return {"timestamp_nano_str": str(ts), "msg": msg, **fields}


def test_iter_history_handles_inclusive_boundary_and_single_row_pages(scripted):
    shared = row(800, "boundary")
    second_at_same_time = row(800, "another author", author="other")
    socket = scripted(history_pages={
        ("900", 1): [shared],
        ("800", 2): [shared, second_at_same_time],
        ("800", 4): [shared, second_at_same_time, row(700, "older")],
    })
    with IMOClient() as client:
        login(client)
        chat = Chat.from_record({"buid": "contact-a"})
        messages = client.iter_history(chat, before="900", page_size=1, max_messages=3)
        assert all(method != "get_conversation" for _, method, _ in socket.calls)
        records = list(messages)
    assert [(message.buid, message.text) for message in records] == [
        ("contact-a", "boundary"), ("contact-a", "another author"), ("contact-a", "older"),
    ]
    assert [p["end_time"] for _, method, p in socket.calls if method == "get_conversation"] == ["900", "800", "800"]


def test_iter_history_rejects_non_advancing_cursor(scripted):
    data = [row(800, str(index)) for index in range(100)]
    scripted(history_pages={("900", 100): data, ("800", 100): data})
    with IMOClient() as client:
        login(client)
        messages = client.iter_history("contact-a", before="900", page_size=100)
        assert [next(messages).text for _ in data] == [str(index) for index in range(100)]
        with pytest.raises(IMORequestError, match="could not advance"):
            next(messages)


def test_iter_history_rejects_rows_without_cursor(scripted):
    scripted(history_pages={("900", 50): [{"msg": "unpageable"}]})
    with IMOClient() as client:
        login(client)
        with pytest.raises(IMORequestError, match="pagination timestamp"):
            list(client.iter_history("contact-a", before="900"))


def test_typed_chats_roster_and_sending_to_contact(scripted):
    scripted()
    with IMOClient() as client:
        login(client)
        chat, _ = client.list_chats()
        assert isinstance(chat, Chat) and not chat.is_group
        assert chat.last_message.text == "Latest"
        assert chat.last_message.buid == "a" and chat.changed_at_nano == "3"
        with pytest.raises(ValueError, match="not a group"):
            client.get_group_members(chat)
        group = Chat.from_record({"buid": "group;"})
        assert group.is_group and group.last_message is None
        owner, member = client.get_group_members(group)
        assert (owner.uid, owner.display, owner.is_owner) == ("owner", "Owner", True)
        assert (member.uid, member.is_owner) == ("member", False)
        contact = client.get_contacts()[0]
        assert client.send_message(contact, "Salam").buid == contact.buid


def test_run_dispatches_typed_message_and_downloads_attachment_after_idle(scripted, tmp_path):
    socket = scripted()
    calls = []
    with IMOClient() as client:
        login(client)
        socket.incoming.append(None)
        socket.downlink(socket.envelope({"type": "conv", "name": "recv_im", "edata": {
            "buid": "contact-a", "msg": "Salam!", "timestamp_nano_str": "900", "author": "a",
            "imdata": '{"type":"audio_uploaded","msg_id":"42","objects":[{"object_id":"imo/voice-event"}]}',
        }}))

        @client.on_message
        def handler(message):
            assert isinstance(message, WebMessage)
            assert (message.text, message.message_id, message.author) == ("Salam!", "42", "a")
            assert message.attachments[0].kind == "audio"
            (path,) = client.download_attachments(message, tmp_path)
            calls.append(path.read_bytes())
            client.stop()
            with pytest.raises(RuntimeError, match="already running"):
                client.run()

        client.on_message(handler)
        client.run()
        assert client.is_authenticated and calls == [b"voice"]
        client.remove_message_handler(handler)
        with pytest.raises(ValueError, match="Register"):
            client.run()


def test_run_exposes_handler_errors_and_can_be_restarted(scripted):
    socket = scripted()
    with IMOClient() as client:
        login(client)

        @client.on_message
        def failing(message):
            raise IMOTimeoutError("handler operation failed")

        socket.downlink(socket.envelope({"type": "conv", "name": "recv_im", "edata": {"msg": "first"}}))
        with pytest.raises(IMOTimeoutError, match="handler operation"):
            client.run()
        client.remove_message_handler(failing)
        client.on_message(lambda _: client.stop())
        socket.downlink(socket.envelope({"type": "conv", "name": "recv_im", "edata": {"msg": "second"}}))
        client.run()
        assert client.is_authenticated


def test_event_queue_discards_unsubscribed_events_but_reports_overflow(scripted, monkeypatch):
    socket = scripted()
    with IMOClient() as client:
        login(client)
        monkeypatch.setattr("imo._web_transport._MAX_EVENTS", 2)
        for _ in range(3):
            socket.downlink(socket.envelope({"type": "unrelated", "name": "ignored"}))
        socket.downlink(socket.envelope({"type": "conv", "name": "recv_im", "edata": {"msg": "ok"}}))
        assert client.receive_message()["msg"] == "ok"
        for index in range(3):
            socket.downlink(socket.envelope({"type": "conv", "name": "recv_im", "edata": {"msg": str(index)}}))
        with pytest.raises(IMOTransportError, match="event buffer exceeded"):
            client.get_contacts()
        assert not client.is_authenticated


def test_keepalive_preserves_pending_command(scripted, monkeypatch):
    socket = scripted()
    with IMOClient(timeout=400) as client:
        login(client)
        now = 0.0
        original_recv = socket.recv

        def recv():
            nonlocal now
            try:
                return original_recv()
            except WebSocketTimeoutException:
                now += 180
                raise

        monkeypatch.setattr(socket, "recv", recv)
        monkeypatch.setattr("imo._web_transport.time", SimpleNamespace(
            time=time.time, time_ns=time.time_ns, monotonic=lambda: now,
        ))
        socket.incoming.append(None)
        assert [contact.buid for contact in client.get_contacts()] == ["contact-a", "contact-b"]
        assert [method for _, method, _ in socket.calls][-3:] == [
            "sync_full_buddies", "keep_alive", "sync_full_buddies",
        ]
