"""Typed mirrors of IMO 1.5.9.3 data-model layer (Imo.DataModel).

Pure, inert data structures reconstructed from static reflection of the installed
assemblies — enums match the client's own values; field names match its snake_case
JSON. Nothing here touches the network, the IMO process, or any session.

Use for: parsing/representing message and contact structures you already have, and
mapping content types / delivery states. It does NOT send or fetch anything — see
docs/data_models.md and docs/standalone_bridge_research.md for why.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Optional


class MessageContentType(IntEnum):
    """Imo.DataModel.Enums.MessageContentType — on-wire message discriminator."""
    TEXT = 0
    PHOTO = 1
    FILE = 2
    AUDIO = 3
    REPLY = 4
    STICKER = 5
    SYSTEM = 6
    VIDEO = 7
    MESSAGE_REPLY = 8
    DICE = 9
    GIF = 10
    NEW_STICKER = 11
    USER_PROFILE = 12
    BIG_GROUP_INVITE = 13
    UNIVERSAL_CARD = 14
    CALL_LOG = 15
    GROUP_CALL = 16


class MessageState(IntEnum):
    """Delivery state. ACKED≈sent (server accepted), DELIVERED≈reached peer, SEEN≈read."""
    SENDING = 0
    ACKED = 1
    DELIVERED = 2
    SEEN = 3
    SENDFAILED = 4


class MessageSendState(IntEnum):
    SUCCESS = 0
    FAIL = -1
    SENDING = 2
    HIDE = 3
    RETRACT = 4


class MessageType(IntEnum):
    SENT = 0
    RECEIVED = 1
    SYSTEM = 2


class ChatType(IntEnum):
    """Imo.DataModel.Enums.ChatTypes."""
    UNKNOWN = -1
    PERSON = 0
    GROUP = 2
    STORY = 3
    FILE_HELPER = 4


# Content class name per content type, as in Imo.DataModel.Models.Messages.*
CONTENT_CLASS = {
    MessageContentType.TEXT: "TextMessage",
    MessageContentType.PHOTO: "PhotoMessage",
    MessageContentType.FILE: "FileMessage",
    MessageContentType.AUDIO: "AudioMessage",
    MessageContentType.REPLY: "ObjectReplyMessage",
    MessageContentType.STICKER: "StickerMessage",
    MessageContentType.SYSTEM: "SystemMessage",
    MessageContentType.VIDEO: "VideoMessage",
    MessageContentType.MESSAGE_REPLY: "MessageReplyMessage",
    MessageContentType.DICE: "DiceMessage",
    MessageContentType.GIF: "GifMessage",
    MessageContentType.NEW_STICKER: "NewStikcerMessage",
    MessageContentType.USER_PROFILE: "UserProfileMessage",
    MessageContentType.BIG_GROUP_INVITE: "BigGroupInviteMessage",
    MessageContentType.UNIVERSAL_CARD: "UniversalCardmMessage",
    MessageContentType.CALL_LOG: "CallLogMessage",
    MessageContentType.GROUP_CALL: "GroupCallMessage",
}


@dataclass
class Head:
    """Imo.DataModel.Models.HeadModel — a contact / chat head. `buid` is the address."""
    buid: str = ""
    display: str = ""          # json: display
    alias: str = ""            # json: alias
    icon: str = ""             # json: icon
    note: str = ""             # json: note
    is_buddy: bool = False     # json: is_buddy
    is_favorite: bool = False  # json: favorite
    is_muted: bool = False     # json: is_muted

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> "Head":
        return cls(
            buid=d.get("buid", ""),
            display=d.get("display", ""),
            alias=d.get("alias", ""),
            icon=d.get("icon", ""),
            note=d.get("note", ""),
            is_buddy=bool(d.get("is_buddy", False)),
            is_favorite=bool(d.get("favorite", False)),
            is_muted=bool(d.get("is_muted", False)),
        )


@dataclass
class Message:
    """Imo.DataModel.Models.MessageModel (+ subclasses). A flattened, inert view.

    `content` holds the text for TEXT; url/name for media kinds. `imdata` keeps the
    raw app payload blob (Imo.DataModel.Models.MsgSendModel.Imdata) when available —
    reconstructing valid imdata for *sending* is out of scope (see docs)."""
    buid: str = ""
    content_type: MessageContentType = MessageContentType.TEXT
    direction: MessageType = MessageType.RECEIVED
    state: MessageState = MessageState.SENDING
    content: str = ""
    timestamp_nano: int = 0
    author: str = ""
    imdata: Optional[dict[str, Any]] = field(default=None)

    @property
    def content_class(self) -> str:
        return CONTENT_CLASS.get(self.content_type, "MessageModel")


# imdata object_type token -> MessageContentType (see docs/imdata_format.md)
OBJECT_TYPE = {
    "text": MessageContentType.TEXT,
    "photo": MessageContentType.PHOTO,
    "video": MessageContentType.VIDEO,
    "audio": MessageContentType.AUDIO,
    "file": MessageContentType.FILE,
    "sticker": MessageContentType.STICKER,
    "new_sticker": MessageContentType.NEW_STICKER,
    "gif": MessageContentType.GIF,
    "dice": MessageContentType.DICE,
    "object_reply": MessageContentType.REPLY,
    "message_reply": MessageContentType.MESSAGE_REPLY,
    "universal_card": MessageContentType.UNIVERSAL_CARD,
    "call_log": MessageContentType.CALL_LOG,
    "group_call": MessageContentType.GROUP_CALL,
    "big_group_invite": MessageContentType.BIG_GROUP_INVITE,
}

# human-readable content extracted per object_type
_CONTENT_KEYS = {
    MessageContentType.TEXT: ("text",),
    MessageContentType.PHOTO: ("img_url", "thumb_url", "photo"),
    MessageContentType.VIDEO: ("bigo_url", "thumb_url", "video"),
    MessageContentType.AUDIO: ("local_path", "audio"),
    MessageContentType.FILE: ("file_name",),
    MessageContentType.GIF: ("web_url", "http_url"),
    MessageContentType.STICKER: ("sticker_id",),
    MessageContentType.NEW_STICKER: ("new_sticker_id", "lottie_url"),
}


def parse_imdata(imdata: dict[str, Any], *, buid: str = "") -> Message:
    """Read-only: turn an observed `imdata` dict (docs/imdata_format.md) into a Message.

    Parses structures you already have; it neither builds valid wire payloads nor sends."""
    obj = imdata.get("objects") or []
    first = obj[0] if obj and isinstance(obj[0], dict) else imdata
    token = (imdata.get("object_type") or first.get("object_type") or "text").lower()
    ctype = OBJECT_TYPE.get(token, MessageContentType.TEXT)
    content = ""
    for k in _CONTENT_KEYS.get(ctype, ()):  # first present key wins
        v = first.get(k) or imdata.get(k)
        if v:
            content = str(v)
            break
    return Message(
        buid=imdata.get("buid", buid),
        content_type=ctype,
        content=content,
        timestamp_nano=int(imdata.get("timestamp_nano") or 0),
        author=str(imdata.get("author_uid") or imdata.get("author") or ""),
        imdata=imdata,
    )


__all__ = [
    "MessageContentType", "MessageState", "MessageSendState", "MessageType",
    "ChatType", "CONTENT_CLASS", "OBJECT_TYPE", "Head", "Message", "parse_imdata",
]
