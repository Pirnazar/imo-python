"""Public data models independent of any adapter or wire format."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from .errors import FeatureUnavailableError

class _MessageClient(Protocol):
    async def reply_to(self, message: Message, text: str) -> Message: ...

    async def download_message(self, message: Message, directory: str | Path) -> tuple[Path, ...]: ...


class ChatKind(StrEnum):
    PRIVATE = "private"
    GROUP = "group"


class ContentType(StrEnum):
    TEXT = "text"
    PHOTO = "photo"
    VIDEO = "video"
    AUDIO = "audio"
    FILE = "file"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class User:
    id: str | None = None
    name: str | None = None


@dataclass(frozen=True, slots=True)
class Chat:
    id: str
    title: str | None = None
    kind: ChatKind | None = None


@dataclass(frozen=True, slots=True)
class Media:
    id: str | None = None
    filename: str | None = None
    content_type: ContentType = ContentType.UNKNOWN
    size: int | None = None


@dataclass(frozen=True, slots=True)
class Message:
    chat_id: str
    id: str | None = None
    sender_id: str | None = None
    text: str | None = None
    date: datetime | None = None
    content_type: ContentType = ContentType.UNKNOWN
    is_outgoing: bool | None = None
    chat_kind: ChatKind | None = None
    media: tuple[Media, ...] = ()
    _client: _MessageClient | None = field(default=None, repr=False, compare=False, kw_only=True)

    async def reply(self, text: str) -> Message:
        """Reply to this message through its owning client."""
        if self._client is None:
            raise FeatureUnavailableError("This message is not bound to an IMO client")
        return await self._client.reply_to(self, text)

    async def download(self, directory: str | Path = ".") -> tuple[Path, ...]:
        """Download the attachments through the client that supplied this message."""
        if self._client is None:
            raise FeatureUnavailableError("This message is not bound to an IMO client")
        return await self._client.download_message(self, directory)
