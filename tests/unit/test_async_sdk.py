import asyncio
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest

from imo import Chat, IMOClient, IMOManager, Message, User, filters
from imo.connection import ConnectionState
from imo.errors import (
    FeatureUnavailableError,
    IMOConnectionError,
    MessageSendError,
    SessionExpired,
    TransportError,
)
from imo.transport import Capability
from imo.types import ChatKind, ContentType, Media


class MockTransport:
    def __init__(self, *feeds: list[Message | Exception], capabilities=frozenset(Capability)):
        self.capabilities = capabilities
        self.feeds = feeds or ([],)
        self.connect_count = 0
        self.disconnect_count = 0
        self.yield_count = 0
        self.closed_streams = 0
        self.failure = None
        self.sent = []

    async def connect(self) -> None:
        self.connect_count += 1
        if self.failure is not None:
            raise self.failure

    async def disconnect(self) -> None:
        self.disconnect_count += 1

    async def get_me(self) -> User:
        return User(None, "Test")

    async def get_contacts(self) -> AsyncGenerator[User, None]:
        yield User("contact-a", "Enem")

    async def get_chats(self) -> AsyncGenerator[Chat, None]:
        yield Chat("chat-a", "Example", ChatKind.PRIVATE)

    async def get_history(self, chat_id: str, *, limit: int | None) -> AsyncGenerator[Message, None]:
        yield Message(chat_id=chat_id, id="source-id", media=(Media(filename="test.bin"),))

    async def send_message(self, chat_id: str, text: str) -> Message:
        self.sent.append((chat_id, None, text))
        return Message(chat_id=chat_id, text=text, is_outgoing=True)

    async def reply(self, chat_id: str, message_id: str, text: str) -> Message:
        self.sent.append((chat_id, message_id, text))
        return Message(chat_id=chat_id, text=text, is_outgoing=True)

    async def download_media(self, media: Media, directory: Path) -> Path:
        return directory / "test.bin"

    async def messages(self) -> AsyncGenerator[Message, None]:
        try:
            for item in self.feeds[self.connect_count - 1]:
                if isinstance(item, Exception):
                    raise item
                self.yield_count += 1
                yield item
        finally:
            self.closed_streams += 1


def message(chat_id="chat-a", message_id="1", **fields):
    return Message(chat_id=chat_id, id=message_id, content_type=ContentType.TEXT,
                   is_outgoing=False, chat_kind=ChatKind.PRIVATE, **fields)


@pytest.mark.asyncio
async def test_default_sdk_has_no_connector():
    client = IMOClient("main")
    assert not client.capabilities and client.state is ConnectionState.DISCONNECTED
    with pytest.raises(FeatureUnavailableError, match="No IMO transport"):
        async with client:
            pytest.fail("the default client must not connect")
    with pytest.raises(FeatureUnavailableError, match="send_text"):
        await client.send_message(chat_id="1", text="Hello")
    with pytest.raises(IMOConnectionError, match="async runner"):
        client.run()
    with pytest.raises(FeatureUnavailableError):
        await Message(chat_id="1").reply("Hi")
    with pytest.raises(FeatureUnavailableError):
        await Message(chat_id="1").download()


@pytest.mark.asyncio
async def test_facade_binds_messages_without_fabricating_fields(tmp_path):
    transport = MockTransport()
    async with IMOClient(transport=transport) as client:
        assert (await client.get_me()).id is None
        assert [user.name async for user in client.get_contacts()] == ["Enem"]
        assert [chat.title async for chat in client.get_chats()] == ["Example"]
        (original,) = [item async for item in client.get_history("chat-a", limit=1)]
        assert original.date is original.sender_id is None
        assert (await original.reply("Reply")).id is None
        assert await original.download(tmp_path) == (tmp_path / "test.bin",)
        assert (await client.send_message(chat_id="chat-a", text="Hi")).text == "Hi"
        with pytest.raises(FeatureUnavailableError, match="stable message ID"):
            await client.reply_to(Message(chat_id="chat-a"), "Hi")
        other = IMOClient("other", transport=MockTransport())
        with pytest.raises(ValueError, match="another IMO client"):
            await other.download_message(original)
    assert transport.sent == [("chat-a", "source-id", "Reply"), ("chat-a", None, "Hi")]
    assert client.state is ConnectionState.DISCONNECTED


@pytest.mark.asyncio
async def test_declared_capabilities_and_error_translation():
    class Incomplete:
        capabilities = frozenset({Capability.ACCOUNT})

        async def connect(self):
            pass

        async def disconnect(self):
            pass

    async with IMOClient(transport=Incomplete()) as client:
        with pytest.raises(TransportError, match="does not implement"):
            await client.get_me()
        with pytest.raises(FeatureUnavailableError, match="reply"):
            await client.reply_to(message(), "Hi")
        with pytest.raises(FeatureUnavailableError, match="download"):
            await client.download_message(message())

    class BrokenSend(MockTransport):
        async def send_message(self, chat_id, text):
            raise RuntimeError("private adapter failure")

    async with IMOClient(transport=BrokenSend()) as client:
        with pytest.raises(MessageSendError, match="Check the chat") as error:
            await client.send_message("chat-a", "Hi")
        assert "private adapter failure" not in str(error.value)


@pytest.mark.asyncio
async def test_filters_and_handler_failure_are_isolated(caplog):
    typed = message(text="Hi")
    unknown = Message(chat_id="chat-a")
    assert (filters.text & filters.private)(typed)
    assert (filters.incoming | filters.outgoing)(typed)
    assert not (filters.incoming | filters.outgoing)(unknown)
    assert (~filters.group)(typed)
    handled = []
    client = IMOClient(transport=MockTransport([typed, unknown]), event_workers=1)

    @client.on_message()
    async def broken(client, message):
        raise ValueError("fixture failure")

    @client.on_message(filters.incoming & filters.text)
    async def handler(client, message):
        handled.append((client.account_id, message.text))

    await client.run_until_disconnected()
    assert handled == [("main", "Hi")]
    assert caplog.messages.count("IMO message handler failed") == 2


@pytest.mark.asyncio
async def test_fifo_per_chat_and_concurrent_shards():
    other = next(str(i) for i in range(100) if hash(str(i)) % 2 != hash("chat-a") % 2)
    first = message(message_id="one")
    same_chat = message(message_id="two")
    parallel = message(chat_id=other, message_id="one")
    transport = MockTransport([first, parallel, same_chat])
    client = IMOClient(transport=transport, event_workers=2, queue_size=1)
    release = asyncio.Event()
    parallel_done = asyncio.Event()
    ordered = []

    @client.on_message()
    async def handler(client, item):
        if item.chat_id == other:
            parallel_done.set()
        else:
            if item.id == "one":
                await release.wait()
            ordered.append(item.id)

    task = asyncio.create_task(client.run_until_disconnected())
    try:
        await asyncio.wait_for(parallel_done.wait(), 2)
        assert ordered == []
    finally:
        release.set()
        await asyncio.wait_for(task, 2)
    assert ordered == ["one", "two"]


@pytest.mark.asyncio
async def test_queue_backpressure_and_cancellation():
    transport = MockTransport([message(message_id=str(i)) for i in range(100)])
    client = IMOClient(transport=transport, event_workers=1, queue_size=1)
    started = asyncio.Event()
    blocked = asyncio.Event()

    @client.on_message()
    async def handler(client, message):
        started.set()
        await blocked.wait()

    task = asyncio.create_task(client.run_until_disconnected())
    try:
        await asyncio.wait_for(started.wait(), 2)
        await asyncio.sleep(0)
        # One handling, one queued, and one held by the producer pending admission.
        assert transport.yield_count == 3
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 2)
    assert transport.closed_streams == transport.disconnect_count == 1
    assert client.state is ConnectionState.DISCONNECTED


@pytest.mark.asyncio
async def test_reconnect_replays_only_missing_or_new_ids():
    first = message(message_id="one")
    without_id = message(message_id=None)
    transport = MockTransport(
        [first, TransportError("temporary loss")],
        [first, message(message_id="two"), without_id, without_id],
    )
    client = IMOClient(transport=transport, reconnect_delay=0, event_workers=1)
    handled = []

    @client.on_message()
    async def handler(client, message):
        handled.append(message.id)

    await client.run_until_disconnected()
    assert handled == ["one", "two", None, None]
    assert transport.connect_count == transport.disconnect_count == transport.closed_streams == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("capabilities,failure", [
    ({Capability.EVENTS}, TransportError("disconnected")),
    (frozenset(Capability), SessionExpired("signed out")),
])
async def test_no_reconnect_without_capability_or_with_expired_session(capabilities, failure):
    transport = MockTransport([failure], capabilities=capabilities)
    with pytest.raises(type(failure)):
        await IMOClient(transport=transport, reconnect_delay=0).run_until_disconnected()
    assert transport.connect_count == transport.disconnect_count == 1


@pytest.mark.asyncio
async def test_explicit_disconnect_does_not_reconnect():
    started = asyncio.Event()
    closed = asyncio.Event()
    finish_close = asyncio.Event()

    class ClosingTransport(MockTransport):
        async def disconnect(self) -> None:
            await super().disconnect()
            closed.set()
            await finish_close.wait()

        async def messages(self) -> AsyncGenerator[Message, None]:
            started.set()
            await closed.wait()
            if closed.is_set():
                raise TransportError("stream closed by request")
            yield message()

    transport = ClosingTransport()
    client = IMOClient(transport=transport, reconnect_delay=0)
    task = asyncio.create_task(client.run_until_disconnected())
    await asyncio.wait_for(started.wait(), 2)
    closing = asyncio.create_task(client.disconnect())
    try:
        await asyncio.wait_for(closed.wait(), 2)
        assert not task.done()
    finally:
        finish_close.set()
        await asyncio.wait_for(asyncio.gather(task, closing), 2)
    assert transport.connect_count == transport.disconnect_count == 1


@pytest.mark.asyncio
async def test_shutdown_deadline_cancels_blocked_handler():
    transport = MockTransport([message()])
    client = IMOClient(transport=transport, shutdown_timeout=0.05, event_workers=1)
    finished = asyncio.Event()

    @client.on_message()
    async def handler(client, message):
        try:
            await asyncio.Future()
        finally:
            finished.set()

    await asyncio.wait_for(client.run_until_disconnected(), 2)
    assert finished.is_set() and transport.disconnect_count == 1


@pytest.mark.asyncio
async def test_manager_isolates_account_failures():
    good = MockTransport([message()])
    bad = MockTransport()
    bad.failure = SessionExpired("signed out")
    manager = IMOManager()
    client = IMOClient("good", transport=good)
    handled = []

    @client.on_message()
    async def handler(client, message):
        handled.append(client.account_id)

    manager.add(client)
    manager.add(IMOClient("bad", transport=bad))
    with pytest.raises(ValueError, match="Duplicate"):
        manager.add(IMOClient("good"))
    with pytest.raises(ValueError, match="own transport"):
        manager.add(IMOClient("reuse", transport=good))
    errors = await manager.run_async()
    assert list(errors) == ["bad"] and isinstance(errors["bad"], SessionExpired)
    assert handled == ["good"]
    assert good.disconnect_count == bad.disconnect_count == 1
