"""Template for an adapter that reads history and downloads media."""

from pathlib import Path

from imo import IMOClient
from imo.transport import Transport


async def download_latest(transport: Transport, chat_id: str, directory: Path) -> None:
    async with IMOClient("main", transport=transport) as client:
        async for message in client.get_history(chat_id, limit=20):
            if message.media:
                for path in await message.download(directory):
                    print(path)
