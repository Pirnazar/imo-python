"""Run independent account listeners together."""

import asyncio
import logging

from .client import IMOClient
from .connection import run_sync

logger = logging.getLogger(__name__)


class IMOManager:
    """Manage named clients. One account failure leaves the others running."""

    def __init__(self) -> None:
        self._clients: dict[str, IMOClient] = {}

    def add(self, client: IMOClient) -> None:
        if client.account_id in self._clients:
            raise ValueError(f"Duplicate IMO account ID: {client.account_id!r}")
        transport = client._connection.transport
        if transport is not None and any(c._connection.transport is transport for c in self._clients.values()):
            raise ValueError("Each IMO account requires its own transport instance")
        self._clients[client.account_id] = client

    async def run_async(self) -> dict[str, Exception]:
        """Run all clients and return failures by account ID once the listeners finish."""
        failures: dict[str, Exception] = {}

        async def run_account(client: IMOClient) -> None:
            try:
                await client.run_until_disconnected()
            except Exception as error:
                failures[client.account_id] = error
                logger.error("IMO account %s stopped with %s", client.account_id, type(error).__name__)

        async with asyncio.TaskGroup() as tasks:
            for client in self._clients.values():
                tasks.create_task(run_account(client))
        return failures

    def run(self) -> dict[str, Exception]:
        """Run all clients from synchronous code."""
        return run_sync(self.run_async)
