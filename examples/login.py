"""Confirm a fresh QR login and print the account's display name."""

import argparse

from imo import IMOClient


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", choices=("sgp", "sjc", "fra"), default="sgp")
    args = parser.parse_args()
    with IMOClient(region=args.region) as client:
        client.connect()
        profile = client.get_me()
        print("Signed in as", profile.get("alias") or profile["uid"])


if __name__ == "__main__":
    main()
