"""Download attachments from recent history and report individual failures."""

import argparse
from pathlib import Path
import sys

from imo import IMOClient, IMODownloadError


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("buid")
    parser.add_argument("directory", type=Path)
    parser.add_argument("--limit", type=int, default=20, help="Maximum number of messages to inspect")
    parser.add_argument("--max-mib", type=int, default=32, help="Size limit per attachment")
    args = parser.parse_args()
    if min(args.limit, args.max_mib) < 1:
        parser.error("--limit and --max-mib must be positive")

    with IMOClient() as client:
        client.connect()
        for message in client.iter_history(args.buid, max_messages=args.limit):
            for attachment in message.attachments:
                try:
                    path = client.download_attachment(attachment, args.directory, max_bytes=args.max_mib * 1024**2)
                except IMODownloadError as error:
                    print(f"{attachment.filename}: {error}", file=sys.stderr)
                else:
                    print(path)


if __name__ == "__main__":
    main()
