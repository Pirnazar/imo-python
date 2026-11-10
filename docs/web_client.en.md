# IMO Web client

[English](web_client.en.md) · [Русский](web_client.md) · [Türkmençe](web_client.tk.md) · [Examples](../examples/README.md) · [API reference](api.md)

`imo.IMOClient` is the synchronous client for the reverse-engineered IMO Web protocol in `imo-python 0.7.0`. It opens a separate session that you confirm in the official IMO mobile app. The package requires Python 3.11+. The session stays in memory. Use one thread per client instance. [Official IMO Web](https://web.imo.im/) · [IMO QR login help](https://imo.im/faq/More-Ways-to-Login)

## Installation and QR login

From the project directory, install the library and run the interactive example.

```text
python -m pip install -e ".[qr]"
python examples/web_qr.py --download-dir imo-downloads
```

Scan the QR with your phone and confirm the login in IMO. In the example, `chats` lists conversation IDs, `history BUID` reads the latest page, `download BUID 20` saves attachments from the latest 20 messages, and `members BUID` lists group members. `BUID` is the conversation ID returned by IMO.

If the terminal QR is hard to scan, run [qr_to_file.py](../examples/qr_to_file.py) and open the local SVG in a browser. For a script you can run offline, try [inspect_attachments.py](../examples/inspect_attachments.py). Each account script opens a fresh session. Use the interactive example to combine operations after one scan.

```python
from imo import IMOClient

with IMOClient(region="sgp", timeout=15) as client:
    client.connect()
    profile = client.get_me()
    contacts = client.get_contacts()
    chats = client.list_chats()

    if chats:
        chat = chats[0]
        for message in client.iter_history(chat.buid, max_messages=20):
            for path in client.download_attachments(message, "imo-downloads"):
                print(path)
        # To send a message to this chat:
        # receipt = client.send_message(chat, "Salam!")
```

`connect()` renders a terminal QR with the `qr` extra. To render it yourself, pass `connect(show_qr=callback)`. The callback receives a `QRChallenge`. For separate steps, use `begin_qr_login()` and `wait_for_login()`. `QRChallenge.ttl` is in seconds. Treat `QRChallenge.payload` as private. Supported signaling regions are `sgp`, `sjc`, and `fra`. Call `connect()` again if the challenge expires or the connection is lost.

## Reading messages and downloading attachments

- `get_contacts()` returns a list of `Head` records and follows contact pagination.
- `get_chats()` returns the current chat index as dictionaries. Pass a chat’s `buid` to `get_history()` or `send_message()`.
- `list_chats()` returns `Chat` objects with `buid`, `is_group`, `changed_at_nano`, and an optional `last_message`. `get_group_members(chat)` accepts a group `Chat` or its BUID and returns `GroupMember` records.
- `get_history(buid, limit=50, before=None)` returns one page of server records, newest first. For older messages, pass the last row’s `timestamp_nano_str` as `before`. The page size ranges from 1 to 100.
- `iter_history(buid, page_size=50, before=None, max_messages=None)` follows pages lazily and suppresses repeated boundary rows. It yields `WebMessage` objects with text, author, timestamp, attachment metadata, and the original `raw` record. A cursor that cannot advance raises `IMORequestError`.
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

```python
client.send_message(id="BUID_FROM_CONTACTS", text="Salam!")
client.send_message(name="Enem", text="Salam!")
client.send_message(name="Enem", media="photo.jpg")
file_receipt, text_receipt = client.send_message(name="Enem", text="Salam!", media="photo.jpg")
```

Pass exactly one recipient. `id` is a conversation ID. `name` searches the contact's note, alias, or display name for one exact match, ignoring case and extra whitespace. A missing or ambiguous name raises `IMOContactNotFound`. The positional form `send_message(buid, text)` also accepts a `Head` or a `Chat` as the recipient.

`media` takes the path to one nonempty local file up to 256 MiB. IMO receives it as a file attachment. Text and file each return a `SentMessage` with `buid`, `message_id`, and `timestamp_nano` after server confirmation. Providing both sends the file first and returns `(file_receipt, text_receipt)`. If the file is confirmed and the text fails, `IMOPartialSendError.attachment` contains the file receipt. The upload was verified against the official web encoder and a simulated server. A real account upload remains unverified.

Delivery and read receipts occur separately. If sending times out, check the chat before retrying. `logout()` asks IMO to end the current web session. `close()` closes the local connection and clears the in-memory session. The context manager calls `close()`.

## Sending by name and in batches

`find_contact(name)` returns the contact's `Head`, ignoring case and repeated spaces. An exact match on the note, alias, or display name wins; otherwise the name must be part of exactly one contact's names. `IMOContactNotFound` is raised when no contact, or more than one, matches. Pass `contacts=` from `get_contacts()` to avoid fetching the list again.

`send_many(messages, delay=8.0, jitter=0.3, by_name=False, stop_on_error=False)` sends `(target, text)` pairs in order and returns a list of `SendResult` with `target`, `text`, `sent`, `error`, and an `ok` property. A target is a BUID, a `Head`, or a `Chat`; with `by_name=True` strings are contact names and the contact list is fetched once. Between messages the client waits `delay` seconds, varied by up to `jitter` (±30% by default), and keeps acknowledging incoming events, so messages that arrive during a pause remain available to `receive_message()`.

```python
client.send_message(client.find_contact("Mom"), "Salam!")

rows = [("Mom", "I'll be home by 7"), ("Father", "Call me back")]
for result in client.send_many(rows, delay=8, by_name=True):
    print(result.target, "ok" if result.ok else result.error)
```

The client validates row structure and text before sending. If a send request times out, the session closes and the failed row records the error. If the connection breaks during a pause, the call can raise directly. For a CSV preview and exact contact matching before the first send, use [send_batch.py](../examples/send_batch.py).

## Listening for messages

```python
from imo import IMOClient

with IMOClient() as client:
    client.connect()

    @client.on_message
    def handle(message):
        print(message.buid, message.text)
        for path in client.download_attachments(message, "incoming"):
            print(path)

    client.run()
```

`run()` calls handlers in registration order on the calling thread. During waits, the client sends an IMO Web keepalive after three minutes without signaling traffic. The loop continues after idle timeouts and raises on disconnection or handler errors. Call `stop()` from a handler to return after the current message while keeping the session open. Use `remove_message_handler(handle)` to remove a handler.

## Verification

The real IMO server issued a QR challenge, and the public IMO CDN returned a PNG over the HTTPS download path. Group rosters, history pagination, callbacks, and authenticated downloads were tested against simulated responses. The Nerv framing and account hash were compared with the official web bundle’s output using synthetic values. End-to-end account operations still require a QR-confirmed session. The protocol can change when IMO updates its web client.

```text
python -m pip install -e ".[dev,qr]"
python -m pytest -q
```

Set the `IMO_WEB_LIVE` environment variable to `1` to also run the live QR and public CDN checks.

See [troubleshooting](troubleshooting.md) for expired QR codes, ambiguous names, and incomplete sends.
