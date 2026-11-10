"""Wait for one incoming message and print its text and attachment metadata."""

import argparse

from imo import IMOClient, IMOTimeoutError, WebMessage


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=int, default=30)
    args = parser.parse_args()
    if args.timeout < 1:
        parser.error("--timeout must be positive")

    with IMOClient() as client:
        client.connect()
        try:
            message = WebMessage.from_record(client.receive_message(timeout=args.timeout))
        except IMOTimeoutError:
            print("No incoming message within the timeout.")
            return
        print(message.buid, message.author, message.text, sep="\t")
        for attachment in message.attachments:
            print(attachment.kind, attachment.filename, attachment.size, sep="\t")


if __name__ == "__main__":
    main()
