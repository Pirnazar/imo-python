"""Listen for incoming messages, optionally limiting output to one chat."""

import argparse

from imo import IMOClient, WebMessage


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--buid", help="Print messages only from this chat")
    parser.add_argument("--count", type=int, help="Stop after this many matching messages")
    args = parser.parse_args()
    if args.count is not None and args.count < 1:
        parser.error("--count must be positive")
    received = 0

    try:
        with IMOClient() as client:
            client.connect()

            @client.on_message
            def handle(message: WebMessage) -> None:
                nonlocal received
                if args.buid is not None and message.buid != args.buid:
                    return
                print(message.buid, message.author, message.text, sep="\t", flush=True)
                received += 1
                if args.count is not None and received >= args.count:
                    client.stop()

            client.run()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
