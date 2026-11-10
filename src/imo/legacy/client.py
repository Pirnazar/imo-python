"""Fresh QR login and account operations for the IMO Web protocol."""
from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from inspect import iscoroutinefunction
import math
from pathlib import Path
import random
import sys
import time

from ._media import Attachment, extract_attachments, save_attachment
from ._nerv_upload import send_file
from ._web_transport import (
    IMOError, IMORequestError, IMOTimeoutError, IMOTransportError, WebTransport, random_id,
    _LOGIN_CHALLENGE_EVENTS, _LOGIN_RESULT_EVENTS, _MESSAGE_EVENTS, _SESSION_ENDED,
)
from ..models import Head
from .web_models import Chat, GroupMember, WebMessage, _timestamp


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


class IMOPartialSendError(IMORequestError):
    """The attachment was confirmed, but the following text was not confirmed."""

    def __init__(self, attachment: SentMessage, cause: IMOError):
        super().__init__("IMO confirmed the attachment but did not confirm the text. Check the chat before resending")
        self.attachment = attachment
        self.cause = cause


class IMOContactNotFound(IMOError, LookupError):
    """No contact, or more than one, matches the requested name."""


@dataclass(frozen=True)
class SendResult:
    """Outcome of one row of send_many. Exactly one of sent and error is set."""

    target: str
    text: str
    sent: SentMessage | None = None
    error: IMOError | None = None

    @property
    def ok(self) -> bool:
        return self.sent is not None


def _fold(value) -> str:
    return " ".join(value.split()).casefold() if isinstance(value, str) else ""


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
        self._message_handlers: list[Callable[[WebMessage], None]] = []
        self._running = False
        self._stop_requested = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()

    @property
    def is_authenticated(self):
        return self._sign_on is not None

    def close(self):
        self.stop()
        if self._transport is not None:
            self._transport.close()
        self._transport = None
        self._challenge = None
        self._sign_on = None

    def connect(self, *, show_qr: Callable[[QRChallenge], None] | None = None,
                timeout: float | None = None) -> None:
        """Open a fresh QR session and wait for confirmation in the official phone app."""
        if self.is_authenticated:
            return
        if timeout is not None and (not math.isfinite(timeout) or timeout <= 0):
            raise ValueError("timeout must be positive")
        if show_qr is None:
            try:
                from qrcode import QRCode
            except ImportError:
                raise IMOLoginError('Terminal QR display requires imo-python[qr] or a show_qr callback') from None

            def show_qr(challenge):
                qr = QRCode(border=4)
                qr.add_data(challenge.payload)
                qr.print_ascii(out=sys.stderr, invert=True)
                print(f"Scan and confirm in the IMO mobile app within {challenge.ttl}s.", file=sys.stderr)

        if not callable(show_qr):
            raise TypeError("show_qr must be callable")
        try:
            challenge = self.begin_qr_login()
            show_qr(challenge)
            self.wait_for_login(timeout=timeout)
        finally:
            if not self.is_authenticated:
                self.close()

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
                event = transport.wait_event(_LOGIN_CHALLENGE_EVENTS | _SESSION_ENDED,
                                             min(deadline, limit) if limit is not None else deadline)
                name = event["name"]
                if (event["type"], name) in _SESSION_ENDED:
                    raise IMOLoginError("IMO Web ended the login session")
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
            event = transport.wait_event(_LOGIN_RESULT_EVENTS | _SESSION_ENDED,
                                         min(deadline, limit) if limit is not None else deadline)
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
        seen = {cursor}
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

    def iter_history(self, buid: str | Head | Chat, *, page_size: int = 50, before: str | None = None,
                     max_messages: int | None = None) -> Iterator[WebMessage]:
        """Yield history newest first and suppress repeated rows at page boundaries."""
        if isinstance(buid, (Head, Chat)):
            buid = buid.buid
        self._validate_buid(buid)
        if type(page_size) is not int or not 1 <= page_size <= 100:
            raise ValueError("page_size must be between 1 and 100")
        if max_messages is not None and (type(max_messages) is not int or max_messages < 0):
            raise ValueError("max_messages must be a nonnegative integer or None")
        if before is not None and _timestamp(before) is None:
            raise ValueError("before must be a nanosecond timestamp string")
        cursor = int(before) if before is not None else None
        boundary = []
        limit = page_size
        remaining = max_messages
        while remaining is None or remaining > 0:
            rows = self.get_history(buid, limit=limit, before=before)
            if not rows:
                return
            page = []
            for row in rows:
                message = WebMessage.from_record(row, buid=buid)
                if message.timestamp_nano is None:
                    raise IMORequestError("IMO Web history row is missing a valid pagination timestamp")
                timestamp = int(message.timestamp_nano)
                if cursor is not None and timestamp > cursor:
                    raise IMORequestError("IMO Web returned a history row beyond the page cursor")
                page.append((timestamp, message))
            page.sort(key=lambda item: item[0], reverse=True)
            for timestamp, message in page:
                if timestamp == cursor:
                    if message.raw in boundary:
                        continue
                    boundary.append(message.raw)
                yield message
                if remaining is not None:
                    remaining -= 1
                    if remaining == 0:
                        return
            if len(rows) < limit:
                return
            oldest = page[-1][0]
            if oldest == cursor:
                if limit == 100:
                    raise IMORequestError("IMO Web history pagination could not advance")
                limit = min(100, limit * 2)
            else:
                cursor, before = oldest, str(oldest)
                boundary = [message.raw for timestamp, message in page if timestamp == oldest]
                limit = max(2, page_size)

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

    def list_chats(self) -> list[Chat]:
        """Return typed chat summaries, including the last message when present."""
        return [Chat.from_record(change) for change in self.get_chats()]

    def get_group_members(self, buid: str | Chat) -> list[GroupMember]:
        """List the current visible roster for a group conversation."""
        if isinstance(buid, Chat):
            if not buid.is_group:
                raise ValueError("chat is not a group")
            buid = buid.buid
        self._validate_buid(buid)
        gid = buid.replace(";", "")
        self._validate_buid(gid)
        reply = self._account_request("pin", "get_group_members", {"gid": gid})
        if reply is None:
            return []
        if not isinstance(reply, list) or not all(isinstance(row, dict) for row in reply):
            raise IMORequestError("IMO Web returned an invalid group roster")
        members = {}
        for row in reply:
            if not row.get("isDeleteAccount"):
                member = GroupMember.from_record(row)
                if member.uid:
                    members[member.uid] = member
        return list(members.values())

    def receive_message(self, *, timeout=None) -> dict:
        """Wait for one incoming recv_im push and return its message payload."""
        transport = self._require_session()
        timeout = self._timeout if timeout is None else timeout
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be positive")
        deadline = time.monotonic() + timeout
        while True:
            try:
                event = transport.wait_event(_SESSION_ENDED | _MESSAGE_EVENTS, deadline)
            except IMOTransportError:
                self.close()
                raise
            if (event["type"], event["name"]) in _SESSION_ENDED:
                self.close()
                raise IMOLoginError("IMO Web ended this session")
            data = event.get("edata")
            if isinstance(data, dict):
                return data

    def on_message(self, handler: Callable[[WebMessage], None]) -> Callable[[WebMessage], None]:
        """Register a synchronous handler, including as a decorator."""
        if not callable(handler) or iscoroutinefunction(handler):
            raise TypeError("handler must be a synchronous callable")
        if handler not in self._message_handlers:
            self._message_handlers.append(handler)
        return handler

    def remove_message_handler(self, handler: Callable[[WebMessage], None]) -> None:
        """Remove a handler registered with on_message."""
        if handler in self._message_handlers:
            self._message_handlers.remove(handler)

    def run(self, *, poll_timeout: float | None = None) -> None:
        """Dispatch incoming messages until stopped, closed, or interrupted by an error."""
        self._require_session()
        if self._running:
            raise RuntimeError("IMO message loop is already running")
        if not self._message_handlers:
            raise ValueError("Register an on_message handler before running the message loop")
        if poll_timeout is not None and (not math.isfinite(poll_timeout) or poll_timeout <= 0):
            raise ValueError("poll_timeout must be positive")
        self._running = True
        self._stop_requested = False
        try:
            while not self._stop_requested and self._message_handlers:
                try:
                    record = self.receive_message(timeout=poll_timeout)
                except IMOTimeoutError:
                    continue
                message = WebMessage.from_record(record)
                for handler in tuple(self._message_handlers):
                    handler(message)
        finally:
            self._running = False

    def stop(self) -> None:
        """Stop run after the current message, keeping the session open."""
        self._stop_requested = True

    def download_attachment(self, attachment: Attachment, directory, *, max_bytes=256 * 1024 * 1024) -> Path:
        """Save one attachment and return its path, preserving any existing file."""
        transport = self._require_session()
        return save_attachment(attachment, directory, request=self._account_request, ssid=transport.ssid,
                               uid=self._sign_on["uid"], country=self._sign_on.get("phone_cc", "").upper(),
                               timeout=self._timeout, max_bytes=max_bytes)

    def download_attachments(self, message: WebMessage | Mapping, directory,
                             *, max_bytes=256 * 1024 * 1024) -> list[Path]:
        """Save originals from one history row or incoming message, in message order."""
        attachments = message.attachments if isinstance(message, WebMessage) else extract_attachments(message)
        return [self.download_attachment(attachment, directory, max_bytes=max_bytes)
                for attachment in attachments]

    def logout(self):
        """Log out the current web session with the server."""
        transport = self._require_session()
        reply = self._account_request("imo_account_manager", "logout", {"ssid": transport.ssid})
        if not isinstance(reply, dict) or reply.get("status") != "success":
            raise IMORequestError("IMO Web did not confirm logout")
        self.close()

    def send_message(self, buid: str | Head | Chat | None = None, text: str | None = None, *,
                     id: str | int | None = None, name: str | None = None,
                     media: str | Path | None = None) -> SentMessage | tuple[SentMessage, SentMessage]:
        """Send to a BUID or exact contact name. When both contents are given, return (file, text)."""
        if sum(value is not None for value in (buid, id, name)) != 1:
            raise ValueError("provide exactly one recipient: buid, id or name")
        if text is not None and (not isinstance(text, str) or not text.strip()):
            raise ValueError("text must be nonempty")
        if text is None and media is None:
            raise ValueError("provide text, media or both")
        if media is not None and not isinstance(media, (str, Path)):
            raise TypeError("media must be a local file path")
        if name is not None:
            buid = self.find_contact(name, exact=True).buid
        elif id is not None:
            if type(id) is int and id <= 0:
                raise ValueError("id must be a positive integer or a conversation ID")
            buid = str(id) if type(id) is int else id
        if isinstance(buid, (Head, Chat)):
            buid = buid.buid
        self._validate_buid(buid)
        if media is None:
            return self._send_text(buid, text)

        transport = self._require_session()
        msg_id = random_id(8)
        timestamp = send_file(self._account_request, transport, self._sign_on["uid"],
                              self._sign_on.get("phone_cc", "").upper(), buid, Path(media),
                              msg_id, random_id(16), self._timeout)
        attachment = SentMessage(buid, msg_id, timestamp)
        if text is None:
            return attachment
        try:
            return attachment, self._send_text(buid, text)
        except IMOError as error:
            raise IMOPartialSendError(attachment, error) from error

    def _send_text(self, buid: str, text: str) -> SentMessage:
        msg_id = random_id(8)
        reply = self._account_request("pin", "send_im", {
            "buid": buid, "msg": text,
            "imdata": {"type": "im", "msg_id": msg_id, "trace_id": random_id(16)},
        })
        timestamp = reply.get("timestamp_nano_str") if isinstance(reply, dict) else None
        if not isinstance(timestamp, str) or not timestamp.isdecimal():
            raise IMORequestError("IMO Web did not confirm the message; check the conversation before resending")
        return SentMessage(buid, msg_id, timestamp)

    def find_contact(self, name: str, *, contacts: Iterable[Head] | None = None, exact: bool = False) -> Head:
        """Return the contact called name, ignoring case and repeated spaces.

        An exact match on the note, alias or display name wins. Otherwise the name must be
        part of exactly one contact's names, unless exact=True. Pass contacts to reuse a list.
        """
        wanted = _fold(name)
        if not wanted:
            raise ValueError("name must be nonempty")
        pool = list(self.get_contacts() if contacts is None else contacts)
        names = [(head, [folded for folded in map(_fold, (head.note, head.alias, head.display)) if folded])
                 for head in pool]
        matches = [head for head, known in names if wanted in known]
        if not matches and not exact:
            matches = [head for head, known in names if any(wanted in folded for folded in known)]
        if not matches:
            raise IMOContactNotFound(f"No contact is named {name!r}")
        count = len({head.buid for head in matches})
        if count > 1:
            raise IMOContactNotFound(f"{count} contacts match {name!r}; use the full name or a BUID")
        return matches[0]

    def send_many(self, messages: Iterable[tuple[str | Head | Chat, str]], *, delay: float = 8.0,
                  jitter: float = 0.3, by_name: bool = False, stop_on_error: bool = False) -> list[SendResult]:
        """Send (target, text) rows in order, pausing delay seconds (within ±jitter) between them.

        With by_name, string targets are contact names resolved by find_contact; otherwise
        they are conversation IDs. Every row is validated before anything is sent. A row the
        server does not confirm, or whose name is not found, is reported in its SendResult and
        the batch continues unless stop_on_error is set. A timeout or lost connection ends the
        session, so the batch stops there and later rows are not returned.
        """
        if not math.isfinite(delay) or delay < 0:
            raise ValueError("delay must be nonnegative")
        if not math.isfinite(jitter) or not 0 <= jitter < 1:
            raise ValueError("jitter must be at least 0 and less than 1")
        rows = []
        for row in messages:
            try:
                target, text = row
            except (TypeError, ValueError):
                raise ValueError("each message must be a (target, text) pair") from None
            if isinstance(target, (Head, Chat)):
                target = target.buid
            elif by_name and isinstance(target, str) and target.strip():
                target = (target,)                       # a name, resolved once the contacts are loaded
            else:
                self._validate_buid(target)
            if not isinstance(text, str) or not text.strip():
                raise ValueError("text must be nonempty")
            rows.append((target, text))
        self._require_session()
        contacts = self.get_contacts() if any(isinstance(target, tuple) for target, _ in rows) else None

        results = []
        for index, (target, text) in enumerate(rows):
            label = target[0] if isinstance(target, tuple) else target
            lost = None
            try:
                if isinstance(target, tuple):
                    target = self.find_contact(label, contacts=contacts).buid
                results.append(SendResult(label, text, sent=self.send_message(target, text)))
            except (IMOTimeoutError, IMOTransportError, IMOLoginError) as error:
                lost = error
            except IMOError as error:
                results.append(SendResult(label, text, error=error))
                if stop_on_error:
                    break
            if lost is not None:
                results.append(SendResult(label, text, error=lost))
                break
            if index + 1 < len(rows):
                self._pause(delay * random.uniform(1 - jitter, 1 + jitter))
        return results

    def _pause(self, seconds):
        """Wait while still acknowledging pushes and sending keep-alives."""
        if seconds <= 0:
            return
        try:
            self._require_session().wait_event(frozenset(), time.monotonic() + seconds)
        except IMOTimeoutError:
            pass
        except IMOTransportError:
            self.close()
            raise

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
