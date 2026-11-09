"""Read-only reader for IMO's local SQLite store (DB/db1.db).

Opens the user's own local database **read-only** (SQLite immutable mode) and maps the
`T_Chater` chat-list table to `Head`/`ChatType`. No network, no session, no writes.

Note: depending on build/account, the live client may keep chats in its in-memory /
proprietary embedded store rather than this SQLite file (which can be empty). This reader
returns whatever `T_Chater` actually contains.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from dataclasses import dataclass
from typing import Iterator, Optional

from .models import ChatType, Head


@dataclass
class ChatRow:
    """One row of T_Chater (the chat list)."""
    key_id: str
    chat_type: ChatType
    is_top_most: bool
    show_in_list: bool
    last_activity_ts: int
    last_message_time: int
    last_message_content: str
    last_msg_key: str

    def as_head(self) -> Head:
        return Head(buid=self.key_id)


def _default_db_path() -> Optional[str]:
    base = os.path.join(os.environ.get("APPDATA", ""), "imo")
    if not os.path.isdir(base):
        return None
    for entry in os.listdir(base):
        p = os.path.join(base, entry, "DB", "db1.db")
        if os.path.isfile(p):
            return p
    return None


def _to_bool(v) -> bool:
    return str(v).strip().lower() in ("1", "true", "yes")


def _to_chat_type(v) -> ChatType:
    try:
        return ChatType(int(v))
    except (ValueError, TypeError):
        # The client declares ChatType as TEXT and uses the CLR enum names.
        names = {
            "person_chat": ChatType.PERSON,
            "group_chat": ChatType.GROUP,
            "story_chat": ChatType.STORY,
            "filehelper_chat": ChatType.FILE_HELPER,
        }
        return names.get(str(v).strip().casefold(), ChatType.UNKNOWN)


class LocalDB:
    """Read-only accessor for db1.db."""

    def __init__(self, path: Optional[str] = None):
        self.path = path or _default_db_path()
        if not self.path or not os.path.isfile(self.path):
            raise FileNotFoundError("db1.db not found; pass path= explicitly")

    def _connect(self) -> sqlite3.Connection:
        # immutable=1: open read-only even while the client holds the file.
        uri = Path(self.path).resolve().as_uri() + "?mode=ro&immutable=1"
        return sqlite3.connect(uri, uri=True)

    def chats(self) -> Iterator[ChatRow]:
        con = self._connect()
        try:
            con.row_factory = sqlite3.Row
            cur = con.execute(
                "SELECT KeyID, ChatType, IsTopMost, ShowInChatsList, "
                "LastActivityTimestamp, LastMessageTime, LastMessageContent, Key_LastMsg "
                "FROM T_Chater ORDER BY LastActivityTimestamp DESC"
            )
            for r in cur:
                yield ChatRow(
                    key_id=r["KeyID"] or "",
                    chat_type=_to_chat_type(r["ChatType"]),
                    is_top_most=_to_bool(r["IsTopMost"]),
                    show_in_list=_to_bool(r["ShowInChatsList"]),
                    last_activity_ts=int(r["LastActivityTimestamp"] or 0),
                    last_message_time=int(r["LastMessageTime"] or 0),
                    last_message_content=r["LastMessageContent"] or "",
                    last_msg_key=r["Key_LastMsg"] or "",
                )
        finally:
            con.close()

    def chat_count(self) -> int:
        con = self._connect()
        try:
            return con.execute("SELECT COUNT(*) FROM T_Chater").fetchone()[0]
        finally:
            con.close()


__all__ = ["LocalDB", "ChatRow"]
