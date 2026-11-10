# IMO Web API reference

[English guide](web_client.en.md) · [Русское руководство](web_client.md) · [Türkmençe gollanma](web_client.tk.md) · [Examples](../examples/README.md)

Import `IMOClient`, its models, and errors from `imo`. Methods are synchronous. Use one thread per client instance and call `connect()` before account operations.

## Session

| Method or property | Result |
| --- | --- |
| `IMOClient(region="sgp", timeout=15.0, language="en")` | An unauthenticated client. `region` also accepts `sjc` and `fra`. The constructor's timeout controls individual signaling operations and file-server waits. |
| `connect(show_qr=None, timeout=None)` | Open a fresh QR session unless the client is already authenticated. The callback receives a `QRChallenge`. The optional timeout limits the wait for confirmation. |
| `begin_qr_login()` | Start a new session and return a `QRChallenge` with a private `payload` and a `ttl` in seconds. |
| `wait_for_login(timeout=None)` | Wait for phone confirmation of the current challenge. |
| `is_authenticated` | Whether the client holds a confirmed session in memory. |
| `get_me()` | Profile dictionary with `uid` and any available fields such as `alias` and `imo_id`. |
| `close()` | Close the local connection and clear the in-memory session. Context-manager exit calls this method. |
| `logout()` | Request server-side logout and close the connection once confirmed. |

## Contacts, chats, and history

| Method | Result |
| --- | --- |
| `get_contacts()` | List of `Head` contacts, following server pagination. |
| `find_contact(name, contacts=None, exact=False)` | One matching `Head`. Pass an existing contact list to reuse it. |
| `get_chats()` | List of chat-index dictionaries. |
| `list_chats()` | List of typed `Chat` records. |
| `get_group_members(buid)` | List of visible `GroupMember` records. Accepts a group BUID or a group `Chat`. |
| `get_history(buid, limit=50, before=None)` | One page of raw message dictionaries, newest first. Page size is 1 to 100. |
| `iter_history(buid, page_size=50, before=None, max_messages=None)` | Lazy iterator of `WebMessage`, newest first. Accepts a BUID, `Head`, or `Chat`. |

A BUID identifies a conversation. Copy it from a contact or chat rather than deriving it from a phone number. Group chat BUIDs end in `;`. History cursors are decimal nanosecond timestamp strings. When paging manually, use the oldest row's `timestamp_nano_str` as `before` and account for overlapping rows. The iterator handles repeated boundary rows and raises if a full page cannot advance.

`find_contact` matches case and whitespace-normalized aliases, display names, and notes. By default it can fall back to one partial match when there is no exact match. Pass `exact=True` to require an exact match. `send_message(name=...)` always requires one exact match.

## Sending

| Method | Result |
| --- | --- |
| `send_message(buid=None, text=None, *, id=None, name=None, media=None)` | A `SentMessage` for text or file. When both are supplied, returns `(file_receipt, text_receipt)`. |
| `send_many(messages, delay=8.0, jitter=0.3, by_name=False, stop_on_error=False)` | A list of `SendResult` records for the attempted text messages. |

Supply one of `buid`, `id`, and `name`. `buid` can also be a `Head` or `Chat`. A local `media` path must point to one nonempty file up to 256 MiB. With both file and text, the client waits for the file receipt before sending the text. `SentMessage` contains `buid`, `message_id`, and `timestamp_nano`. A receipt confirms the server response. Delivery and reading occur separately.

`send_many` accepts `(target, text)` pairs. With `by_name=True`, it applies the default `find_contact` rules to strings. For exact matching in a batch, resolve each name with `find_contact(..., exact=True)` first and pass the resulting contacts. `SendResult` exposes `target`, `text`, `sent`, `error`, and `ok`. Inspect results before retrying any failed row.

## Incoming messages and media

| Method | Result |
| --- | --- |
| `receive_message(timeout=None)` | One raw incoming message. An idle timeout raises `IMOTimeoutError` and preserves the connection. |
| `on_message(handler)` | Register a synchronous callback receiving `WebMessage`. Also usable as `@client.on_message`. |
| `remove_message_handler(handler)` | Unregister a callback. |
| `run(poll_timeout=None)` | Wait for events and call handlers in registration order. An idle timeout continues the loop. |
| `stop()` | Stop the loop after the current message. The session stays open. |
| `extract_attachments(record)` | Read `Attachment` metadata from a raw row or `imdata` mapping offline. |
| `download_attachment(attachment, directory, max_bytes=268435456)` | Save one attachment and return its `Path`. |
| `download_attachments(message, directory, max_bytes=268435456)` | Save supported attachments from a raw row or `WebMessage` and return their paths. |

`WebMessage` exposes `buid`, `text`, `timestamp_nano`, `message_id`, `author`, `kind`, `is_sent`, `attachments`, and `raw`. Attachment metadata includes `kind`, `filename`, and `size` when available. Downloads stream to temporary files and preserve existing files by adding a suffix on collisions.

## Errors

| Error | Meaning |
| --- | --- |
| `IMOLoginError` | QR login is incomplete, cancelled, rejected, or the session ended. |
| `IMOContactNotFound` | The name is missing or ambiguous. |
| `IMOTimeoutError` | The operation deadline expired. |
| `IMOTransportError` | A signaling connection failed, disconnected, or returned an invalid frame. |
| `IMORequestError` | The server rejected a command or its result could not be verified. |
| `IMOUploadError` | Upload could not be completed or confirmed. |
| `IMOPartialSendError` | File was confirmed and the following text was unconfirmed. The file receipt is available as `error.attachment`. |
| `IMODownloadError` | A file could not be downloaded or verified. Its subtypes `IMOAttachmentUnavailable` and `IMOAttachmentTooLarge` distinguish missing or expired media from size limits. |

These errors inherit `IMOError`. Invalid arguments can also raise `ValueError` or `TypeError`, and filesystem errors can raise `OSError`. See [troubleshooting](troubleshooting.md) for recovery steps.
