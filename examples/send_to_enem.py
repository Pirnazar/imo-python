"""Sign in to IMO Web with a QR code and send one text message to Enem."""
import argparse
import sys

from imo import IMOClient, IMOError


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("text", help="Message to send to Enem")
    args = parser.parse_args()
    if not args.text.strip():
        parser.error("message must not be empty")

    try:
        with IMOClient() as client:
            client.connect()
            receipt = client.send_message(name="Enem", text=args.text)
            print(f"IMO confirmed the send request for Enem. Message ID: {receipt.message_id}")
    except IMOError as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
