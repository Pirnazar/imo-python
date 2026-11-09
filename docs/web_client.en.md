# imo-python 0.3.0

[English](web_client.en.md) · [Русский](web_client.md) · [Türkmençe](web_client.tk.md)

`imo-python` is a synchronous client for the reverse-engineered IMO Web protocol. It opens a separate session that you confirm in the official IMO mobile app. It runs on Python 3.8+ and keeps the session in memory. Use one thread per client instance. [Official IMO Web](https://web.imo.im/) · [IMO QR login help](https://imo.im/faq/More-Ways-to-Login)

## Installation and QR login

From the project directory, install the library and run the interactive example.

```text
python -m pip install -e ".[qr]"
python examples/web_qr.py --download-dir imo-downloads
```

Scan the QR with your phone and confirm the login in IMO. In the example, `chats` lists conversation IDs, `history BUID` reads the latest page, and `download BUID 20` saves attachments from the latest 20 messages. `BUID` is the conversation ID returned by IMO.

```python
import qrcode

from imo import IMOClient

with IMOClient(region="sgp", timeout=15) as client:
    challenge = client.begin_qr_login()
    qr = qrcode.QRCode(border=4)
    qr.add_data(challenge.payload)
    qr.print_ascii(invert=True)
    client.wait_for_login()

    profile = client.get_me()
    contacts = client.get_contacts()
    chats = client.get_chats()

    if chats:
        buid = chats[0]["buid"]
        for row in client.get_history(buid, limit=20):
            for path in client.download_attachments(row, "imo-downloads"):
                print(path)
        # To send a message to this chat:
        # receipt = client.send_message(buid, "Salam!")
```

`QRChallenge.ttl` is in seconds. Treat `QRChallenge.payload` as private. Supported signaling regions are `sgp`, `sjc`, and `fra`. Run `begin_qr_login()` again if the challenge expires or the connection is lost.

## Reading messages and downloading attachments

- `get_contacts()` returns a list of `Head` records and follows contact pagination.
- `get_chats()` returns the current chat index as dictionaries. Pass a chat’s `buid` to `get_history()` or `send_message()`.
- `get_history(buid, limit=50, before=None)` returns one page of server records, newest first. For older messages, pass the last row’s `timestamp_nano_str` as `before`. The page size ranges from 1 to 100.
- `receive_message(timeout=30)` returns the payload of one incoming event. You can pass it directly to `download_attachments()`. A receive timeout raises `IMOTimeoutError` and keeps the connection open.
- `extract_attachments(message)` reads attachment metadata without a network request. It accepts a history row, an incoming event payload, or an `imdata` dictionary and returns `Attachment` objects with `kind`, `filename`, and `size` in bytes when present.
- `download_attachment(attachment, directory, max_bytes=268435456)` returns a `pathlib.Path`. `download_attachments(message, directory, max_bytes=268435456)` returns one path per saved attachment, or an empty list when the message has no supported originals. If a later attachment fails, the earlier files remain in the directory.

Downloads support original documents, photos, videos, audio and voice messages, and GIFs represented as downloadable media. The client selects Nerv, Pixel, or an IMO storage HTTPS URL from the message’s attachment metadata. Downloads are streamed to temporary files. The client removes incomplete files and gives duplicate names a numeric suffix. The default limit is 256 MiB per attachment. Missing, expired, or oversized files raise `IMOAttachmentUnavailable` or `IMOAttachmentTooLarge`. Other transfer failures raise `IMODownloadError`. Signaling failures use `IMOTransportError` or `IMOTimeoutError`, and filesystem errors are raised as `OSError`.

```python
from imo import extract_attachments

# Run inside the authenticated session.
message = client.receive_message(timeout=30)
for attachment in extract_attachments(message):
    print(attachment.kind, attachment.filename, attachment.size)
    print(client.download_attachment(attachment, "incoming", max_bytes=32 * 1024 * 1024))
```

## Sending and ending the session

`send_message(buid, text)` returns a `SentMessage` with `buid`, `message_id`, and `timestamp_nano` when the server replies. Delivery and read receipts occur separately. If sending times out, check the chat before retrying. `logout()` asks IMO to end the current web session. `close()` closes the local connection and clears the in-memory session. The context manager calls `close()`.

## Verification

The real IMO server issued a QR challenge, and the public IMO CDN returned a PNG over the HTTPS download path. Authenticated download flows are covered by simulated responses. The Nerv framing and account hash were compared with the official web bundle’s output using synthetic values. End-to-end downloads of private chat attachments still require a QR-confirmed session. The protocol can change when IMO updates its web client.

```text
python -m pip install -e ".[dev,qr]"
python -m pytest -q tests/test_web_client.py tests/test_attachments.py
```

Set the `IMO_WEB_LIVE` environment variable to `1` to also run the live QR and public CDN checks.
