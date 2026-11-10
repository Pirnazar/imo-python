# Public async API

[English](api.md) · [Русский](api.ru.md) · [Türkmençe](api.tk.md)

`from imo import IMOClient, IMOManager, Message, Chat, User, filters` imports the async SDK. Additional types live in `imo.types`, exceptions in `imo.errors`, and adapter contracts in `imo.transport`.

## Client

| Operation | Result |
| --- | --- |
| `IMOClient(account_id="main", transport=adapter)` | A client with independent state and handlers |
| `await connect()` / `await disconnect()` | Open or close the configured adapter |
| `await get_me()` | `User` |
| `get_contacts()` / `get_chats()` | Async iterators of `User` and `Chat` |
| `get_history(chat_id, limit=None)` | Async iterator of `Message` |
| `await send_message(chat_id, text)` | `Message` from the text sender |
| `await reply_to(message, text)` | `Message` from the reply sender |
| `await download_media(media, directory=".")` | Saved `Path` |
| `await download_message(message, directory=".")` | Tuple of paths in attachment order |
| `@on_message(predicate=None)` | Register an async `(client, message)` handler |
| `await listen()` | Consume events on an open connection |
| `await run_until_disconnected()` | Listen and close the connection if this call opened it |
| `run()` | Synchronous entry point for the async runner |

Capability checks precede adapter calls. Without an adapter, `connect()` raises `FeatureUnavailableError`. An `async with` block closes its connection on exit.

## Messages and filters

A `Message` has a required `chat_id` for routing. `id`, `sender_id`, `text`, `date`, `is_outgoing`, and `chat_kind` may be absent. `content_type` defaults to `ContentType.UNKNOWN`. `media` is a tuple of `Media` records.

Messages produced by a client can call `await message.reply(text)` or `await message.download(directory)`. Reply requires a stable message ID and an adapter that supports replying. Download uses the bound client's media capability. An unbound message or unsupported operation raises `FeatureUnavailableError`.

Use `&`, `|` and `~` to combine the predicates in `imo.filters`. Unknown direction matches neither direction filter. Unknown chat kind matches neither `private` nor `group`. Negation applies to the predicate result, so `~filters.group` also matches an unknown chat kind.

## Accounts and migration

`IMOManager.run_async()` returns account failures after all its listeners finish. Use `run()` when no event loop is running. Duplicate account IDs and shared adapter instances are rejected.

Existing synchronous code can switch its imports to `imo.legacy`. The Windows bridge remains in `imo.desktop`. Offline parsing and SQLite reading remain in `imo.models` and `imo.localdb`. The public `imo.Message` is the async SDK model. The historical offline model is `imo.models.Message`.

To keep using QR login and exact contact-name matching in existing scripts, install `.[qr]` and use the synchronous Web client. [Legacy Web guide](web_client.en.md)

```python
from imo.legacy import IMOClient

with IMOClient() as client:
    client.connect()
    client.send_message(name="Enem", text="Salam!")
```
