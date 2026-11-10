from __future__ import annotations

import base64
import io
import os

import pytest

from imo import IMOAttachmentTooLarge, IMOAttachmentUnavailable, IMOClient, IMODownloadError, IMOLoginError
from imo import extract_attachments
from imo import _media, _nerv
from imo._media_identity import account_hash


# Synthetic values serialized by the public IMO Web bundle's encoder.
SERVER_REQUEST = (
    "YQAAAAIpEwHIACoAAAAAAAAAAAAAAAIAVE0CAAAAAAAAAAAAAAA+AAAA9/W4B1oRIDgAAAAAAAAAAAAAAAAAAAIAVE0"
    "AAQAAAFBpDwBkAQAAAAgAdGFza2Zyb20DAHdlYg=="
)
START_REQUEST = (
    "owAAAAL5AwDIAAAAAAAAAAAAAAAAABkAaHR0cHM6Ly9maWxlcy5pbW8uaW0vbmFtZQAAAAAAAAAAAAAAAAAAAAAAAA"
    "4AP3BhcmFtPWV4YW1wbGUAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAQoAdGVzdC10b2tlbvf1uAdaESA4AAAAAAIAAAAB"
    "AAIAVE2JEwMAd2ViAAAAAP////8AAAAAZAAAAA=="
)
SERVER_RESPONSE = (
    "GQEAAALr9gDIAAAAAAKaEQHIANoAAAAqAAAAyAAAAMoAAAAAAAAAAAAAAAAAAAAAAAAAAAABAAAACQAAAAEAAAAKAAEAAAAL"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAACgB0ZXN0LXRva2VuAQAA"
    "AAcAAAABAAAACAAAAAAAAAAAAPf1uAdaESA4AAAAAAAAAAAAAAAAAAAAAAAAAAAAAQAAAA4Ac3R1Yi13c3MtdG9rZW4V"
    "AGZpbGVzLmltby5pbS9kb3dubG9hZAAAAAAAAPf1uAdaESA4KgAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
)
STARTED = base64.b64decode(
    "TAAAAAINBADIAEUAAAAAAAAAAAAAAAoAc2FtcGxlLmJpbgAAAAAAAAAAAAAAAAAAAAD39bgHWhEgOAAAAAAAAAAAAAAAAAAAZAAAAA=="
)
PIECE = base64.b64decode("QAAAAAICBADIAEUAAAAAAAAAAAAAAAMAAAABAAAAAwAAAAEAAAADAEFCQwEAAAD39bgHWhEgOAEqAAAAAwAAAA==")
ACK = base64.b64decode("LgAAAAL1AwDIAEUAAAAAAAAAAAAAAAMAAAABAAAAAwAAAAEAAAD39bgHWhEgOA==")


class MediaSocket:
    def __init__(self):
        self.incoming = iter((STARTED[:7], STARTED[7:] + PIECE[:11], PIECE[11:]))
        self.sent = []
        self.closed = False

    def settimeout(self, value):
        assert value > 0

    def getstatus(self):
        return 101

    def send_binary(self, packet):
        self.sent.append(packet)

    def recv(self):
        return next(self.incoming, "")

    def shutdown(self):
        self.closed = True


class SignedInTransport:
    ssid = "fixture-ssid"

    def __init__(self, request):
        self.request = request

    def pop_event(self, names):
        return None

    def close(self):
        pass


def signed_in(request):
    client = IMOClient()
    client._transport = SignedInTransport(request)
    client._sign_on = {"uid": "fixture-uid", "phone_cc": "tm"}
    return client


def photo_message(**fields):
    return {"imdata": {"type": "photo_uploaded_2", "objects": [{"object_id": "imo/p123100x100", **fields}]}}


def test_nerv_download_matches_web_encoder(monkeypatch, tmp_path):
    socket = MediaSocket()

    def request(system, method, data):
        assert (system, method, data) == ("feproxy", "request_file_server",
                                          {"payload": SERVER_REQUEST, "uid": "fixture-uid"})
        return {"res": SERVER_RESPONSE}

    def connect(url, **options):
        assert url == "wss://files.imo.im/download?token=stub-wss-token"
        assert options == {"origin": "https://web.imo.im", "timeout": 15.0, "redirect_limit": 0}
        return socket

    monkeypatch.setattr(_nerv, "_REQUEST_IDS", iter((42,)))
    monkeypatch.setattr(_nerv.time, "time", lambda: 100)
    monkeypatch.setattr(_nerv, "create_connection", connect)
    message = {"imdata": {"type": "file_uploaded", "file_name": "report.bin",
                          "url": "https://files.imo.im/name?param=example", "file_size": "3"}}
    with signed_in(request) as client:
        (path,) = client.download_attachments(message, tmp_path)
    assert path.read_bytes() == b"ABC"
    assert path.name == "report.bin"
    assert socket.sent == [base64.b64decode(START_REQUEST), ACK]
    assert socket.closed
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("uid,expected", [
    ("fixture-uid", 4044251543752996343),
    ("b\xd6\xd6d\xd6\xd6\u0416\u04162cb\u04160\u0416\xd6a\u04160cca", 2696498110188612914),
    ("a" * 100, 4269740744738298403),
])
def test_nerv_hash_matches_browser(uid, expected):
    assert account_hash(uid) == expected


def test_nerv_refuses_mismatched_response_and_untrusted_socket():
    with pytest.raises(IMODownloadError, match="mismatched"):
        _nerv._server_response({"res": SERVER_RESPONSE}, 43, account_hash("fixture-uid"))
    raw = base64.b64decode(SERVER_RESPONSE).replace(b"files.imo.im/download", b"private.test/download")
    with pytest.raises(IMODownloadError, match="invalid file-server endpoint"):
        _nerv._server_response({"res": base64.b64encode(raw)}, 42, account_hash("fixture-uid"))


@pytest.mark.parametrize("mode,pattern", [("wrong-length", "invalid size"), ("too-large", "max_bytes"),
                                          ("out-of-order", "unexpected attachment piece")])
def test_nerv_refuses_bad_pieces(mode, pattern):
    socket = MediaSocket()
    piece = bytearray(PIECE)
    if mode == "wrong-length":
        piece[-4] = 1
    elif mode == "out-of-order":
        piece[34] = 2
    socket.incoming = iter((STARTED + piece,))
    with pytest.raises(IMODownloadError, match=pattern):
        list(_nerv._read_download(socket, 100, account_hash("fixture-uid"), "stub", 5,
                                  2 if mode == "too-large" else 32))
    assert socket.sent == []


def test_extract_attachments_preserves_multiple_originals():
    message = {"imdata": """{"type":"im","objects":[
        {"type":"image","object_id":"imo/photo","filename":"..\\/CON.jpg","filesize":"20"},
        {"object_type":"video","bigo_url":"remote/video.mp4","bigo_thumbnail_url":"remote/thumb.jpg"},
        {"type":"audio","http_url":"http://media.imoim.net/voice.ogg"},
        {"type":"object_reply","object_id":"ignored"}]}"""}
    attachments = extract_attachments(message)
    assert [(a.kind, a.size) for a in attachments] == [("photo", 20), ("video", None), ("audio", None)]
    assert attachments[0].filename == "_CON.jpg"
    assert attachments[1].filename == "video.mp4"
    assert attachments[1]._sources == (("nerv", "remote/video.mp4"),)
    assert attachments[2]._sources == (("https", "https://media.imoim.net/voice.ogg"),)
    assert "remote/video.mp4" not in repr(attachments[1])
    assert extract_attachments({"imdata": "{bad"}) == []
    assert extract_attachments({"imdata": {"type": "link", "url": "https://media.imoim.net/file"}}) == []
    assert extract_attachments({"imdata": {"type": "im", "replyTo": photo_message()["imdata"]}}) == []


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/private", "https://imo.im.attacker.test/a", "https://user@files.imo.im/a",
    "https://files.imo.im:444/a", "file:///private", "https://files.imo.im\\@attacker.test/a",
])
def test_extract_does_not_treat_unsafe_urls_as_download_sources(url):
    assert extract_attachments({"type": "file_uploaded", "url": url, "http_url": url}) == []


def test_pixel_download_ranges_and_preserves_existing_file(tmp_path):
    data = bytes(range(256)) * 53
    calls = []

    def request(system, method, params):
        assert (system, method) == ("pixeldownload", "get_photo")
        assert params["object_id"] == "p123"
        assert params["ssid"] == "fixture-ssid" and params["uid"] == "fixture-uid"
        assert params["transform"] == {}
        start, end = params["ranges"]
        calls.append((start, end))
        return {"total": len(data), "base64": base64.b64encode(data[start:end]).decode("ascii")}

    original = tmp_path / "photo.jpg"
    original.write_bytes(b"keep")
    message = photo_message(ext="jpg")
    with signed_in(request) as client:
        (saved,) = client.download_attachments(message, tmp_path)
    assert saved.name == "photo (1).jpg"
    assert saved.read_bytes() == data and original.read_bytes() == b"keep"
    assert calls == [(0, 12288), (12288, 24576)]


@pytest.mark.parametrize("reply,error", [
    ({"total": 5000, "base64": "QQ=="}, IMOAttachmentTooLarge),
    ({"total": 2, "base64": "QQ=="}, IMODownloadError),
    ({"total": 1, "base64": "!"}, IMODownloadError),
    ({"result": "fail", "reason": "not_found"}, IMOAttachmentUnavailable),
])
def test_pixel_failures_leave_no_file(tmp_path, reply, error):
    (attachment,) = extract_attachments(photo_message())
    with signed_in(lambda *_: reply) as client:
        with pytest.raises(error):
            client.download_attachment(attachment, tmp_path, max_bytes=200)
    assert list(tmp_path.iterdir()) == []


def test_transfer_fallback_replaces_partial_bytes(monkeypatch, tmp_path):
    def fail_after_data(*_):
        yield b"do not keep"
        raise IMODownloadError("file service went away")

    def request(system, method, params):
        assert (system, method) == ("pixeldownload", "get_photo")
        return {"total": 3, "base64": "QUJD"}

    monkeypatch.setattr(_media, "nerv_chunks", fail_after_data)
    with signed_in(request) as client:
        (path,) = client.download_attachments(photo_message(bigo_url="remote/image"), tmp_path)
    assert path.read_bytes() == b"ABC"


def test_cdn_redirect_checks_target():
    redirects = _media._MediaRedirects()
    req = _media.Request("https://profile.imo.im/picture")
    with pytest.raises(IMODownloadError, match="left"):
        redirects.redirect_request(req, None, 302, "", {}, "http://localhost/private")
    redirected = redirects.redirect_request(req, None, 302, "", {}, "https://room.imostatic.com/original")
    assert redirected.full_url == "https://room.imostatic.com/original"


class BytesResponse(io.BytesIO):
    status = 200

    def __init__(self, data, length):
        super().__init__(data)
        self.headers = {"Content-Length": str(length)}


def test_https_download_uses_no_signaling_and_validates_length(monkeypatch, tmp_path):
    body = BytesResponse(b"download", 8)

    class Opener:
        def open(self, request, *, timeout):
            assert request.full_url == "https://profile.imo.im/image.jpg"
            assert request.get_header("Cookie") is None
            assert timeout == 15
            return body

    def no_signaling(*_):
        raise AssertionError("HTTPS must never use signaling credentials")

    monkeypatch.setattr(_media, "build_opener", lambda _: Opener())
    message = {"type": "photo_uploaded", "http_url": "http://profile.imo.im/image.jpg"}
    with signed_in(no_signaling) as client:
        (path,) = client.download_attachments(message, tmp_path)
        assert path.read_bytes() == b"download"
        body = BytesResponse(b"download", 9)
        with pytest.raises(IMODownloadError, match="Incomplete"):
            client.download_attachments(message, tmp_path)
    assert list(tmp_path.iterdir()) == [path]


def test_client_requires_login_before_transfer(tmp_path):
    (attachment,) = extract_attachments(photo_message())
    with IMOClient() as client, pytest.raises(IMOLoginError):
        client.download_attachment(attachment, tmp_path)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.skipif(os.environ.get("IMO_WEB_LIVE") != "1", reason="Set IMO_WEB_LIVE=1 to check the public IMO CDN")
def test_public_imo_cdn_returns_image():
    # This public website asset exercises HTTPS independently of account access.
    data = b"".join(_media._https_chunks(
        "https://static-web.imoim.net/as/indigo-static/official/graphics/logo200.png", 15, 1024 * 1024
    ))
    assert data.startswith(b"\x89PNG\r\n\x1a\n")
