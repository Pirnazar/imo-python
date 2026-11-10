<p align="center">
  <img src="docs/assets/imo-mark.svg" alt="" width="64" height="64">
</p>
<h1 align="center">imo-python</h1>
<p align="center">
  <strong>Unofficial Python client for IMO Web</strong><br>
  Sign in by QR, send messages and files, and read chat history.
</p>
<p align="center">
  <a href="pyproject.toml">Python 3.11+</a> · <a href="LICENSE">MIT</a> · <a href="#verification">Alpha</a>
</p>
<p align="center">
  <a href="#quick-start">Quick start</a> · <a href="docs/api.md">API</a> · <a href="examples/README.md">14 examples</a><br>
  <a href="docs/web_client.en.md">English</a> · <a href="docs/web_client.md">Русский</a> · <a href="docs/web_client.tk.md">Türkmençe</a>
</p>

## Quick start

Run from the project directory with Python 3.11 or newer.

```sh
python -m pip install -e ".[qr]"
python examples/web_qr.py
```

Scan the terminal QR in the official IMO app and confirm the new session. The interactive shell lets you run `contacts`, `chats`, and `history BUID` after one scan. For a QR image you can open in a browser, use [qr_to_file.py](examples/qr_to_file.py).

```python
from imo import IMOClient

with IMOClient() as client:
    client.connect()
    for chat in client.list_chats():
        print(chat.buid)
```

## Examples by task

- **Find a recipient.** Look up a contact by exact name or copy a BUID from the chat list. [Contacts](examples/contacts.py) · [Chats and groups](examples/chats.py)
- **Send a message.** Send text by name or BUID, attach a local file, or preview a CSV before sending. [Text](examples/send_text.py) · [File](examples/send_file.py) · [CSV](examples/send_batch.py)
- **Read a conversation.** Export recent messages as JSON Lines or save attachments from history. [History](examples/history.py) · [Downloads](examples/download_media.py)
- **Receive messages.** Wait for a single event or run a handler until the chosen count is reached. [Receive once](examples/receive_one.py) · [Listen](examples/listen.py)

The [examples catalog](examples/README.md) includes commands and prerequisites. Two scripts run offline:

```sh
python examples/inspect_attachments.py
python examples/send_batch.py examples/batch.example.csv
```

## Listen for incoming messages

```python
from imo import IMOClient

with IMOClient() as client:
    client.connect()

    @client.on_message
    def handle(message):
        print(message.buid, message.text)

    client.run()
```

Use each client instance from one thread. The session stays in memory. `logout()` asks the server to end it.

Use `connect(show_qr=callback)` when your code renders its own QR. For help with QR codes, exact-name matching, and send timeouts, see [troubleshooting](docs/troubleshooting.md).

## Verification

The real IMO server has issued QR challenges, and the public IMO CDN has served a test image. Account operations and file transfers are covered by scripted protocol tests. End-to-end sends and private media transfers still require a QR-confirmed account test.

```sh
python -m pip install -e ".[dev]"
python -m pytest
python -m ruff check .
python -m build
```

Set `IMO_WEB_LIVE=1` to include the live QR and public CDN tests. The async SDK, Windows bridge, offline models, and research are preserved on the [archive/full-sdk branch](https://github.com/Pirnazar/imo-python/tree/archive/full-sdk).
