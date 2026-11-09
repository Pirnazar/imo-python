"""Nerv file downloads negotiated through the active IMO Web session."""
from __future__ import annotations

import base64
from itertools import count
import re
from struct import Struct, pack
import time

from websocket import WebSocketException, WebSocketTimeoutException, create_connection

from ._media_endpoints import media_url
from ._media_identity import account_hash
from ._web_transport import _ORIGIN, IMORequestError


class IMODownloadError(IMORequestError):
    """A download could not be completed or verified."""


class IMOAttachmentUnavailable(IMODownloadError):
    """The attachment has expired or is unavailable on the storage server."""


class IMOAttachmentTooLarge(IMODownloadError):
    """The transfer exceeded the requested byte limit."""


_HEADER = Struct("<IIH")
_REQUEST_SERVER = 18032898
_SERVER_ROUTE = 16182018
_SERVER_RESULT = 17930754
_START = 260354
_STARTED = 265474
_PIECE = 262658
_PIECE_ACK = 259330
_PING = 2587138
_PONG = 2587394
_REQUEST_ERROR = 262146
_SERVER_ERROR = 264450
_STATISTICS = 2637314
_REQUEST_IDS = count(int(time.time()) + 234881024)
_MAX_PACKET = 1024 * 1024


def _string(value):
    raw = value.encode("utf-8")
    if len(raw) > 65535:
        raise IMODownloadError("Nerv field exceeds its wire size limit")
    return pack("<H", len(raw)) + raw


def _packet(uri, payload):
    return _HEADER.pack(len(payload) + _HEADER.size, uri, 200) + payload


class _Reader:
    def __init__(self, data):
        self.data = data
        self.offset = 0

    def read(self, length):
        end = self.offset + length
        if end > len(self.data):
            raise IMODownloadError("Truncated Nerv packet")
        value = self.data[self.offset:end]
        self.offset = end
        return value

    def uint(self, length):
        return int.from_bytes(self.read(length), "little")

    def blob(self, length_size=2):
        return self.read(self.uint(length_size))

    def text(self):
        try:
            return self.blob().decode("utf-8")
        except UnicodeDecodeError:
            raise IMODownloadError("Invalid UTF-8 in Nerv response") from None

    def skip_rows(self, widths):
        for _ in range(self.uint(4)):
            for width in widths:
                if width:
                    self.read(width)
                else:
                    self.blob()

    def skip_endpoints(self, *, udp=False):
        for _ in range(self.uint(4)):
            self.read(4)
            self.skip_rows((2,))
            if udp:
                self.skip_rows((2,))


def _server_request(request_id, uid64, country):
    payload = (
        pack("<III", request_id, 0, 0) + _string(country) +
        pack("<IQIQ", 2, 0, 62, uid64) +
        pack("<IHIHH", 0, 0, 0, 0, 0) + _string(country) +
        pack("<BIIBI", 0, 1, 1010000, 100, 1) +
        _string("taskfrom") + _string("web")
    )
    return base64.b64encode(_packet(_REQUEST_SERVER, payload)).decode("ascii")


def _server_response(response, request_id, uid64):
    try:
        raw = base64.b64decode(response["res"], validate=True)
    except (ValueError, TypeError, KeyError):
        raise IMODownloadError("IMO Web did not return a Nerv file server") from None
    if len(raw) < _HEADER.size or _HEADER.unpack_from(raw) != (len(raw), _SERVER_ROUTE, 200):
        raise IMODownloadError("Invalid Nerv file-server routing response")
    routed = _Reader(raw[_HEADER.size:])
    routed.read(1)  # TTL
    routed.blob()  # origin
    uri, status = routed.uint(4), routed.uint(2)
    inner = _Reader(routed.blob(4))
    if (uri, status, routed.uint(8), routed.uint(4)) != (_SERVER_RESULT, 200, uid64, request_id):
        raise IMODownloadError("Nerv returned a mismatched file-server route")
    if (inner.uint(4), inner.uint(4)) != (request_id, 200):
        raise IMODownloadError("Nerv refused the file-server request")
    endpoint = _Reader(inner.blob())
    endpoint.read(20)  # legacy connection metadata
    endpoint.skip_endpoints(udp=True)
    endpoint.read(14 * 4)  # transport policy
    token = endpoint.text()
    endpoint.skip_endpoints()
    endpoint.read(8)
    if endpoint.uint(8) != uid64:
        raise IMODownloadError("Nerv returned a file server for a different account")
    endpoint.skip_endpoints()
    endpoint.read(1)
    for _ in range(4):
        endpoint.skip_endpoints()
    count_tokens = endpoint.uint(4)
    if count_tokens > 32:
        raise IMODownloadError("Invalid number of Nerv WebSocket tokens")
    tokens = [endpoint.text() for _ in range(count_tokens)]
    address = media_url("wss://" + endpoint.text(), websocket=True)
    if not address or not token or not tokens or not all(re.fullmatch(r"[A-Za-z0-9%_+./=~:-]+", item)
                                                         for item in tokens):
        raise IMODownloadError("Nerv returned an invalid file-server endpoint")
    return address, tokens, token


def _start_request(seq, uid64, country, token, reference):
    path, separator, query = reference.partition("?")
    extensions = [(1, country), (5001, "web")] if country else [(5001, "web")]
    payload = (
        pack("<QI", 0, 0) + _string(path) +
        pack("<IIBBII", 0, 0, 0, 0, 0, 0) + _string(separator + query) +
        pack("<BBIIIIIB", 0, 0, 0, 0, 0, 0, 0, 1) + _string(token) +
        pack("<QII", uid64, 0, len(extensions)) +
        b"".join(pack("<H", key) + _string(value) for key, value in extensions) +
        pack("<IIII", 0, 0xFFFFFFFF, 0, seq)
    )
    return _packet(_START, payload)


def _read_download(ws, seq, uid64, token, timeout, max_bytes):
    pending = bytearray()
    deadline = time.monotonic() + timeout
    ping_at = time.monotonic() + 10
    task_id = None
    next_piece = 1
    size = None
    received = 0
    while True:
        now = time.monotonic()
        if now >= deadline:
            raise IMODownloadError("Timed out receiving Nerv attachment")
        if now >= ping_at:
            ws.settimeout(deadline - now)
            ws.send_binary(_packet(_PING, pack("<QII", uid64, int(time.time()) & 0xFFFFFFFF, 0) + _string(token)))
            ping_at = now + 10
        ws.settimeout(min(deadline, ping_at) - now)
        try:
            incoming = ws.recv()
        except WebSocketTimeoutException:
            continue
        if not isinstance(incoming, bytes) or not incoming:
            raise IMODownloadError("Nerv closed the download stream")
        pending.extend(incoming)
        consumed = 0
        while len(pending) - consumed >= _HEADER.size:
            length, uri, status = _HEADER.unpack_from(pending, consumed)
            if not _HEADER.size <= length <= _MAX_PACKET:
                raise IMODownloadError("Invalid Nerv packet length")
            end = consumed + length
            if end > len(pending):
                break
            body = _Reader(bytes(pending[consumed + _HEADER.size:end]))
            consumed = end
            if status in (204, 404, 410):
                raise IMOAttachmentUnavailable("Nerv attachment has expired or is unavailable")
            if status != 200:
                raise IMODownloadError(f"Nerv file server returned status {status}")
            if uri == _STARTED:
                new_task = body.uint(8)
                body.read(4)
                body.blob()
                body.read(16)
                if body.uint(8) != uid64:
                    raise IMODownloadError("Nerv returned a download for a different account")
                body.blob()
                body.skip_rows((0, 4))
                body.skip_rows((0, 4))
                body.skip_rows((0, 0))
                if body.uint(4) != seq or not new_task or task_id is not None:
                    raise IMODownloadError("Invalid Nerv download start")
                task_id = new_task
                deadline = time.monotonic() + timeout
            elif uri == _PIECE:
                piece_task = body.uint(8)
                uid, total, pieces, piece_size, serial = (body.uint(4) for _ in range(5))
                data, last = body.blob(), body.uint(1)
                body.blob()  # hash field
                body.read(1)  # request level
                piece_uid, flags = body.uint(8), body.uint(1)
                if flags & 1:
                    body.read(4)
                file_size = body.uint(4)
                if (task_id is None or piece_task != task_id or piece_uid != uid64 or serial != next_piece
                        or last not in (0, 1)):
                    raise IMODownloadError("Nerv returned an unexpected attachment piece")
                if file_size > max_bytes or received + len(data) > max_bytes:
                    raise IMOAttachmentTooLarge("Attachment exceeds max_bytes")
                if file_size and size not in (None, file_size):
                    raise IMODownloadError("Nerv attachment size changed during download")
                if file_size:
                    size = file_size
                received += len(data)
                if size is not None and (received > size or (last and received != size)):
                    raise IMODownloadError("Nerv attachment has an invalid size")
                if (not data and not last) or (last and size is None and received):
                    raise IMODownloadError("Nerv returned an incomplete attachment")
                ws.settimeout(timeout)
                ws.send_binary(_packet(_PIECE_ACK, pack("<QIIIIIQ", task_id, uid, total, pieces,
                                                        piece_size, serial, uid64)))
                next_piece += 1
                deadline = time.monotonic() + timeout
                yield data
                if last:
                    return
            elif uri in (_REQUEST_ERROR, _SERVER_ERROR):
                body.read(12)
                body.blob()
                if uri == _REQUEST_ERROR:
                    body.blob()
                code = body.uint(4)
                if code in (204, 404, 410):
                    raise IMOAttachmentUnavailable("Nerv attachment has expired or is unavailable")
                raise IMODownloadError(f"Nerv rejected the attachment request ({code})")
            elif uri not in (_PONG, _STATISTICS):
                raise IMODownloadError("Unexpected Nerv download packet")
        del pending[:consumed]


def nerv_chunks(request, uid, country, reference, timeout, max_bytes):
    uid64 = account_hash(uid)
    request_id = next(_REQUEST_IDS) & 0xFFFFFFFF
    response = request("feproxy", "request_file_server", {"payload": _server_request(request_id, uid64, country)})
    address, tokens, token = _server_response(response, request_id, uid64)
    ws = None
    for websocket_token in tokens[:2]:
        try:
            candidate = create_connection(address + "?token=" + websocket_token, origin=_ORIGIN,
                                          timeout=timeout, redirect_limit=0)
        except (WebSocketException, OSError):
            continue
        if candidate.getstatus() == 101:
            ws = candidate
            break
        candidate.shutdown()
    if ws is None:
        raise IMODownloadError("Unable to connect to the Nerv file server")
    try:
        seq = int(time.time()) & 0xFFFFFFFF
        ws.send_binary(_start_request(seq, uid64, country, token, reference))
        yield from _read_download(ws, seq, uid64, token, timeout, max_bytes)
    except (WebSocketException, OSError):
        raise IMODownloadError("Nerv file connection failed") from None
    finally:
        ws.shutdown()
