"""IMO Web signaling over a fresh, in-memory WebSocket session."""
from __future__ import annotations

from collections import deque
import json
import secrets
import string
import struct
import time
import zlib

from websocket import WebSocketException, WebSocketTimeoutException, create_connection


_ORIGIN = "https://web.imo.im"
_HOSTS = {
    "sgp": ("sgp-webstream.imo.im", "3g"),
    "sjc": ("webstream.imo.im", "3f"),
    "fra": ("fra-webstream.imo.im", "3h"),
}
_MAX_FRAME = 8 * 1024 * 1024
_MAX_EVENTS = 1024


class IMOError(Exception):
    """Base error for the IMO Web client."""


class IMOTransportError(IMOError):
    """The signaling connection closed or returned an invalid frame."""


class IMOTimeoutError(IMOError):
    """The operation's deadline elapsed."""


class IMORequestError(IMOError):
    """The server rejected a command or did not confirm its result."""


def random_id(size: int) -> str:
    return "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(size))


def encode_frame(message: dict) -> bytes:
    compressed = zlib.compress(json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    return struct.pack(">I", len(compressed)) + compressed


class FrameDecoder:
    def __init__(self):
        self._buffer = bytearray()

    def feed(self, data: bytes) -> list[dict]:
        self._buffer.extend(data)
        offset = 0
        messages = []
        while len(self._buffer) - offset >= 4:
            length = struct.unpack_from(">I", self._buffer, offset)[0]
            if not 0 < length <= _MAX_FRAME:
                raise IMOTransportError("Invalid IMO Web frame length")
            end = offset + 4 + length
            if len(self._buffer) < end:
                break
            try:
                inflater = zlib.decompressobj()
                decoded = inflater.decompress(self._buffer[offset + 4:end], _MAX_FRAME + 1)
                if not inflater.eof or inflater.unused_data or len(decoded) > _MAX_FRAME:
                    raise ValueError("invalid compressed frame")
                message = json.loads(decoded)
                if not isinstance(message, dict):
                    raise ValueError("invalid message")
            except (ValueError, UnicodeError, zlib.error):
                raise IMOTransportError("Invalid IMO Web frame payload") from None
            messages.append(message)
            offset = end
        del self._buffer[:offset]
        return messages


class WebTransport:
    """One connection. Calls are synchronous and must be serialized by the caller."""

    def __init__(self, region: str, timeout: float):
        if region not in _HOSTS:
            raise ValueError("region must be sgp, sjc or fra")
        self.host, prefix = _HOSTS[region]
        self.timeout = timeout
        self.ssid = prefix + random_id(15)
        self._device = random_id(32)
        self._client_token = random_id(32)
        self._ws = None
        self._decoder = FrameDecoder()
        self._frames = deque()
        self._uplink = 0
        self._downlink = 0
        self._queued = {}
        self._responses = {}
        self._events = deque()
        self._awaiting = None
        self._clock_offset = 0

    def open(self):
        try:
            self._ws = create_connection(
                f"wss://{self.host}/wss_webstream", origin=_ORIGIN, timeout=self.timeout,
            )
        except (WebSocketException, OSError):
            raise IMOTransportError("Unable to connect to IMO Web") from None
        try:
            now = time.time()
            self._send({
                "method": "name_channel",
                "headers": {"compression": ["zlib"], "is-alpha": False},
                "data": {
                    "name": f"{random_id(4)}0_web_socket_{int(now * 1000)}",
                    "ssid": self.ssid, "type": "websocket", "connection_type": "",
                    "carrier_code": "", "timestamp": int(now), "udid": self._device,
                    "cdn_domain": "webstream.imo.im",
                },
            })
            answer = self._receive(time.monotonic() + self.timeout)
            if answer.get("method") != "name_channel":
                raise IMOTransportError("IMO Web did not confirm the signaling channel")
            data = answer.get("data")
            timestamp = data.get("ts_nano") if isinstance(data, dict) else None
            if type(timestamp) is int and timestamp > 0:
                self._clock_offset = timestamp - time.time_ns()
        except Exception:
            self.close()
            raise

    def now_ns(self):
        return time.time_ns() + self._clock_offset

    def pop_event(self, names):
        for index, event in enumerate(self._events):
            if (event.get("type"), event.get("name")) in names:
                del self._events[index]
                return event
        return None

    def close(self):
        ws, self._ws = self._ws, None
        if ws is not None:
            try:
                ws.shutdown()
            except OSError:
                pass

    def _send(self, message):
        if self._ws is None:
            raise IMOTransportError("Signaling connection is closed")
        try:
            self._ws.settimeout(self.timeout)
            self._ws.send_binary(encode_frame(message))
        except (WebSocketException, OSError):
            raise IMOTransportError("Unable to send on the IMO Web connection") from None

    def _receive(self, deadline):
        if self._ws is None:
            raise IMOTransportError("Signaling connection is closed")
        while not self._frames:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise IMOTimeoutError("Timed out waiting for IMO Web")
            self._ws.settimeout(remaining)
            try:
                received = self._ws.recv()
            except WebSocketTimeoutException:
                raise IMOTimeoutError("Timed out waiting for IMO Web") from None
            except (WebSocketException, OSError):
                raise IMOTransportError("IMO Web disconnected") from None
            if not isinstance(received, bytes):
                raise IMOTransportError("IMO Web closed the signaling stream")
            self._frames.extend(self._decoder.feed(received))
        return self._frames.popleft()

    def _forward(self, messages):
        self._send({
            "method": "forward_to_server",
            "headers": {
                "ua": "imoWebApp/1.0.0; Python",
                "c": {"iat": self._client_token, "UDID": self._device},
                "sim_iso": None, "route_num": 0, "connection_type": "",
                "is-alpha": False, "ext_info": {"cdn_domain": "webstream.imo.im"},
            },
            "data": {"ack": self._downlink, "ssid": self.ssid, "messages": messages},
        })

    def _pump(self, deadline):
        frame = self._receive(deadline)
        body = frame.get("data")
        messages = body.get("messages") if isinstance(body, dict) else None
        if not isinstance(messages, list) or not messages:
            return
        for envelope in messages:
            if not isinstance(envelope, dict):
                continue
            if "RST" in (envelope.get("flags") or []):
                raise IMOTransportError("IMO Web reset the signaling session")
            target, seq = envelope.get("to"), envelope.get("seq")
            if not isinstance(target, dict) or target.get("ssid") != self.ssid:
                continue
            if type(seq) is int and seq >= self._downlink:
                self._queued.setdefault(seq, envelope.get("data"))
                if len(self._queued) > _MAX_EVENTS:
                    raise IMOTransportError("IMO Web sequence buffer exceeded its limit")
        while self._downlink in self._queued:
            body = self._queued.pop(self._downlink)
            self._downlink += 1
            if not isinstance(body, dict):
                continue
            request_id = body.get("request_id")
            if request_id is not None and request_id == self._awaiting:
                if "response" not in body:
                    raise IMOTransportError("IMO Web omitted the response payload")
                self._responses[request_id] = body["response"]
            elif "name" in body and "type" in body:
                if len(self._events) >= _MAX_EVENTS:
                    self._events.popleft()
                self._events.append(body)
        self._forward([])

    def request(self, system, method, params, *, response=True):
        request_id = random_id(8)
        seq = self._uplink
        self._uplink += 1
        self._awaiting = request_id if response else None
        try:
            self._forward([{
                "data": {"data": params, "request_id": request_id, "method": method},
                "seq": seq, "to": {"system": system}, "from": {"system": "client", "ssid": self.ssid},
            }])
            if not response:
                return None
            deadline = time.monotonic() + self.timeout
            while request_id not in self._responses:
                self._pump(deadline)
            return self._responses.pop(request_id)
        except (IMOTimeoutError, IMOTransportError):
            # A command may already have reached the service. In particular, never retry send_im.
            self.close()
            raise
        finally:
            self._awaiting = None

    def wait_event(self, names, deadline):
        while True:
            event = self.pop_event(names)
            if event is not None:
                return event
            self._pump(deadline)
