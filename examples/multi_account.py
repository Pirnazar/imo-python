"""Template for independent adapters for two accounts."""

from imo import IMOClient, IMOManager
from imo.transport import Transport


def run(first: Transport, second: Transport) -> dict[str, Exception]:
    manager = IMOManager()
    manager.add(IMOClient("account_1", transport=first))
    manager.add(IMOClient("account_2", transport=second))
    return manager.run()
