"""Fresh QR login and account operations for the IMO Web protocol."""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from pathlib import Path
import time

from ._media import Attachment, extract_attachments, save_attachment
from ._web_transport import (
    IMOError, IMORequestError, IMOTimeoutError, IMOTransportError, WebTransport, random_id,
)
from .models import Head


_SESSION_ENDED = {("pin", "not_authenticated"), ("session", "signoff_all")}


class IMOLoginError(IMOError):
    """Login was rejected, cancelled, or has not yet completed."""


@dataclass(frozen=True)
class QRChallenge:
    """A short-lived QR payload. Treat it as private and render it locally."""

    payload: str = field(repr=False)
    ttl: int


@dataclass(frozen=True)
class SentMessage:
    buid: str
    message_id: str
    timestamp_nano: str


class IMOClient:
    """Synchronous, in-memory IMO Web client with a separate QR login."""

    def __init__(self, *, region="sgp", timeout=15.0, language="en"):
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be positive")
        self._region = region
        self._timeout = timeout
        self._language = language
        self._transport = None
        self._challenge = None
        self._challenge_expires = 0.0
        self._sign_on = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()

    @property
    def is_authenticated(self):
        return self._sign_on is not None

    def close(self):
        if self._transport is not None:
            self._transport.close()
        self._transport = None
        self._challenge = None
        self._sign_on = None

    def begin_qr_login(self) -> QRChallenge:
        """Start a new web session and request a QR for the official mobile app."""
        self.close()
        transport = WebTransport(self._region, self._timeout)
        self._transport = transport
        try:
            transport.open()
            reply = transport.request("imo_account_proxy", "request_qr_code", {"ssid": transport.ssid})
            result = self._result(reply, "request_qr_code")
            payload, ttl = result.get("qr_link"), result.get("code_ttl")
            if not isinstance(payload, str) or not payload or type(ttl) is not int or ttl <= 0:
                raise IMORequestError("IMO Web returned an invalid QR challenge")
            self._challenge = QRChallenge(payload, ttl)
            self._challenge_expires = time.monotonic() + ttl
            return self._challenge
        except Exception:
            self.close()
            raise

    def wait_for_login(self, *, timeout=None) -> None:
        """Wait for scanning and mobile confirmation, then wait for server signed_on."""
        if self._challenge is None or self._transport is None:
            raise IMOLoginError("Call begin_qr_login first")
        if timeout is not None and (not math.isfinite(timeout) or timeout <= 0):
            raise ValueError("timeout must be positive")
        transport = self._transport
        deadline = self._challenge_expires
        limit = time.monotonic() + timeout if timeout is not None else None
        try:
            while True:
                event = transport.wait_event({
                    ("session", "qr_code_scanned"),
                    ("session", "qr_code_login_completed"),
                    ("session", "qr_code_login_cancelled"),
                }, min(deadline, limit) if limit is not None else deadline)
                name = event["name"]
                if name == "qr_code_login_cancelled":
                    raise IMOLoginError("QR login was cancelled")
                if name == "qr_code_login_completed":
                    break
                extra = event.get("edata")
                ttl = extra.get("bind_ttl") if isinstance(extra, dict) else None
                if type(ttl) is int and ttl > 0:
                    deadline = time.monotonic() + ttl
            now = time.time_ns() // 1_000_000
            transport.request("session", "cookie_login", {
                "reason": "scan_login", "active": True, "timestamp": now,
                "last_unread_ts_nano": 0, "lang": self._language, "ssid": transport.ssid,
                "extras": {"device_info": {
                    "lang": self._language, "time_zone": "UTC GMT+00:00", "current_time": now,
                }},
            }, response=False)
            deadline = time.monotonic() + self._timeout
            event = transport.wait_event({
                ("account", "signed_on"), ("session", "cookie_login_failed"),
            }, min(deadline, limit) if limit is not None else deadline)
            if event["name"] != "signed_on" or not isinstance(event.get("uid"), str) or not event["uid"]:
                raise IMOLoginError("IMO Web rejected the QR login")
            self._sign_on = {"uid": event["uid"]}
            profile = event.get("edata")
            if isinstance(profile, dict):
                for key in ("alias", "imo_id", "phone_cc", "profile_photo_id"):
                    if isinstance(profile.get(key), str):
                        self._sign_on[key] = profile[key]
            self._challenge = None
        except Exception:
            self.close()
            raise

    def get_me(self) -> dict:
        """Return the profile supplied by signed_on for this session."""
        if self._sign_on is None:
            raise IMOLoginError("QR login has not completed")
        return dict(self._sign_on)

    def get_contacts(self) -> list[Head]:
        """Fetch the account's contact list, following server pagination."""
        cursor = "0"
        seen = set()
        contacts = {}
        while True:
            result = self._result(self._account_request("pin", "sync_full_buddies", {"cursor": cursor}),
                                  "sync_full_buddies")
            buddies = result.get("buddies")
            if not isinstance(buddies, list):
                raise IMORequestError("IMO Web returned an invalid contact page")
            for record in buddies:
                if isinstance(record, dict) and isinstance(record.get("buid"), str) and record["buid"]:
                    contacts[record["buid"]] = Head.from_json(record)
            if not result.get("has_more"):
                return list(contacts.values())
            cursor = result.get("next_cursor")
            if not isinstance(cursor, str) or not cursor or cursor in seen:
                raise IMORequestError("IMO Web returned an invalid contact cursor")
            seen.add(cursor)

    def get_history(self, buid: str, *, limit=50, before=None) -> list[dict]:
        """Fetch a page, newest first. Use the last timestamp_nano_str as before."""
        self._validate_buid(buid)
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        if before is not None and (not isinstance(before, str) or not before.isascii() or not before.isdecimal()):
            raise ValueError("before must be a nanosecond timestamp string")
        self._require_session()
        end = before if before is not None else str(self._transport.now_ns())
        reply = self._account_request("convhistory", "get_conversation", {
            "buid": buid, "from_end": True, "proto": "imo", "limit": limit,
            "start_time": "0", "end_time": end,
        })
        if reply is None:
            return []
        if not isinstance(reply, list) or not all(isinstance(row, dict) for row in reply):
            raise IMORequestError("IMO Web returned an invalid conversation page")
        return reply

    def get_chats(self) -> list[dict]:
        """Read the chat index and apply its update/delete records."""
        reply = self._account_request("pin", "sync_chat_changes", {"last_ts": 0, "last_ts_v2": 0})
        changes = reply.get("result") if isinstance(reply, dict) and reply.get("status") == "success" else None
        if not isinstance(changes, list) or not all(isinstance(change, dict) for change in changes):
            raise IMORequestError("IMO Web returned an invalid chat index")
        try:
            ordered = sorted(changes, key=lambda change: int(change.get("change_ts") or 0))
        except (ValueError, TypeError, OverflowError):
            raise IMORequestError("IMO Web returned an invalid chat change timestamp") from None
        chats = {}
        for change in ordered:
            kind, buid = change.get("type"), change.get("buid")
            if kind == "delete_all_chat":
                chats.clear()
            elif isinstance(buid, str) and buid:
                if kind == "delete":
                    chats.pop(buid, None)
                elif kind == "update":
                    chats.pop(buid, None)
                    chats[buid] = change
        return list(reversed(list(chats.values())))

    def receive_message(self, *, timeout=None) -> dict:
        """Wait for one incoming recv_im push and return its message payload."""
        transport = self._require_session()
        timeout = self._timeout if timeout is None else timeout
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be positive")
        deadline = time.monotonic() + timeout
        while True:
            try:
                event = transport.wait_event(_SESSION_ENDED | {("conv", "recv_im")}, deadline)
            except IMOTransportError:
                self.close()
                raise
            if (event["type"], event["name"]) in _SESSION_ENDED:
                self.close()
                raise IMOLoginError("IMO Web ended this session")
            data = event.get("edata")
            if isinstance(data, dict):
                return data

    def download_attachment(self, attachment: Attachment, directory, *, max_bytes=256 * 1024 * 1024) -> Path:
        """Save one attachment and return its path, preserving any existing file."""
        transport = self._require_session()
        return save_attachment(attachment, directory, request=self._account_request, ssid=transport.ssid,
                               uid=self._sign_on["uid"], country=self._sign_on.get("phone_cc", "").upper(),
                               timeout=self._timeout, max_bytes=max_bytes)

    def download_attachments(self, message, directory, *, max_bytes=256 * 1024 * 1024) -> list[Path]:
        """Save originals from one history row or incoming message, in message order."""
        return [self.download_attachment(attachment, directory, max_bytes=max_bytes)
                for attachment in extract_attachments(message)]

    def logout(self):
        """Log out the current web session with the server."""
        transport = self._require_session()
        reply = self._account_request("imo_account_manager", "logout", {"ssid": transport.ssid})
        if not isinstance(reply, dict) or reply.get("status") != "success":
            raise IMORequestError("IMO Web did not confirm logout")
        self.close()

    def send_message(self, buid: str, text: str) -> SentMessage:
        """Send text to a conversation ID. A timeout does not establish delivery status."""
        self._validate_buid(buid)
        if not isinstance(text, str) or not text.strip():
            raise ValueError("text must be nonempty")
        msg_id = random_id(8)
        reply = self._account_request("pin", "send_im", {
            "buid": buid, "msg": text,
            "imdata": {"type": "im", "msg_id": msg_id, "trace_id": random_id(16)},
        })
        timestamp = reply.get("timestamp_nano_str") if isinstance(reply, dict) else None
        if not isinstance(timestamp, str) or not timestamp.isdecimal():
            raise IMORequestError("IMO Web did not confirm the message; check the conversation before resending")
        return SentMessage(buid, msg_id, timestamp)

    def _require_session(self):
        if self._sign_on is None or self._transport is None:
            raise IMOLoginError("QR login has not completed")
        return self._transport

    def _account_request(self, system, method, params):
        transport = self._require_session()
        try:
            reply = transport.request(system, method, {**params, "uid": self._sign_on["uid"]})
        except (IMOTimeoutError, IMOTransportError):
            self.close()
            raise
        if method != "logout" and transport.pop_event(_SESSION_ENDED) is not None:
            self.close()
            raise IMOLoginError("IMO Web ended this session")
        return reply

    @staticmethod
    def _result(reply, method):
        if not isinstance(reply, dict) or reply.get("status") != "success" or not isinstance(reply.get("result"), dict):
            raise IMORequestError(f"IMO Web did not return a successful {method} result")
        return reply["result"]

    @staticmethod
    def _validate_buid(buid):
        if not isinstance(buid, str) or not buid.strip():
            raise ValueError("buid must be a conversation ID returned by IMO")
