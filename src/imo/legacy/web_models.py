"""Typed views of IMO Web records. The raw methods in IMOClient also remain available."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from ._media import Attachment, _message_imdata, extract_attachments


def _text(value):
    return value if isinstance(value, str) else ""


def _timestamp(value):
    if (isinstance(value, str) and 1 <= len(value) <= 20
            and value.isascii() and value.isdecimal()):
        return value
    return None


@dataclass(frozen=True)
class WebMessage:
    """One message from chat history or a live recv_im event."""

    buid: str
    text: str
    timestamp_nano: str | None
    message_id: str
    author: str
    kind: str
    is_sent: bool | None
    attachments: tuple[Attachment, ...]
    raw: dict = field(repr=False, compare=False)

    @classmethod
    def from_record(cls, record: Mapping, *, buid: str = "") -> WebMessage:
        if not isinstance(record, Mapping):
            raise TypeError("record must be a mapping")
        imdata = _message_imdata(record)
        return cls(
            buid=_text(record.get("buid")) or buid,
            text=_text(record.get("msg")),
            timestamp_nano=_timestamp(record.get("timestamp_nano_str")),
            message_id=_text(record.get("msg_id")) or _text(imdata.get("msg_id")),
            author=_text(record.get("author")),
            kind=_text(imdata.get("type")),
            is_sent=record.get("is_sent") if type(record.get("is_sent")) is bool else None,
            attachments=tuple(extract_attachments(imdata)),
            raw=dict(record),
        )


@dataclass(frozen=True)
class Chat:
    """An entry in the account's chat index."""

    buid: str
    changed_at_nano: str | None
    last_message: WebMessage | None
    raw: dict = field(repr=False, compare=False)

    @property
    def is_group(self) -> bool:
        return self.buid.endswith(";")

    @classmethod
    def from_record(cls, record: Mapping) -> Chat:
        buid = _text(record.get("buid"))
        if not buid.strip():
            raise ValueError("chat record has no conversation ID")
        changed_at = record.get("change_ts")
        if type(changed_at) is int:
            changed_at = str(changed_at)
        last = record.get("last_message")
        return cls(buid, _timestamp(changed_at),
                   WebMessage.from_record(last, buid=buid) if isinstance(last, Mapping) else None,
                   dict(record))


@dataclass(frozen=True)
class GroupMember:
    """A visible member returned by the group roster endpoint."""

    uid: str
    display: str
    icon: str
    is_owner: bool
    raw: dict = field(repr=False, compare=False)

    @classmethod
    def from_record(cls, record: Mapping) -> GroupMember:
        return cls(
            uid=_text(record.get("uid")).partition(";")[0] or _text(record.get("buid")),
            display=_text(record.get("display")),
            icon=_text(record.get("icon")),
            is_owner=bool(record.get("is_owner")),
            raw=dict(record),
        )
