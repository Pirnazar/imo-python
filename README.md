# imo-python

[English](docs/api.md) · [Русский](docs/api.ru.md) · [Türkmençe](docs/api.tk.md)

A typed, async-first Python SDK for building IMO integrations around an explicit transport adapter. The core uses the standard library.

**Version 0.6.0.** The async SDK has no bundled live IMO adapter. Its API and event lifecycle are tested with a fixture adapter. The synchronous Web client, Windows bridge, offline parsers, and reverse-engineering material remain available separately.

## Installation

From a checkout, with Python 3.11 or newer.

```sh
python -m pip install .
```

Install `.[qr]` for the legacy Web client and terminal QR rendering. Use `.[web]` when your code renders the QR itself. On Windows, `.[native]` installs the bridge's optional terminal QR dependency. Building the bridge also requires the locally installed IMO assemblies and .NET Framework.

## Quick Start

`python examples/basic.py` runs today and prints the explicit missing-transport error. `python examples/parse_messages.py` exercises the offline parsers. The other async examples take an adapter supplied by the caller.

```python
from imo import IMOClient
from imo.transport import Transport


async def show_profile(transport: Transport) -> None:
    async with IMOClient("main", transport=transport) as client:
        print(await client.get_me())
```

## Connection

An account name identifies the client locally. Supply an adapter with `IMOClient("main", transport=adapter)` and let `async with` manage its connection, or call `connect()` and `disconnect()` explicitly. `client.capabilities` lists supported operations. The SDK stores no authentication material.

## Messages

`await client.send_message(chat_id="123456", text="Hello!")` returns a `Message` when the adapter supports text sending. `get_history(chat_id, limit=20)` yields messages asynchronously. IDs, sender IDs, timestamps, and direction reflect the fields supplied by the adapter.

`await message.reply("Hello!")` requires reply support and a stable message ID. `await message.download("downloads")` returns a tuple of saved paths when the adapter supports downloads. A missing capability raises `FeatureUnavailableError`. Text sends are never automatically retried.

## Receiving Events

```python
from imo import IMOClient, Message, filters
from imo.transport import Transport


def listen(transport: Transport) -> None:
    client = IMOClient("main", transport=transport)

    @client.on_message(filters.incoming & filters.text)
    async def handle(client: IMOClient, message: Message) -> None:
        print(client.account_id, message.text)

    client.run()
```

From an existing event loop use `await client.run_until_disconnected()`. The dispatcher preserves arrival order within each chat, limits queued events, and logs handler failures independently. Reconnect is opt-in. Replay suppression uses stable message IDs and a bounded cache.

## Contacts & Chats

With an adapter that supports these operations, iterate `client.get_contacts()` for `User` records or `client.get_chats()` for `Chat` records. A chat has an `id`, an optional `title`, and an optional `kind`.

## Multiple Accounts

Register each client with `IMOManager.add(client)` and supply a separate adapter instance per account. Use `manager.run()` from synchronous code or `await manager.run_async()` in an existing event loop. Failures are logged and returned by account ID when the listeners finish. Isolation is verified with fixture adapters. Concurrent live IMO sessions still need validation.

## Error Handling

Catch `IMOError` from `imo.errors` for SDK failures. `FeatureUnavailableError` indicates a missing adapter or operation. `AuthenticationRequired` and `SessionExpired` indicate an authorization requirement. `IMOConnectionError`, `TransportError`, `ChatNotFound`, and `MessageSendError` distinguish connection, adapter, lookup, and sending failures.

## Current Limitations

- The async facade requires a caller-supplied adapter and cannot authenticate against IMO on its own.
- The [legacy Web client](docs/web_client.en.md) uses `imo.legacy.IMOClient`. Its QR challenge and public CDN access were tested against IMO. Account operations and file uploads still need independent end-to-end verification.
- The [Windows bridge](docs/desktop_bridge.md) uses `imo.desktop.IMOClient` and a separate x86 executable. It is retained for research and compatibility.
- The [offline models](docs/data_models.md), `imo.models.parse_imdata`, and `imo.localdb.LocalDB` remain available.

## Development

```sh
python -m pip install -e ".[dev]"
python -m pytest
python -m ruff check .
python -m mypy
python -m build
python -m twine check --strict dist/imo_python-0.6.0-py3-none-any.whl dist/imo_python-0.6.0.tar.gz
```

Default tests use fixtures and local data. Windows and network research tests are opt-in. [Public API](docs/api.md) · [Architecture and capabilities](docs/architecture.md) · [Reverse-engineering index](docs/research_index.md)
