# SDK architecture

The async facade depends on structural interfaces in `imo.transport`. Wire data stays in adapters. An adapter constructs SDK models and preserves unknown fields as `None`. It supplies stable message IDs when the source provides them. The async core does not import the Web implementation, the Windows bridge, or SQLite.

## Capability matrix

| Operation | Async facade contract | Legacy Web client | Windows bridge | Offline reader |
| --- | --- | --- | --- | --- |
| Connect | Explicit `Transport` required | Separate QR flow | Separate x86 process and QR flow | — |
| Account and contacts | `ACCOUNT`, `CONTACTS` | Implemented | Implemented | — |
| Chat list | `CHATS` | Implemented | Implemented | SQLite snapshot |
| History | `HISTORY` | Implemented | — | — |
| Send text | `SEND_TEXT` | Implemented | Implemented | — |
| Reply to a message ID | `REPLY` | — | — | — |
| Incoming events | `EVENTS` | Implemented | Implemented | — |
| Download media | `DOWNLOAD` | Implemented | — | — |
| Upload media | Outside the current facade | Implemented | — | — |
| Reconnect | `RECONNECT` | Fresh QR flow | Bridge-managed connection | — |

The async column describes extension points tested with a fixture adapter. Legacy implementations run independently and do not implement the async adapter contract. See the [Web guide](web_client.en.md), [Windows bridge guide](desktop_bridge.md), and [research index](research_index.md) for their test coverage.

## Adapter contracts

An adapter implements async `connect()` and `disconnect()`, declares a stable set of capabilities, and implements the corresponding protocols. It should use `TransportError` for recoverable stream failures, `AuthenticationRequired` for missing authorization, and `SessionExpired` for a session that needs fresh authorization. Unexpected adapter exceptions surface as SDK errors without internal error text.

An event source returns an async generator of `Message`. Clean EOF finishes the listener. `TransportError` triggers up to `reconnect_attempts` reconnects per listener if the adapter declares `RECONNECT`. Reconnect closes and reopens the account adapter, then subscribes again. It does not retry sends or handle authorization challenges. Adapter I/O and cleanup should be nonblocking and cancellation-cooperative.

## Dispatch and shutdown

Each account gets `event_workers` workers with `queue_size` slots each. Chat IDs route to stable worker slots within a listener. Each worker processes its queue in arrival order. Chats on different slots can run concurrently. A full queue applies backpressure to the stream reader. Adapters that buffer data enforce their own bounds.

Deduplication uses `(chat_id, message.id)` for the most recent `dedup_size` distinct IDs accepted by a listener. The cache survives reconnect within that listener. Messages without stable IDs are dispatched on every receipt. Old IDs can be evicted and restarting the listener starts a new cache.

EOF drains queued work for up to `shutdown_timeout`, then requests cancellation of remaining workers. Explicit disconnect suppresses reconnect. Adapter disconnect should unblock pending event reads. Cancelling the listener closes the event generator and cancels the workers. An owning context closes the adapter. Async handlers should await I/O and offload blocking work with `asyncio.to_thread`.

## Refactoring baseline

The pre-refactor suite recorded 82 passes and seven skips for opt-in tests. The synchronous Web implementation already contained QR signaling, contact and chat operations, history, text sending, events, and file transfers. The Windows wrapper and x86 harness covered desktop research. The new SDK leaves the previous protocol implementation, parsers, regression tests, and collected evidence in compatibility or research layers.
