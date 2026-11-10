"""Async account facade with explicit adapter injection."""

from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import AsyncIterator, Callable
from contextlib import aclosing
from dataclasses import replace
from inspect import iscoroutinefunction
from pathlib import Path
from types import TracebackType
from typing import Self

from ._dispatcher import EventDispatcher, MessageHandler, Registration
from .connection import Connection, ConnectionState, run_sync, transport_errors
from .errors import FeatureUnavailableError, IMOConnectionError, IMOError, MessageSendError, TransportError
from .filters import Filter
from .transport import (
    AccountReader,
    Capability,
    ChatReader,
    ContactReader,
    EventSource,
    HistoryReader,
    MediaDownloader,
    ReplySender,
    TextSender,
    Transport,
)
from .types import Chat, Media, Message, User

logger = logging.getLogger(__name__)

def _missing_contract(capability: Capability) -> TransportError:
    return TransportError(f"The IMO transport declares {capability} but does not implement its contract")


class IMOClient:
    """One named account. Pass a transport to enable real or fixture operations."""

    def __init__(
        self,
        account_id: str = "main",
        *,
        transport: Transport | None = None,
        event_workers: int = 4,
        queue_size: int = 64,
        dedup_size: int = 2048,
        shutdown_timeout: float = 10,
        reconnect_attempts: int = 2,
        reconnect_delay: float = 1,
    ) -> None:
        if not account_id.strip():
            raise ValueError("account_id must be nonempty")
        if event_workers < 1 or queue_size < 1 or dedup_size < 0:
            raise ValueError("event_workers and queue_size must be positive and dedup_size nonnegative")
        if not math.isfinite(shutdown_timeout) or shutdown_timeout <= 0:
            raise ValueError("shutdown_timeout must be finite and positive")
        if reconnect_attempts < 0 or not math.isfinite(reconnect_delay) or reconnect_delay < 0:
            raise ValueError("reconnect settings must be finite and nonnegative")
        self._account_id = account_id
        self._connection = Connection(transport)
        self._handlers: list[Registration] = []
        self._listening = False
        self._stop_requested = False
        self._event_workers = event_workers
        self._queue_size = queue_size
        self._dedup_size = dedup_size
        self._shutdown_timeout = shutdown_timeout
        self._reconnect_attempts = reconnect_attempts
        self._reconnect_delay = reconnect_delay

    @property
    def account_id(self) -> str:
        return self._account_id

    @property
    def state(self) -> ConnectionState:
        return self._connection.state

    @property
    def capabilities(self) -> frozenset[Capability]:
        transport = self._connection.transport
        return frozenset(transport.capabilities) if transport is not None else frozenset()

    async def connect(self) -> None:
        await self._connection.connect()

    async def disconnect(self) -> None:
        self._stop_requested = True
        await self._connection.disconnect()

    async def __aenter__(self) -> Self:
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        try:
            await self.disconnect()
        except IMOError:
            if exc is None:
                raise
            logger.warning("IMO adapter failed to disconnect while handling another error")

    def _operation(self, capability: Capability) -> Transport:
        transport = self._connection.transport
        if transport is None:
            raise FeatureUnavailableError(f"{capability} requires a configured IMO transport")
        if capability not in transport.capabilities:
            raise FeatureUnavailableError(f"The IMO transport does not support {capability}")
        if self.state is not ConnectionState.CONNECTED:
            raise IMOConnectionError("Connect the account before using the IMO transport")
        return transport

    async def get_me(self) -> User:
        transport = self._operation(Capability.ACCOUNT)
        if not isinstance(transport, AccountReader):
            raise _missing_contract(Capability.ACCOUNT)
        with transport_errors("read the account profile"):
            return await transport.get_me()

    async def get_contacts(self) -> AsyncIterator[User]:
        transport = self._operation(Capability.CONTACTS)
        if not isinstance(transport, ContactReader):
            raise _missing_contract(Capability.CONTACTS)
        with transport_errors("list contacts"):
            async for contact in transport.get_contacts():
                yield contact

    async def get_chats(self) -> AsyncIterator[Chat]:
        transport = self._operation(Capability.CHATS)
        if not isinstance(transport, ChatReader):
            raise _missing_contract(Capability.CHATS)
        with transport_errors("list chats"):
            async for chat in transport.get_chats():
                yield chat

    async def get_history(self, chat_id: str, *, limit: int | None = None) -> AsyncIterator[Message]:
        if not chat_id.strip() or (limit is not None and limit <= 0):
            raise ValueError("chat_id must be nonempty and limit must be positive when supplied")
        transport = self._operation(Capability.HISTORY)
        if not isinstance(transport, HistoryReader):
            raise _missing_contract(Capability.HISTORY)
        with transport_errors("read the chat history"):
            async for message in transport.get_history(chat_id, limit=limit):
                yield self._bind(message)

    async def send_message(self, chat_id: str, text: str) -> Message:
        if not chat_id.strip() or not text.strip():
            raise ValueError("chat_id and text must be nonempty")
        transport = self._operation(Capability.SEND_TEXT)
        if not isinstance(transport, TextSender):
            raise _missing_contract(Capability.SEND_TEXT)
        with transport_errors("confirm the send. Check the chat before retrying", MessageSendError):
            return self._bind(await transport.send_message(chat_id, text))

    async def reply_to(self, message: Message, text: str) -> Message:
        self._check_owner(message)
        transport = self._operation(Capability.REPLY)
        if not isinstance(transport, ReplySender):
            raise _missing_contract(Capability.REPLY)
        if not message.id:
            raise FeatureUnavailableError("Replying requires a stable message ID from the adapter")
        if not text.strip():
            raise ValueError("text must be nonempty")
        with transport_errors("confirm the reply. Check the chat before retrying", MessageSendError):
            return self._bind(await transport.reply(message.chat_id, message.id, text))

    def _media_downloader(self) -> MediaDownloader:
        transport = self._operation(Capability.DOWNLOAD)
        if not isinstance(transport, MediaDownloader):
            raise _missing_contract(Capability.DOWNLOAD)
        return transport

    async def download_media(self, media: Media, directory: str | Path = ".") -> Path:
        transport = self._media_downloader()
        with transport_errors("download the attachment"):
            return await transport.download_media(media, Path(directory))

    async def download_message(self, message: Message, directory: str | Path = ".") -> tuple[Path, ...]:
        self._check_owner(message)
        transport = self._media_downloader()
        path = Path(directory)
        with transport_errors("download the attachments"):
            return tuple([await transport.download_media(media, path) for media in message.media])

    def _bind(self, message: Message) -> Message:
        return replace(message, _client=self)

    def _check_owner(self, message: Message) -> None:
        if message._client is not None and message._client is not self:
            raise ValueError("The message belongs to another IMO client")

    def on_message(self, predicate: Filter | None = None) -> Callable[[MessageHandler], MessageHandler]:
        """Register an async handler as a decorator."""
        def register(handler: MessageHandler) -> MessageHandler:
            if not iscoroutinefunction(handler):
                raise TypeError("on_message expects an async function")
            self._handlers.append((predicate, handler))
            return handler
        return register

    def _event_source(self) -> EventSource:
        transport = self._operation(Capability.EVENTS)
        if not isinstance(transport, EventSource):
            raise _missing_contract(Capability.EVENTS)
        return transport

    async def listen(self) -> None:
        """Consume the connected adapter's event stream until EOF or an unrecoverable error."""
        self._event_source()
        if self._listening:
            raise IMOConnectionError("This IMO client already has an event listener")
        self._listening = True
        self._stop_requested = False
        try:
            async with EventDispatcher(
                self, self._handlers, workers=self._event_workers, queue_size=self._queue_size,
                dedup_size=self._dedup_size, shutdown_timeout=self._shutdown_timeout,
            ) as dispatcher:
                await self._consume_events(dispatcher)
        finally:
            self._listening = False

    async def _consume_events(self, dispatcher: EventDispatcher) -> None:
        for attempt in range(self._reconnect_attempts + 1):
            try:
                if attempt:
                    await asyncio.sleep(self._reconnect_delay)
                    if self._stop_requested:
                        return
                    await self._connection.disconnect()
                    if self._stop_requested:
                        return
                    await self.connect()
                    if self._stop_requested:
                        return
                source = self._event_source()
                with transport_errors("receive messages"):
                    async with aclosing(source.messages()) as messages:
                        async for message in messages:
                            if self._stop_requested:
                                return
                            await dispatcher.submit(self._bind(message))
                return
            except TransportError:
                if self._stop_requested:
                    return
                if attempt == self._reconnect_attempts or Capability.RECONNECT not in self.capabilities:
                    raise

    async def run_until_disconnected(self) -> None:
        """Listen, managing the connection when this call opens it."""
        if self.state is ConnectionState.CONNECTED:
            await self.listen()
        else:
            async with self:
                await self.listen()

    def run(self) -> None:
        """Run the listener from synchronous code."""
        run_sync(self.run_until_disconnected)
