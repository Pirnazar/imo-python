"""Unit tests for the read-only data-model / imdata layer."""
from imo.models import (
    ChatType,
    Head,
    Message,
    MessageContentType,
    MessageState,
    OBJECT_TYPE,
    parse_imdata,
)


def test_enum_values_match_client():
    assert MessageContentType.TEXT == 0
    assert MessageContentType.GROUP_CALL == 16
    assert MessageState.ACKED == 1 and MessageState.SEEN == 3
    assert ChatType.GROUP == 2 and ChatType.FILE_HELPER == 4


def test_content_class_lookup():
    assert Message(content_type=MessageContentType.PHOTO).content_class == "PhotoMessage"
    assert Message(content_type=MessageContentType.TEXT).content_class == "TextMessage"


def test_head_from_json_snake_case():
    h = Head.from_json(
        {"buid": "abc", "display": "Мама", "is_buddy": True, "favorite": True, "note": "n"}
    )
    assert h.buid == "abc" and h.display == "Мама"
    assert h.is_buddy and h.is_favorite and h.note == "n"
    assert h.is_muted is False


def test_object_type_map_covers_tokens():
    for token in ("text", "photo", "video", "audio", "file", "sticker", "gif", "dice"):
        assert token in OBJECT_TYPE


def test_parse_imdata_text():
    m = parse_imdata(
        {"buid": "C1", "object_type": "text",
         "objects": [{"object_type": "text", "text": "Salam"}], "timestamp_nano": 17}
    )
    assert m.content_type == MessageContentType.TEXT
    assert m.content == "Salam" and m.buid == "C1" and m.timestamp_nano == 17


def test_parse_imdata_photo_unicode_and_fallback():
    m = parse_imdata(
        {"buid": "C2", "objects": [{"object_type": "photo", "img_url": "http://x/п.jpg"}]}
    )
    assert m.content_type == MessageContentType.PHOTO
    assert m.content == "http://x/п.jpg"
    assert m.content_class == "PhotoMessage"


def test_parse_imdata_unknown_type_defaults_to_text():
    m = parse_imdata({"buid": "C3", "object_type": "no_such_type", "objects": []})
    assert m.content_type == MessageContentType.TEXT
    assert m.imdata["buid"] == "C3"  # raw payload preserved
