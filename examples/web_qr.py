"""Scan a fresh QR in your terminal and keep one account session for multiple operations."""
import argparse
import csv
import json
from pathlib import Path
import sys

from imo.legacy import IMOClient, IMODownloadError, IMOError



def read_batch(path):
    """Rows of ``contact;text`` (or comma/tab separated). ``#`` lines and a header row are skipped."""
    lines = [line for line in Path(path).read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    if not lines:
        return []
    rows = []
    for row in csv.reader(lines, csv.Sniffer().sniff(lines[0], delimiters=";,\t")):
        if not row or row[0].strip().startswith("#"):
            continue
        if len(row) < 2:
            raise ValueError(f"row without text: {row}")
        if row[0].strip().casefold() in ("contact", "контакт"):
            continue
        rows.append((row[0].strip(), row[1].replace("\\n", "\n")))
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", choices=("sgp", "sjc", "fra"), default="sgp")
    parser.add_argument("--download-dir", default="imo-downloads",
                        help="Output directory for the download command")
    parser.add_argument("--delay", type=float, default=8.0,
                        help="Seconds between messages of the batch command (±30%%)")
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    with IMOClient(region=args.region) as client:
        client.connect()
        print("Commands: me, contacts, chats, history BUID, download BUID [LIMIT], "
              "members BUID, send BUID TEXT, sendto NAME | TEXT, batch FILE.csv, receive, logout, exit")
        while True:
            try:
                verb, _, argument = input("imo> ").strip().partition(" ")
            except (EOFError, KeyboardInterrupt):
                break
            try:
                if verb == "me":
                    result = client.get_me()
                elif verb == "contacts":
                    result = [{"buid": contact.buid, "name": contact.alias or contact.display}
                              for contact in client.get_contacts()]
                elif verb == "chats":
                    result = client.get_chats()
                elif verb == "history":
                    result = client.get_history(argument)
                elif verb == "members":
                    result = [{"uid": member.uid, "name": member.display, "owner": member.is_owner}
                              for member in client.get_group_members(argument)]
                elif verb == "download":
                    buid, _, limit = argument.partition(" ")
                    result = []
                    for message in client.iter_history(buid, max_messages=int(limit) if limit else 50):
                        for attachment in message.attachments:
                            try:
                                path = client.download_attachment(attachment, args.download_dir)
                            except IMODownloadError as error:
                                print(f"{attachment.filename}: {error}", file=sys.stderr)
                            else:
                                result.append(str(path))
                elif verb == "send":
                    buid, _, text = argument.partition(" ")
                    receipt = client.send_message(buid, text)
                    result = {"message_id": receipt.message_id, "timestamp_nano": receipt.timestamp_nano}
                elif verb == "sendto":
                    name, _, text = argument.partition("|")
                    receipt = client.send_message(name=name, text=text.strip())
                    result = {"buid": receipt.buid, "timestamp_nano": receipt.timestamp_nano}
                elif verb == "batch":
                    result = [{"to": row.target, "ok": row.ok, "error": str(row.error) if row.error else None}
                              for row in client.send_many(read_batch(argument), delay=args.delay, by_name=True)]
                elif verb == "receive":
                    result = client.receive_message(timeout=30)
                elif verb == "logout":
                    client.logout()
                    break
                elif verb == "exit":
                    break
                else:
                    continue
                print(json.dumps(result, ensure_ascii=False, indent=2))
            except (IMOError, OSError, ValueError) as error:
                print(error, file=sys.stderr)
                if not client.is_authenticated:
                    return 1
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (IMOError, KeyboardInterrupt) as error:
        print(error, file=sys.stderr)
        raise SystemExit(1)
