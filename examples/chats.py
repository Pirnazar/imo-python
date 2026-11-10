"""List conversations, or list members of a group by its BUID."""

import argparse

from imo import IMOClient


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--group", metavar="BUID", help="List members of this group")
    args = parser.parse_args()

    with IMOClient() as client:
        client.connect()
        if args.group:
            for member in client.get_group_members(args.group):
                print(member.uid, member.display, "owner" if member.is_owner else "member", sep="\t")
            return

        for chat in client.list_chats():
            preview = chat.last_message.text if chat.last_message else ""
            print(chat.buid, "group" if chat.is_group else "direct", preview, sep="\t")


if __name__ == "__main__":
    main()
