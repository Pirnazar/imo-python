"""Send one local file and, optionally, a separate text message."""

import argparse
from pathlib import Path

from imo import IMOClient, IMOError, IMOPartialSendError


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    recipient = parser.add_mutually_exclusive_group(required=True)
    recipient.add_argument("--id", metavar="BUID")
    recipient.add_argument("--name", help="Exact contact name")
    parser.add_argument("file", type=Path)
    parser.add_argument("--text", help="Separate text message sent after the file")
    args = parser.parse_args()
    if not args.file.is_file():
        parser.error("file must exist")
    if args.text is not None and not args.text.strip():
        parser.error("text must not be empty")

    try:
        with IMOClient() as client:
            client.connect()
            result = client.send_message(id=args.id, name=args.name, text=args.text, media=args.file)
            if isinstance(result, tuple):
                file_receipt, text_receipt = result
                print("File:", file_receipt.message_id)
                print("Text:", text_receipt.message_id)
            else:
                print("File:", result.message_id)
    except IMOPartialSendError as error:
        parser.exit(1, f"File confirmed ({error.attachment.message_id}). {error}\n")
    except (IMOError, OSError, ValueError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
