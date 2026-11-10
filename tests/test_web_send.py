"""Recipient selection and the file-send protocol exercised over scripted connections."""
import base64
from collections import deque
from hashlib import md5, sha256
import json
from struct import unpack_from
import time
from types import SimpleNamespace

import pytest

from imo import IMOClient, IMOContactNotFound, IMOPartialSendError, IMOUploadError
from imo import _nerv, _nerv_upload as upload
from test_attachments import SERVER_RESPONSE
from test_web_client import login, scripted  # noqa: F401  (scripted is a fixture)


UID64 = 4044251543752996343
CONTACTS = [{"buid": "contact-a", "alias": "Enem"}, {"buid": "other", "alias": "Enem Two"}]
BATCH_READY = base64.b64decode("GAAAAAKOJwDIAAcAAAAAAAAAZQAAAAAA")
FILE_READY = base64.b64decode("OwAAAALzAwDIAAgAAAAAAAAAAAAAAAAAAAAKAHNhbXBsZS5iaW4AAAAAAAAAAPf1uAdaESA4ZAAAAAA=")
ACK = base64.b64decode("LgAAAAL1AwDIAAgAAAAAAAAAAAAAAAMAAAABAAAAAwAAAAEAAAD39bgHWhEgOA==")
RESULT = base64.b64decode(
    "bgAAAAKPJwDIAAcAAAAAAAAAZQAAAAAAAAAAAAEAAAABAEoAeyJzdGF0dXMiOiJzdWNjZXNzIiwicmVzdWx0Ijp7Im9iamVjdF9"
    "kYXRhIjp7InRpbWVzdGFtcF9uYW5vX3N0ciI6IjkwMiJ9fX0="
)


def test_send_selects_id_or_exact_name(scripted):
    socket = scripted(buddies=CONTACTS)
    with IMOClient() as client:
        login(client)
        assert client.send_message(id="group;", text="Salam").buid == "group;"
        assert client.send_message(id=123, text="Salam").buid == "123"
        assert all(method != "sync_full_buddies" for _, method, _ in socket.calls)
        assert client.send_message(name=" ENEM ", text="Salam").buid == "contact-a"
        assert client.send_message("legacy", "Salam").buid == "legacy"
        with pytest.raises(IMOContactNotFound):
            client.send_message(name="Two", text="Salam")
        for kwargs in ({}, {"id": "x", "name": "Enem"}, {"id": "x", "text": " "},
                       {"id": True, "text": "Salam"}):
            with pytest.raises(ValueError):
                client.send_message(**kwargs)
    assert [p["buid"] for _, method, p in socket.calls if method == "send_im"] == [
        "group;", "123", "contact-a", "legacy",
    ]


def test_send_rejects_multiple_exact_name_matches(scripted):
    socket = scripted(buddies=CONTACTS + [{"buid": "another", "note": "Enem"}])
    with IMOClient() as client:
        login(client)
        with pytest.raises(IMOContactNotFound, match="2 contacts"):
            client.send_message(name="Enem", text="Salam")
    assert all(method != "send_im" for _, method, _ in socket.calls)


def test_upload_encoders_match_the_official_web_bundle():
    digest = md5(b"abc").hexdigest()
    registration = upload._file_registration(100, UID64, "TM", "test-token", "sample.bin", 3, 1, digest, 891568578)
    backend = {"uid": "fixture-uid", "stream_id": "pair:imo#contact-a#fixture-uid", "imdata": {"type": "bigo_uploaded"}}
    info = {"file_size": 3, "url": "", "key": "object_url", "md5": digest}
    frames = (
        registration,
        upload._batch_request(101, UID64, backend, registration, info),
        upload._file_piece(8, UID64, 3, 1, 1, 1, b"abc"),
        upload._file_piece(8, UID64, 65535, 1, 1, 1, b"a" * 65535),
    )
    assert [sha256(frame).hexdigest() for frame in frames] == [
        "83a8c34f8ed43986616b0fcbba39fad7b4f14639ebe8c9bef726cb5f29c75cab",
        "fd190d1aa2b8f1af829e4770e27251eed472565c6ddc5b1e15143ef7bbe7eef1",
        "e76354c650e4e3314c717ea307f7a654394467bd9b7263a34afeea190450ad95",
        "b0370b1838f22790440c57e8b0f969c575dfcc9a3b582dffa32ace7969b3cafd",
    ]


class UploadSocket:
    def __init__(self, final):
        self.incoming = deque((BATCH_READY[:7], BATCH_READY[7:] + FILE_READY, ACK + final))
        self.sent = []
        self.closed = False

    def getstatus(self):
        return 101

    def settimeout(self, timeout):
        assert timeout > 0

    def send_binary(self, data):
        self.sent.append(data)

    def recv(self):
        return self.incoming.popleft() if self.incoming else b""

    def shutdown(self):
        self.closed = True


@pytest.mark.parametrize("mode", ["file", "both", "text-fails", "file-fails"])
def test_send_media_waits_for_file_confirmation(mode, scripted, monkeypatch, tmp_path):
    signal = scripted(buddies=CONTACTS, file_server_response=SERVER_RESPONSE,
                      unconfirmed={"contact-a"} if mode == "text-fails" else set())
    socket = UploadSocket(b"" if mode == "file-fails" else RESULT)
    monkeypatch.setattr(_nerv, "_REQUEST_IDS", iter((42,)))
    monkeypatch.setattr(upload, "time", SimpleNamespace(monotonic=time.monotonic, time_ns=lambda: 100_000_000))

    def connect(url, **options):
        assert url == "wss://files.imo.im/download?token=stub-wss-token"
        assert options["redirect_limit"] == 0
        return socket

    monkeypatch.setattr(_nerv, "create_connection", connect)
    path = tmp_path / "sample.bin"
    path.write_bytes(b"abc")
    with IMOClient() as client:
        login(client)
        if mode == "file-fails":
            with pytest.raises(IMOUploadError, match="closed"):
                client.send_message(name="Enem", text="Salam", media=path)
        elif mode == "text-fails":
            with pytest.raises(IMOPartialSendError) as caught:
                client.send_message(name="Enem", text="Salam", media=path)
            assert caught.value.attachment.timestamp_nano == "902"
        elif mode == "both":
            file_receipt, text_receipt = client.send_message(name="Enem", text="Salam", media=path)
            assert (file_receipt.timestamp_nano, text_receipt.timestamp_nano) == ("902", "901")
        else:
            receipt = client.send_message(id="contact-a", media=path)
            assert receipt.timestamp_nano == "902"
    methods = [method for _, method, _ in signal.calls]
    assert methods.count("request_file_server") == 1
    assert methods.count("send_im") == int(mode in ("both", "text-fails"))
    file_server = next(params for _, method, params in signal.calls if method == "request_file_server")
    request = base64.b64decode(file_server["payload"])
    country_length = unpack_from("<H", request, 22)[0]
    assert unpack_from("<I", request, 24 + country_length)[0] == 1
    assert socket.closed and len(socket.sent) == 2
    batch, piece = socket.sent
    fields = _nerv._Reader(batch[10:])
    assert (fields.uint(4), fields.uint(4), fields.uint(8), fields.uint(2)) == (62, 101, UID64, 1)
    assert (fields.uint(4), fields.uint(4), fields.uint(2)) == (0, 1, 1)
    backend = json.loads(fields.text())
    assert backend["stream_id"] == "pair:imo#contact-a#fixture-uid"
    assert backend["imdata"]["file_name"] == "sample.bin"
    assert sha256(piece).hexdigest() == "e76354c650e4e3314c717ea307f7a654394467bd9b7263a34afeea190450ad95"


def test_invalid_file_does_not_send_text(scripted, tmp_path):
    signal = scripted()
    with IMOClient() as client:
        login(client)
        for path in (tmp_path, tmp_path / "missing.txt", tmp_path / "empty.txt"):
            if path.name == "empty.txt":
                path.touch()
            with pytest.raises(ValueError, match="media must"):
                client.send_message(id="contact-a", text="Salam", media=path)
    assert all(method not in ("send_im", "request_file_server") for _, method, _ in signal.calls)
