"""Print the most recent messages as JSON Lines, newest first."""

import argparse
import json

from imo import IMOClient


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("buid", help="Conversation ID returned by IMO")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--before", help="A timestamp_nano_str cursor")
    args = parser.parse_args()
    if args.limit < 1:
        parser.error("--limit must be positive")

    with IMOClient() as client:
        client.connect()
        for message in client.iter_history(args.buid, max_messages=args.limit, before=args.before):
            print(json.dumps({
                "buid": message.buid,
                "message_id": message.message_id,
                "author": message.author,
                "timestamp_nano": message.timestamp_nano,
                "text": message.text,
                "attachment_count": len(message.attachments),
            }))


if __name__ == "__main__":
    main()
