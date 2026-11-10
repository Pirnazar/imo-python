"""Preview a CSV batch offline, or send it with --apply after exact contact resolution."""

import argparse
import csv
import math
from pathlib import Path

from imo import IMOClient, IMOError


def read_rows(path: Path) -> list[tuple[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file, delimiter=";", strict=True)
        if reader.fieldnames != ["contact", "text"]:
            raise ValueError("expected CSV header contact;text")
        rows = []
        for row in reader:
            name, text = row["contact"], row["text"]
            if None in row or not name or not name.strip() or not text or not text.strip():
                raise ValueError(f"invalid contact or text at CSV line {reader.line_num}")
            rows.append((name.strip(), text))
        return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_file", type=Path)
    parser.add_argument("--apply", action="store_true", help="Actually sign in and send the messages")
    parser.add_argument("--delay", type=float, default=8.0, help="Seconds between messages")
    args = parser.parse_args()
    if not math.isfinite(args.delay) or args.delay < 0:
        parser.error("--delay must be finite and nonnegative")
    try:
        rows = read_rows(args.csv_file)
    except (csv.Error, OSError, ValueError) as error:
        parser.error(str(error))
    if not rows:
        print("No messages in the CSV.")
        return
    if not args.apply:
        for name, text in rows:
            print(f"{name!r}: {text!r}")
        print(f"{len(rows)} message(s) in the preview. Use --apply to send.")
        return

    try:
        with IMOClient() as client:
            client.connect()
            contacts = client.get_contacts()
            resolved = [(client.find_contact(name, contacts=contacts, exact=True), text) for name, text in rows]
            results = client.send_many(resolved, delay=args.delay, stop_on_error=True)
    except IMOError as error:
        parser.exit(1, f"{error}\n")

    for (name, _), result in zip(rows, results, strict=False):
        print(f"{name}: {result.sent.message_id if result.sent else result.error}")
    if len(results) != len(rows) or any(not result.ok for result in results):
        parser.exit(1, "Batch stopped. Check the chat before retrying any unconfirmed message.\n")


if __name__ == "__main__":
    main()
