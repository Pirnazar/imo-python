"""Send one local file using IMO Web's Nerv batch upload with backend notification."""
from __future__ import annotations

from hashlib import md5
import json
import os
from stat import S_ISREG
from struct import pack
import time
from zlib import crc32

from websocket import WebSocketException, WebSocketTimeoutException

from ._nerv import IMODownloadError, _HEADER, _MAX_PACKET, _Reader, _open_file_server, _packet, _string
from ._web_transport import IMORequestError, _USER_AGENT, random_id
from .models import _timestamp


_BATCH_REQUEST = 2592002
_BATCH_REGISTERED = 2592258
_BATCH_RESULT = 2592514
_FILE_REQUEST = 258562
_FILE_REGISTERED = 258818
_FILE_PIECE = 259074
_PIECE_ACK = 259330
_UPLOAD_FAILED = 262402
_FILE_ERROR = 264450
_UPLOAD_PING = 265986
_PIECE_SIZE = 256 * 1024
_MAX_UPLOAD_SIZE = 256 * 1024 * 1024


class IMOUploadError(IMORequestError):
    """IMO Web did not confirm a file upload. Check the chat before retrying."""


def _json(data):
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def _ext_info(key, value):
    return pack("<IH", 1, key) + _string(value)


def _blob32(data):
    return pack("<I", len(data)) + data


def _file_registration(seq, uid64, country, token, filename, size, pieces, digest, checksum):
    metadata = {4: country, 50: digest, 60: "true", 5001: "web", 60000: "1.0.0"}
    query = {"autoIdx": "1", "offset": "0", "size": str(size), "crc": str(checksum)}
    return (
        pack("<QIIII", 0, 0, size, pieces, _PIECE_SIZE) + _string(filename) +
        _string("") * 3 + pack("<II", 0, 61) + _string("") +
        pack("<I", len(metadata)) +
        b"".join(pack("<I", key) + _string(value) for key, value in metadata.items()) +
        pack("<I", checksum) + _string(token) + pack("<QIII", uid64, seq, 0, 0) +
        _string("") + pack("<I", len(query)) +
        b"".join(_string(key) + _string(value) for key, value in query.items()) +
        pack("<I", 0)
    )


def _batch_request(batch_seq, uid64, backend, registration, file_info):
    entry = (pack("<I", _FILE_REQUEST) + _string("") +
             _ext_info(1, _json(file_info)) + _blob32(registration))
    return _packet(_BATCH_REQUEST, pack("<IIQHI", 62, batch_seq, uid64, 1, 0) +
                   _ext_info(1, _json(backend)) + pack("<I", 1) + _blob32(entry))


def _file_piece(task_id, uid64, size, pieces, index, serial, data):
    length = len(data)
    digest = md5(data).hexdigest()  # Protocol checksum.
    return _packet(_FILE_PIECE, pack("<QIIIII", task_id, 0, size, pieces, length, serial) +
                   pack("<I" if length >= 65535 else "<H", length) + data +
                   pack("<I", int(index == pieces)) + _string(digest) +
                   pack("<IIIIIIQ", 0, 0, 0, 0, 2, index, uid64))


def _batch_timestamp(body, batch_id, batch_seq):
    task_id, seq, status = body.uint(8), body.uint(4), body.uint(2)
    if task_id != batch_id or seq not in (0, batch_seq) or status:
        raise IMOUploadError("Nerv did not confirm the upload batch")
    body.skip_rows((0,))  # per-file responses
    result = None
    for _ in range(body.uint(4)):
        key, value = body.uint(2), body.text()
        if key == 1:
            result = value
    try:
        reply = json.loads(result)
        timestamp = _timestamp(reply["result"]["object_data"]["timestamp_nano_str"])
        if reply.get("status") != "failed" and timestamp:
            return timestamp
    except (TypeError, KeyError, ValueError):
        pass
    raise IMOUploadError("IMO Web did not confirm the file message. Check the chat before resending")


class _UploadSocket:
    def __init__(self, socket, uid64, token, timeout):
        self.socket = socket
        self.uid64 = uid64
        self.token = token
        self.timeout = timeout
        self.ping_at = time.monotonic() + 10
        self.pending = bytearray()

    def send(self, packet):
        self.socket.settimeout(self.timeout)
        self.socket.send_binary(packet)

    def receive(self, deadline):
        while True:
            if len(self.pending) >= _HEADER.size:
                length, uri, status = _HEADER.unpack_from(self.pending)
                if not _HEADER.size <= length <= _MAX_PACKET:
                    raise IMOUploadError("Invalid Nerv upload packet length")
                if len(self.pending) >= length:
                    body = _Reader(bytes(self.pending[_HEADER.size:length]))
                    del self.pending[:length]
                    if status != 200:
                        raise IMOUploadError(f"Nerv upload server returned status {status}")
                    return uri, body

            now = time.monotonic()
            if now >= deadline:
                raise IMOUploadError("Timed out waiting for upload confirmation. Check the chat before resending")
            if now >= self.ping_at:
                payload = pack("<IQIBIIQ", 0, time.time_ns() // 1_000_000, 1, 0, 0, 0, self.uid64)
                self.send(_packet(_UPLOAD_PING, payload + _string(self.token)))
                self.ping_at = now + 10
            self.socket.settimeout(min(deadline, self.ping_at) - now)
            try:
                data = self.socket.recv()
            except WebSocketTimeoutException:
                continue
            if not isinstance(data, bytes) or not data:
                raise IMOUploadError("Nerv closed the upload stream. Check the chat before resending")
            self.pending.extend(data)


def _finish_upload(channel, file, uid64, batch_seq, file_seq, size, pieces):
    batch_id = task_id = None
    offset = index = serial = acknowledged = 0
    deadline = time.monotonic() + channel.timeout
    while True:
        uri, body = channel.receive(deadline)
        if uri == _BATCH_REGISTERED:
            new_batch, seq, status = body.uint(8), body.uint(4), body.uint(2)
            if seq != batch_seq or status or not new_batch or batch_id not in (None, new_batch):
                raise IMOUploadError("Nerv rejected upload batch registration")
            batch_id = new_batch
        elif uri == _FILE_REGISTERED:
            new_task = body.uint(8)
            body.read(4)
            start = body.uint(4)
            body.blob()
            status = body.uint(4)
            body.read(4)
            if (body.uint(8) not in (0, uid64) or body.uint(4) != file_seq or
                    not new_task or status or start > size):
                raise IMOUploadError("Nerv rejected file registration")
            if task_id is not None:
                if task_id != new_task:
                    raise IMOUploadError("Nerv changed the upload task ID")
                continue
            task_id = new_task
            offset = size if start == size else start // _PIECE_SIZE * _PIECE_SIZE
            index = offset // _PIECE_SIZE
            file.seek(offset)
        elif uri == _PIECE_ACK:
            ack_task = body.uint(8)
            body.read(16)
            piece = body.uint(4)
            if ack_task != task_id or body.uint(8) not in (0, uid64) or not 1 <= piece <= serial:
                raise IMOUploadError("Nerv acknowledged an unexpected upload piece")
            if piece <= acknowledged:
                continue
            acknowledged = piece
        elif uri == _BATCH_RESULT:
            return _batch_timestamp(body, batch_id, batch_seq)
        elif uri in (_UPLOAD_FAILED, _FILE_ERROR):
            raise IMOUploadError("Nerv rejected the upload. Check the chat before resending")
        else:
            # Upload pongs and independent file-info notifications carry no message receipt.
            continue

        deadline = time.monotonic() + channel.timeout
        if task_id is not None and offset < size and serial == acknowledged:
            length = min(_PIECE_SIZE, size - offset)
            data = file.read(length)
            if len(data) != length:
                raise IMOUploadError("Local file changed during the upload")
            index += 1
            serial += 1
            channel.send(_file_piece(task_id, uid64, size, pieces, index, serial, data))
            offset += length


def _stream_id(uid, buid):
    if buid.endswith(";"):
        return "groups:" + buid.split(";", 1)[0]
    if uid == buid:
        return "private:" + uid
    return "pair:imo#" + "#".join(sorted((uid, buid), key=lambda value: value.encode("utf-16-be")))


def send_file(request, transport, uid, country, buid, path, msg_id, trace_id, timeout):
    if not path.is_file():
        raise ValueError("media must point to a local file")
    with path.open("rb") as file:
        initial = os.fstat(file.fileno())
        size = initial.st_size
        if not S_ISREG(initial.st_mode) or not 0 < size <= _MAX_UPLOAD_SIZE:
            raise ValueError("media must be a nonempty regular file of at most 256 MiB")
        digest = md5()  # Protocol checksum.
        checksum = 0
        remaining = size
        while remaining:
            data = file.read(min(2 * 1024 * 1024, remaining))
            if not data:
                raise ValueError("media file changed while preparing the upload")
            remaining -= len(data)
            digest.update(data)
            checksum = crc32(data, checksum)
        current = os.fstat(file.fileno())
        if (current.st_size, current.st_mtime_ns) != (size, initial.st_mtime_ns):
            raise ValueError("media file changed while preparing the upload")
        file.seek(0)

        try:
            ws, uid64, token = _open_file_server(request, uid, country, timeout, request_type=1)
            try:
                file_seq = (time.time_ns() // 1_000_000) & 0xFFFFFFFF
                batch_seq = (file_seq + 1) & 0xFFFFFFFF
                pieces = (size + _PIECE_SIZE - 1) // _PIECE_SIZE
                checksum &= 0xFFFFFFFF
                registration = _file_registration(file_seq, uid64, country, token, path.name,
                                                  size, pieces, digest.hexdigest(), checksum)
                backend = {
                    "uid": uid, "client_info": {
                        "udid": transport.device_id, "full-user-agent": _USER_AGENT, "user-agent": "imoWebApp 1.0.0",
                        "signup_cc": country, "file_trace_id": trace_id,
                    }, "object_type": "file", "stream_id": _stream_id(uid, buid),
                    "imdata": {
                        "type": "bigo_uploaded", "msg_id": msg_id, "trace_id": trace_id,
                        "file_name": path.name, "ext": path.suffix.lstrip("."), "file_size": size,
                    }, "task_id": f"{random_id(10)}_{time.time_ns() // 1_000_000}", "ssid": transport.ssid,
                }
                info = {"file_size": size, "url": "", "key": "object_url", "md5": digest.hexdigest()}
                channel = _UploadSocket(ws, uid64, token, timeout)
                channel.send(_batch_request(batch_seq, uid64, backend, registration, info))
                return _finish_upload(channel, file, uid64, batch_seq, file_seq, size, pieces)
            finally:
                ws.shutdown()
        except IMODownloadError as error:
            raise IMOUploadError(str(error)) from None
        except (WebSocketException, OSError):
            raise IMOUploadError("Nerv file connection failed. Check the chat before resending") from None
