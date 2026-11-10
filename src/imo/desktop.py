"""IMOClient — send and receive IMO messages through the installed Windows client's core.

The client starts ``ImoBridge.exe`` (built by ``native/bridge/Build.ps1``), a headless host
for the official IMO .NET assemblies, and talks to it with JSON lines. The bridge signs in
with a QR code scanned from the IMO phone app and keeps its own profile, separate from the
desktop application.

    from imo.desktop import IMOClient

    with IMOClient() as imo:
        imo.login()                      # shows a QR code the first time
        imo.send("Мама", "Привет!")

This is unofficial: IMO has no public API, automating an account is against its terms and
can get the account restricted. Use it for your own account and your own contacts.
"""
from __future__ import annotations

import itertools
import json
import os
import queue
import random
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Optional, Union

__all__ = [
    "IMOClient", "IMOError", "BridgeError", "NotSignedIn", "ContactNotFound",
    "Chat", "Contact", "IncomingMessage", "SendResult", "find_bridge",
]


class IMOError(Exception):
    """Base class for client errors."""


class BridgeError(IMOError):
    """The bridge process is missing, crashed or rejected a command."""


class NotSignedIn(IMOError):
    """The operation needs a signed-in account."""


class ContactNotFound(IMOError):
    """No chat or contact matches the given name."""


# ------------------------------------------------------------------- models ---
@dataclass
class Contact:
    buid: str
    name: str = ""
    is_group: bool = False
    raw: dict = field(default_factory=dict, repr=False)


@dataclass
class Chat:
    buid: str
    name: str = ""
    is_group: bool = False
    last_message: str = ""
    last_activity: int = 0
    raw: dict = field(default_factory=dict, repr=False)


@dataclass
class IncomingMessage:
    chat: str                 # buid of the conversation
    sender: str               # buid of the author (same as chat for 1:1)
    sender_name: str
    text: str
    kind: str                 # MessageContentType name: Text, Photo, ...
    timestamp: int            # nanoseconds since the epoch
    outgoing: bool
    raw: dict = field(default_factory=dict, repr=False)


@dataclass
class SendResult:
    to: str
    text: str
    ok: bool
    error: str = ""


def _first(d: dict, *keys: str, default: Any = "") -> Any:
    for k in keys:
        v = d.get(k)
        if v not in (None, ""):
            return v
    return default


_NAME_KEYS = ("AliasByRemark", "Remark", "Display", "Alias", "DisplayName", "Name")


def _is_group(buid: str, raw: dict) -> bool:
    if "IsGroup" in raw:
        return bool(raw["IsGroup"])
    return "Group" in str(raw.get("ChatType", "")) or buid.endswith(";")


def _chat_from(raw: dict) -> Chat:
    """Chat from a serialized ``ChaterModel`` (``ChatTarget`` is the contact or group head)."""
    head = raw.get("ChatTarget") if isinstance(raw.get("ChatTarget"), dict) else {}
    buid = str(_first(raw, "KeyID", default=_first(head, "KeyID")))
    return Chat(
        buid=buid,
        name=str(_first(head, *_NAME_KEYS)),
        is_group=_is_group(buid, head or raw),
        last_message=str(_first(raw, "LastMessageContent")),
        last_activity=int(_first(raw, "LastActivityTimestamp", "LastMessageTime", default=0) or 0),
        raw=raw,
    )


def _contact_from(raw: dict) -> Contact:
    """Contact from a serialized ``HeadModel`` / ``UserModel`` / ``GroupModel``."""
    buid = str(_first(raw, "KeyID", "Buid", "Uid", "Gid"))
    return Contact(buid=buid, name=str(_first(raw, *_NAME_KEYS)), is_group=_is_group(buid, raw), raw=raw)


def _message_from(raw: dict) -> IncomingMessage:
    """Message from a serialized ``MessageModel``."""
    sender = raw.get("Sender") if isinstance(raw.get("Sender"), dict) else {}
    chat = str(_first(raw, "ConvBuid", "Buid", "KeyID"))
    return IncomingMessage(
        chat=chat,
        sender=str(_first(raw, "Sender_buid", default=_first(sender, "KeyID", default=chat))),
        sender_name=str(_first(sender, *_NAME_KEYS, default=_first(raw, "AuthorAlias", "Alias"))),
        text=str(_first(raw, "Msg", "Content")),
        kind=str(_first(raw, "MessageContentType", default="Text")),
        timestamp=int(_first(raw, "TimestampNano", "SentTimestamp", default=0) or 0),
        outgoing=bool(raw.get("IsMyMessage")) or str(raw.get("Origin", "")).upper().startswith("SEN"),
        raw=raw,
    )


def _norm(s: str) -> str:
    return " ".join(s.split()).casefold()


# ------------------------------------------------------------------- bridge ---
def find_bridge() -> Path:
    """Locate ImoBridge.exe.

    Order: ``$IMO_BRIDGE``, then ``.runtime`` in the project checkout, then
    ``%LOCALAPPDATA%/imo-python/runtime`` (the default of ``Build.ps1``).
    """
    env = os.environ.get("IMO_BRIDGE")
    if env:
        return Path(env)
    roots = [Path(__file__).resolve().parents[2] / ".runtime",
             Path(os.environ.get("LOCALAPPDATA", "")) / "imo-python" / "runtime"]
    for root in roots:
        found = sorted(root.glob("*/ImoBridge.exe"), key=lambda p: p.stat().st_mtime)
        if found:
            return found[-1]
    raise BridgeError(
        "ImoBridge.exe not found. Build it first: powershell -File native/bridge/Build.ps1")


class _Bridge:
    """JSON-lines transport to the bridge process."""

    def __init__(self, path: Path, debug: bool, on_event: Callable[[dict], None]):
        self._on_event = on_event
        self._ids = itertools.count(1)
        self._pending: dict[int, queue.Queue] = {}
        self._lock = threading.Lock()
        self.closed = threading.Event()
        # A .py bridge is a stand-in used by the tests.
        args = ([sys.executable, str(path)] if path.suffix == ".py" else [str(path)]) + (["--log"] if debug else [])
        try:
            self._proc = subprocess.Popen(
                args, cwd=str(path.parent), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=None if debug else subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as e:
            raise BridgeError(f"cannot start {path}: {e}") from e
        threading.Thread(target=self._read, name="imo-bridge-reader", daemon=True).start()

    def _read(self) -> None:
        assert self._proc.stdout is not None
        for line in self._proc.stdout:
            try:
                msg = json.loads(line.decode("utf-8", errors="replace"))
            except ValueError:
                continue
            if "event" in msg:
                try:
                    self._on_event(msg)
                except Exception as e:  # a handler must not kill the reader
                    print(f"imo: event handler failed: {e!r}", file=sys.stderr)
                continue
            waiter = self._pending.pop(msg.get("id"), None)
            if waiter is not None:
                waiter.put(msg)
        self.closed.set()
        for waiter in list(self._pending.values()):
            waiter.put({"ok": False, "error": "bridge exited"})

    def new_id(self) -> int:
        return next(self._ids)

    def call(self, cmd: str, timeout: float = 30.0, ident: Optional[int] = None, **params: Any) -> Any:
        if self.closed.is_set():
            raise BridgeError("bridge is not running")
        if ident is None:
            ident = self.new_id()
        waiter: queue.Queue = queue.Queue(1)
        self._pending[ident] = waiter
        data = (json.dumps({"id": ident, "cmd": cmd, **params}, ensure_ascii=False) + "\n").encode("utf-8")
        try:
            with self._lock:
                assert self._proc.stdin is not None
                self._proc.stdin.write(data)
                self._proc.stdin.flush()
            reply = waiter.get(timeout=timeout)
        except queue.Empty:
            raise BridgeError(f"no reply to {cmd!r} within {timeout:.0f}s") from None
        except OSError as e:
            raise BridgeError(f"bridge pipe closed: {e}") from e
        finally:
            self._pending.pop(ident, None)
        if not reply.get("ok"):
            raise BridgeError(str(reply.get("error", "unknown bridge error")))
        return reply.get("result")

    def close(self) -> None:
        if self._proc.poll() is None:
            try:
                self.call("exit", timeout=5)
            except BridgeError:
                pass
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()


# ------------------------------------------------------------------- client ---
def _show_qr(link: str, ttl: int) -> None:
    """Default QR presenter: ASCII art in the terminal (needs the `qrcode` package)."""
    print(f"\nОткройте imo на телефоне → сканер QR и отсканируйте код (действует {ttl} с):")
    try:
        import qrcode  # type: ignore
    except ImportError:
        print("  (pip install qrcode, чтобы увидеть код здесь)\n  " + link)
        return
    qr = qrcode.QRCode(border=2)
    qr.add_data(link)
    qr.print_ascii(invert=True)


class IMOClient:
    """High-level client. Thread-safe; callbacks run on the bridge reader thread."""

    def __init__(self, bridge: Union[str, Path, None] = None, *, debug: bool = False):
        self._bridge_path = Path(bridge) if bridge else None
        self._debug = debug
        self._bridge: Optional[_Bridge] = None
        self._events: "queue.Queue[dict]" = queue.Queue()
        self._waiters: list[tuple[Callable[[dict], bool], queue.Queue]] = []
        self._waiters_lock = threading.Lock()
        self._message_handlers: list[Callable[[IncomingMessage], None]] = []
        self._event_handlers: list[Callable[[dict], None]] = []
        self._connected = threading.Event()
        self._signed_on = threading.Event()
        self._names: dict[str, str] = {}          # normalized name -> buid
        self._buddies_synced = False
        self.me: dict = {}

    # ------------------------------------------------------------ lifecycle
    def __enter__(self) -> "IMOClient":
        self.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def start(self, timeout: float = 30.0) -> None:
        """Start the bridge and open the signalling connection."""
        if self._bridge is not None:
            return
        self._bridge = _Bridge(self._bridge_path or find_bridge(), self._debug, self._handle_event)
        ready = self._wait(lambda e: e["event"] in ("ready", "fatal"), timeout)
        if ready["event"] == "fatal":
            raise BridgeError(ready.get("error", "bridge failed to start"))
        self._call("connect")
        if not self._connected.wait(timeout):
            raise BridgeError(f"no connection to imo servers within {timeout:.0f}s")

    def close(self) -> None:
        if self._bridge is not None:
            self._bridge.close()
            self._bridge = None

    # --------------------------------------------------------------- events
    def _handle_event(self, e: dict) -> None:
        kind = e.get("type") if e.get("event") == "action" else None
        if kind == "SignalConnected":
            self._connected.set()
        elif kind == "SignalDisconnected":
            self._connected.clear()
        elif kind == "SignedOn":
            self._signed_on.set()
        elif kind == "SignOff":
            self._signed_on.clear()
        with self._waiters_lock:
            for item in list(self._waiters):
                try:
                    matched = item[0](e)
                except Exception:
                    matched = False
                if matched:
                    self._waiters.remove(item)
                    item[1].put(e)
        for handler in list(self._event_handlers):
            handler(e)
        if kind in ("MessageReceive", "UnreadMessageReceive") and self._message_handlers:
            for raw in self._models(e):
                msg = _message_from(raw)
                for handler in list(self._message_handlers):
                    handler(msg)

    @staticmethod
    def _models(e: dict) -> list[dict]:
        out: list[dict] = []
        for key in ("data", "model", "models", "data1"):
            v = e.get(key)
            if isinstance(v, dict):
                out.append(v)
            elif isinstance(v, list):
                out.extend(x for x in v if isinstance(x, dict))
        return out

    def _wait(self, predicate: Callable[[dict], bool], timeout: float) -> dict:
        waiter: queue.Queue = queue.Queue(1)
        item = (predicate, waiter)
        with self._waiters_lock:
            self._waiters.append(item)
        try:
            return waiter.get(timeout=timeout)
        except queue.Empty:
            raise TimeoutError(f"no matching event within {timeout:.0f}s") from None
        finally:
            with self._waiters_lock:
                if item in self._waiters:
                    self._waiters.remove(item)

    def _call(self, cmd: str, timeout: float = 30.0, **params: Any) -> Any:
        if self._bridge is None:
            raise BridgeError("client is not started; call start() or use `with IMOClient()`")
        return self._bridge.call(cmd, timeout=timeout, **params)

    def _run_and_wait(self, action: str, params: Optional[dict], timeout: float,
                      accept: Optional[Callable[[dict], bool]] = None) -> dict:
        """RunTask(action) and wait for the matching ReceivedData event."""
        def match(e: dict) -> bool:
            return e.get("event") == "action" and e.get("type") == action and (accept is None or accept(e))
        waiter: queue.Queue = queue.Queue(1)
        item = (match, waiter)
        with self._waiters_lock:
            self._waiters.append(item)
        try:
            self._call("run", action=action, params=params or {})
            return waiter.get(timeout=timeout)
        except queue.Empty:
            raise TimeoutError(f"{action}: no result within {timeout:.0f}s") from None
        finally:
            with self._waiters_lock:
                if item in self._waiters:
                    self._waiters.remove(item)

    def on_event(self, handler: Callable[[dict], None]) -> Callable[[dict], None]:
        """Register a handler for every raw bridge event (useful for debugging)."""
        self._event_handlers.append(handler)
        return handler

    def on_message(self, handler: Callable[[IncomingMessage], None]) -> Callable[[IncomingMessage], None]:
        """Register a handler for incoming messages. Usable as a decorator."""
        self._message_handlers.append(handler)
        return handler

    def run_forever(self) -> None:
        """Block and deliver messages to ``on_message`` handlers until Ctrl+C or bridge exit."""
        if self._bridge is None:
            raise BridgeError("client is not started")
        try:
            while not self._bridge.closed.wait(0.5):
                pass
        except KeyboardInterrupt:
            pass

    # ---------------------------------------------------------------- login
    @property
    def connected(self) -> bool:
        return self._connected.is_set()

    @property
    def signed_in(self) -> bool:
        return self._signed_on.is_set()

    def status(self) -> dict:
        return self._call("status")

    def login(self, on_qr: Optional[Callable[[str, int], None]] = None, timeout: float = 300.0) -> dict:
        """Sign in. Restores the saved session, otherwise shows QR codes until one is scanned.

        ``on_qr(link, ttl_seconds)`` is called for every fresh code; by default the code is
        printed to the terminal. Returns the account status.
        """
        self.start()
        deadline = time.monotonic() + timeout
        st = self.status()
        if st.get("cookie_signed_on") and not st.get("signed_on"):
            self._signed_on.wait(min(25.0, timeout))      # the bridge restores the session itself
            st = self.status()
        if st.get("signed_on"):
            self._signed_on.set()
        show = on_qr or _show_qr
        while not self._signed_on.is_set():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("QR code was not confirmed in time")
            reply = self._call("request_qr", timeout=30)
            result = (reply or {}).get("result") or {}
            link, ttl = result.get("qr_link"), int(result.get("code_ttl") or 60)
            if (reply or {}).get("status") != "success" or not link:
                raise IMOError(f"imo refused to issue a QR code: {reply!r}")
            show(link, ttl)
            expires = time.monotonic() + ttl
            scanned = False
            while not self._signed_on.is_set():
                wait = (deadline if scanned else min(expires, deadline)) - time.monotonic()
                if wait <= 0:
                    break                                  # code expired: ask for a new one
                try:
                    e = self._wait(lambda e: e.get("type") in (
                        "QrCodeScanned", "QrCodeLoginCancelled", "SignedOn"), wait)
                except TimeoutError:
                    break
                if e.get("type") == "QrCodeScanned":
                    scanned = True
                elif e.get("type") == "QrCodeLoginCancelled":
                    break
        self.me = self.status()
        return self.me

    def _require_login(self) -> None:
        if not self._signed_on.is_set():
            if self._bridge is not None and self.status().get("signed_on"):
                self._signed_on.set()
                return
            raise NotSignedIn("call login() first")

    # ---------------------------------------------------------------- chats
    def chats(self, refresh: bool = True, timeout: float = 30.0) -> list[Chat]:
        """Chat list, most recent first (the client core keeps the 100 latest visible chats).

        The server only returns chats changed since the last sync, so ``refresh=True`` first
        pulls that delta and then reads the full list from the client's local store.
        """
        self._require_login()
        merged: dict[str, Chat] = {}
        if refresh:
            try:
                delta = self._run_and_wait("GetChaters", {"BoolValue0": True}, min(timeout, 10.0))
                merged.update((c.buid, c) for c in map(_chat_from, self._models(delta)))
            except TimeoutError:
                pass                                   # nothing changed since the last sync
        local = self._run_and_wait("GetChaters", None, timeout)
        merged.update((c.buid, c) for c in map(_chat_from, self._models(local)))
        merged.pop("", None)
        for c in merged.values():
            if c.name:
                self._names[_norm(c.name)] = c.buid
        return sorted(merged.values(), key=lambda c: c.last_activity, reverse=True)

    def contacts(self, refresh: bool = False, timeout: float = 30.0) -> list[Contact]:
        """All buddies and groups known to the account.

        The first call (and ``refresh=True``) syncs the buddy list from the server; later
        calls read the client core's in-memory copy.
        """
        self._require_login()
        if refresh or not self._buddies_synced:
            self._run_and_wait("SyncBuddyList", {"BoolValue0": True}, timeout)
            self._buddies_synced = True
        found: dict[str, Contact] = {}
        for action in ("GetAllBuddies", "GetAllGroups"):
            returned = self._call("run", action=action, timeout=timeout)
            for raw in returned if isinstance(returned, list) else []:
                if isinstance(raw, dict):
                    c = _contact_from(raw)
                    if c.buid:
                        found.setdefault(c.buid, c)
        for c in found.values():
            if c.name:
                self._names[_norm(c.name)] = c.buid
        return sorted(found.values(), key=lambda c: _norm(c.name))

    def resolve(self, to: str) -> str:
        """Turn a contact/group name into a buid. A value that is already a buid passes through."""
        key = _norm(to)
        if key in self._names:
            return self._names[key]
        known = set(self._names.values())
        if to in known:
            return to
        for loader in (self.contacts, self.chats):
            try:
                loader()
            except TimeoutError:
                continue
            if key in self._names:
                return self._names[key]
            if to in set(self._names.values()):
                return to
        partial = {b for n, b in self._names.items() if key in n}
        if len(partial) == 1:
            return partial.pop()
        if len(partial) > 1:
            raise ContactNotFound(f"{to!r} matches several contacts; use the exact name or buid")
        raise ContactNotFound(f"no contact or chat named {to!r}")

    # ----------------------------------------------------------------- send
    def send(self, to: str, text: str, *, buid: bool = False, ack_timeout: float = 20.0) -> bool:
        """Send a text message to a contact or group, by name (or by buid with ``buid=True``).

        Returns True when the server acknowledged the message, False if no acknowledgement
        arrived within ``ack_timeout`` (the client core keeps retrying on its own).
        """
        self._require_login()
        if not text:
            raise ValueError("text is empty")
        target = to if buid else self.resolve(to)
        assert self._bridge is not None
        ident = self._bridge.new_id()
        waiter: queue.Queue = queue.Queue(1)
        item = (lambda e: e.get("event") == "send_ack" and e.get("send_id") == ident, waiter)
        # Register before sending, so a fast acknowledgement is not missed.
        with self._waiters_lock:
            self._waiters.append(item)
        try:
            self._bridge.call("send", ident=ident, buid=target, text=text)
            waiter.get(timeout=ack_timeout)
            return True
        except queue.Empty:
            return False
        finally:
            with self._waiters_lock:
                if item in self._waiters:
                    self._waiters.remove(item)

    def send_many(self, messages: Iterable[tuple[str, str]], *, delay: float = 8.0,
                  stop_on_error: bool = False) -> list[SendResult]:
        """Send ``(to, text)`` pairs one by one with a randomized pause (±30%) between them."""
        rows = list(messages)
        results: list[SendResult] = []
        for i, (to, text) in enumerate(rows):
            try:
                ok = self.send(to, text)
                results.append(SendResult(to, text, ok, "" if ok else "no acknowledgement"))
            except IMOError as e:
                results.append(SendResult(to, text, False, str(e)))
                if stop_on_error:
                    break
            if i + 1 < len(rows):
                time.sleep(delay * random.uniform(0.7, 1.3))
        return results
