"""Send one text message by BUID or exact contact name."""

import argparse

from imo import IMOClient, IMOError


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    recipient = parser.add_mutually_exclusive_group(required=True)
    recipient.add_argument("--id", metavar="BUID")
    recipient.add_argument("--name", help="Exact contact name")
    parser.add_argument("text")
    args = parser.parse_args()
    if not args.text.strip():
        parser.error("text must not be empty")

    try:
        with IMOClient() as client:
            client.connect()
            receipt = client.send_message(id=args.id, name=args.name, text=args.text)
            print(receipt.buid, receipt.message_id, receipt.timestamp_nano, sep="\t")
    except IMOError as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
