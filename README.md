# imo-python

A Python client for IMO Web. It uses the Web protocol directly and opens a separate session that you confirm by scanning a QR code in the official IMO app.

[English](docs/web_client.en.md) · [Русский](docs/web_client.md) · [Türkmençe](docs/web_client.tk.md) · [API reference](docs/api.md) · [Examples](examples/README.md)

## Installation

Run from the project directory with Python 3.11 or newer.

```sh
python -m pip install -e ".[qr]"
python examples/web_qr.py
```

`IMOClient()` uses IMO Web directly. The `qr` extra enables terminal rendering. To render the QR yourself, pass `show_qr=` to `connect()` and install the base package.

Try the offline examples to inspect attachment metadata or preview a CSV before signing in.

```sh
python examples/inspect_attachments.py
python examples/send_batch.py examples/batch.example.csv
```

## Quick start

```python
from imo import IMOClient

with IMOClient() as client:
    client.connect()
    for chat in client.list_chats():
        print(chat.buid)

    # Send to one exact match from the contact list.
    # client.send_message(name="Enem", text="Salam!")
```

Use `examples/contacts.py` or `examples/chats.py` to find a BUID, the conversation ID returned by IMO. Pass the BUID to `get_history()` for one page or `iter_history()` to follow pages. Pass a history record or incoming message to `download_attachments()`.

```python
with IMOClient() as client:
    client.connect()

    @client.on_message
    def handle(message):
        print(message.buid, message.text)

    client.run()
```

Use each client instance from one thread. The session stays in memory. `logout()` asks the server to end it.

For more commands, see the [examples catalog](examples/README.md). For help with QR codes, exact-name matching, and send timeouts, see [troubleshooting](docs/troubleshooting.md).

## Verification

The real IMO server has issued QR challenges, and the public IMO CDN has served a test image. Account operations and file transfers are covered by scripted protocol tests. End-to-end sends and private media transfers still require a QR-confirmed account test.

```sh
python -m pip install -e ".[dev]"
python -m pytest
python -m ruff check .
python -m build
```

Set `IMO_WEB_LIVE=1` to include the live QR and public CDN tests. The async SDK, Windows bridge, offline models, and research are preserved on the [archive/full-sdk branch](https://github.com/Pirnazar/imo-python/tree/archive/full-sdk).
