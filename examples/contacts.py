"""List contacts, or find a single exact match by name."""

import argparse

from imo import IMOClient, IMOContactNotFound


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", help="Match an alias, display name, or note exactly")
    args = parser.parse_args()

    with IMOClient() as client:
        client.connect()
        contacts = client.get_contacts()
        if args.name is not None:
            try:
                contacts = [client.find_contact(args.name, contacts=contacts, exact=True)]
            except IMOContactNotFound as error:
                parser.exit(1, f"{error}\n")
        for contact in contacts:
            print(contact.buid, contact.note or contact.alias or contact.display, sep="\t")


if __name__ == "__main__":
    main()
