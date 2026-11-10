import sqlite3

from imo.models import ChatType
from imo.localdb import LocalDB


def test_chat_snapshot_matches_imo_table(tmp_path):
    db = tmp_path / "copy #1 & chat.db"
    connection = sqlite3.connect(db)
    try:
        connection.executescript("""
            CREATE TABLE T_Chater (
                KeyID TEXT PRIMARY KEY, TopMostTs LONG, IsTopMost TEXT, LastActivity LONG,
                ShowInChatsList TEXT, LastActivityTimestamp LONG, ChatType TEXT,
                LastMessageTime LONG, LastMessageContent TEXT, Key_LastMsg TEXT
            );
            INSERT INTO T_Chater (KeyID, ChatType, IsTopMost, ShowInChatsList,
                LastActivityTimestamp, LastMessageTime, LastMessageContent, Key_LastMsg)
            VALUES
                ('fixture-person', '0', 'False', 'True', 10, 3, '', ''),
                ('fixture-group', 'Group_Chat', 'True', 'False', 20, 5, 'Salam!', 'fixture-msg');
        """)
    finally:
        connection.close()

    before = db.read_bytes()
    snapshot = LocalDB(str(db))
    assert snapshot.chat_count() == 2
    group, person = snapshot.chats()
    assert group.chat_type == ChatType.GROUP
    assert group.as_head().buid == 'fixture-group'
    assert group.is_top_most and not group.show_in_list
    assert group.last_message_content == 'Salam!'
    assert person.chat_type == ChatType.PERSON
    assert person.show_in_list and not person.is_top_most
    assert db.read_bytes() == before
