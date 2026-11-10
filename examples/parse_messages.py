"""Example: parse observed imo `imdata` payloads into typed Message objects.

This only *reads* structures you already have (e.g. logged/exported payloads).
It does not connect to imo, read your session, or send anything.

    python examples/parse_messages.py
"""
from imo.models import Head, parse_imdata

# Example payloads shaped like docs/imdata_format.md (not real account data).
SAMPLES = [
    {"buid": "chat_a", "object_type": "text",
     "objects": [{"object_type": "text", "text": "Salam, nähili?"}],
     "timestamp_nano": 1_700_000_000_000_000_000},
    {"buid": "chat_b",
     "objects": [{"object_type": "photo", "img_url": "https://im.example/p.jpg",
                  "original_width": 1280, "original_height": 720}]},
    {"buid": "chat_b",
     "objects": [{"object_type": "file", "file_name": "report.pdf", "file_size": 20480}]},
]


def main() -> None:
    contact = Head.from_json({"buid": "chat_a", "display": "Enem", "is_buddy": True})
    print(f"contact: {contact.display} <{contact.buid}> buddy={contact.is_buddy}\n")

    for raw in SAMPLES:
        msg = parse_imdata(raw)
        print(f"[{msg.content_type.name:<6}] {msg.content_class:<13} "
              f"chat={msg.buid!r} content={msg.content!r}")


if __name__ == "__main__":
    main()
