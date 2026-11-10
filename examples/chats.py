"""Template for an adapter that lists chats."""

from imo import IMOClient
from imo.transport import Transport


async def list_chats(transport: Transport) -> None:
    async with IMOClient("main", transport=transport) as client:
        async for chat in client.get_chats():
            print(chat.id, chat.title)
