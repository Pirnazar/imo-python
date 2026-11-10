"""Bounded asynchronous dispatch with chat ordering and replay protection."""

from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Sequence
from types import TracebackType
from typing import TYPE_CHECKING, Self

from .filters import Filter
from .types import Message

if TYPE_CHECKING:
    from .client import IMOClient

logger = logging.getLogger(__name__)
MessageHandler = Callable[["IMOClient", Message], Awaitable[None]]
Registration = tuple[Filter | None, MessageHandler]


class EventDispatcher:
    def __init__(
        self,
        client: IMOClient,
        handlers: Sequence[Registration],
        *,
        workers: int,
        queue_size: int,
        dedup_size: int,
        shutdown_timeout: float,
    ) -> None:
        self._client = client
        self._handlers = handlers
        self._queues = [asyncio.Queue[Message](queue_size) for _ in range(workers)]
        self._workers: list[asyncio.Task[None]] = []
        self._seen: OrderedDict[tuple[str, str], None] = OrderedDict()
        self._dedup_size = dedup_size
        self._shutdown_timeout = shutdown_timeout

    async def __aenter__(self) -> Self:
        self._workers = [asyncio.create_task(self._consume(queue)) for queue in self._queues]
        return self

    async def submit(self, message: Message) -> None:
        # The client is the sole producer. Record the ID only after admission.
        key = (message.chat_id, message.id) if message.id else None
        if key is not None and key in self._seen:
            return
        queue = self._queues[hash(message.chat_id) % len(self._queues)]
        await queue.put(message)
        if key is not None and self._dedup_size:
            self._seen[key] = None
            if len(self._seen) > self._dedup_size:
                self._seen.popitem(last=False)

    async def _consume(self, queue: asyncio.Queue[Message]) -> None:
        while True:
            message = await queue.get()
            try:
                for predicate, handler in tuple(self._handlers):
                    try:
                        if predicate is None or predicate(message):
                            await handler(self._client, message)
                    except asyncio.CancelledError:
                        task = asyncio.current_task()
                        if task is not None and task.cancelling():
                            raise
                        logger.warning("IMO message handler raised CancelledError")
                    except Exception:
                        logger.exception("IMO message handler failed")
            finally:
                queue.task_done()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        try:
            if not isinstance(exc, (asyncio.CancelledError, KeyboardInterrupt, SystemExit)):
                try:
                    async with asyncio.timeout(self._shutdown_timeout):
                        await asyncio.gather(*(queue.join() for queue in self._queues))
                except TimeoutError:
                    logger.warning("IMO event shutdown timed out; cancelling pending handlers")
        finally:
            for worker in self._workers:
                worker.cancel()
            await asyncio.gather(*self._workers, return_exceptions=True)
