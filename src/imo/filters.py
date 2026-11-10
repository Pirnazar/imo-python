"""Composable predicates for message handlers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .types import ChatKind, ContentType, Message


@dataclass(frozen=True, slots=True)
class Filter:
    predicate: Callable[[Message], bool]

    def __call__(self, message: Message) -> bool:
        return self.predicate(message)

    def __and__(self, other: Filter) -> Filter:
        return Filter(lambda message: self(message) and other(message))

    def __or__(self, other: Filter) -> Filter:
        return Filter(lambda message: self(message) or other(message))

    def __invert__(self) -> Filter:
        return Filter(lambda message: not self(message))


text = Filter(lambda message: message.content_type is ContentType.TEXT)
incoming = Filter(lambda message: message.is_outgoing is False)
outgoing = Filter(lambda message: message.is_outgoing is True)
private = Filter(lambda message: message.chat_kind is ChatKind.PRIVATE)
group = Filter(lambda message: message.chat_kind is ChatKind.GROUP)

__all__ = ["Filter", "group", "incoming", "outgoing", "private", "text"]
