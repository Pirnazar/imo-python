"""Render the QR as a local SVG and remove it when the login attempt ends."""

import argparse
from pathlib import Path

import qrcode
from qrcode.image.svg import SvgPathFillImage

from imo import IMOClient, QRChallenge


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("imo-qr.svg"))
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        parser.error("output already exists")
    created = False

    def show_qr(challenge: QRChallenge) -> None:
        nonlocal created
        with output.open("xb") as file:
            created = True
            qrcode.make(challenge.payload, image_factory=SvgPathFillImage).save(file)
        print(f"Open {output} and scan it in the IMO app within {challenge.ttl}s.", flush=True)

    try:
        with IMOClient() as client:
            client.connect(show_qr=show_qr)
            print("Signed in.")
    finally:
        if created:
            output.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
