"""Optional adapter contracts. Implement only the capabilities you declare."""

from collections.abc import AsyncGenerator, AsyncIterator, Set
from enum import StrEnum
from pathlib import Path
from typing import Protocol, runtime_checkable

from .types import Chat, Media, Message, User


class Capability(StrEnum):
    ACCOUNT = "account"
    CONTACTS = "contacts"
    CHATS = "chats"
    HISTORY = "history"
    SEND_TEXT = "send_text"
    REPLY = "reply"
    EVENTS = "events"
    DOWNLOAD = "download"
    RECONNECT = "reconnect"


class Transport(Protocol):
    @property
    def capabilities(self) -> Set[Capability]: ...

    async def connect(self) -> None: ...

    async def disconnect(self) -> None: ...


@runtime_checkable
class AccountReader(Protocol):
    async def get_me(self) -> User: ...


@runtime_checkable
class ContactReader(Protocol):
    def get_contacts(self) -> AsyncIterator[User]: ...


@runtime_checkable
class ChatReader(Protocol):
    def get_chats(self) -> AsyncIterator[Chat]: ...


@runtime_checkable
class HistoryReader(Protocol):
    def get_history(self, chat_id: str, *, limit: int | None) -> AsyncIterator[Message]: ...


@runtime_checkable
class TextSender(Protocol):
    async def send_message(self, chat_id: str, text: str) -> Message: ...


@runtime_checkable
class ReplySender(Protocol):
    async def reply(self, chat_id: str, message_id: str, text: str) -> Message: ...


@runtime_checkable
class EventSource(Protocol):
    def messages(self) -> AsyncGenerator[Message, None]: ...


@runtime_checkable
class MediaDownloader(Protocol):
    async def download_media(self, media: Media, directory: Path) -> Path: ...
