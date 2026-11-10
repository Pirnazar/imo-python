"""Inspect attachment metadata offline from a JSON file or an included sample."""

import argparse
import json
from pathlib import Path

from imo import extract_attachments


SAMPLE = {
    "imdata": {
        "type": "photo_uploaded",
        "objects": [{"object_id": "imo/demo-photo", "filename": "sample.jpg", "filesize": 1024}],
    },
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("json_file", type=Path, nargs="?", help="One history row or imdata object")
    args = parser.parse_args()
    record = json.loads(args.json_file.read_text(encoding="utf-8-sig")) if args.json_file else SAMPLE
    if not isinstance(record, dict):
        parser.error("expected a JSON object")
    for attachment in extract_attachments(record):
        print(attachment.kind, attachment.filename, attachment.size, sep="\t")


if __name__ == "__main__":
    main()
