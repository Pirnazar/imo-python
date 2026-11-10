"""Connection lifecycle shared by the facade and event runner."""

import asyncio
from collections.abc import Callable, Coroutine, Iterator
from contextlib import contextmanager, suppress
from enum import StrEnum
from typing import Any, TypeVar

from .errors import FeatureUnavailableError, IMOConnectionError, IMOError, TransportError
from .transport import Transport

_Result = TypeVar("_Result")


def run_sync(main: Callable[[], Coroutine[Any, Any, _Result]]) -> _Result:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(main())
    raise IMOConnectionError("run() requires a synchronous caller; use the async runner")


class ConnectionState(StrEnum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DISCONNECTING = "disconnecting"


@contextmanager
def transport_errors(operation: str, error_type: type[IMOError] = TransportError) -> Iterator[None]:
    try:
        yield
    except IMOError:
        raise
    except Exception:
        raise error_type(f"IMO adapter could not {operation}") from None


class Connection:
    def __init__(self, transport: Transport | None):
        self.transport = transport
        self.state = ConnectionState.DISCONNECTED
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        async with self._lock:
            if self.state is ConnectionState.CONNECTED:
                return
            if self.transport is None:
                raise FeatureUnavailableError("No IMO transport is configured for this client")
            self.state = ConnectionState.CONNECTING
            try:
                with transport_errors("connect"):
                    await self.transport.connect()
            except BaseException:
                try:
                    with suppress(Exception):
                        await self.transport.disconnect()
                finally:
                    self.state = ConnectionState.DISCONNECTED
                raise
            self.state = ConnectionState.CONNECTED

    async def disconnect(self) -> None:
        async with self._lock:
            if self.state is ConnectionState.DISCONNECTED or self.transport is None:
                return
            self.state = ConnectionState.DISCONNECTING
            try:
                with transport_errors("disconnect"):
                    await self.transport.disconnect()
            finally:
                self.state = ConnectionState.DISCONNECTED
