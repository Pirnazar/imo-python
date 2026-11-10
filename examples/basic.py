"""Runnable offline example showing the SDK's behavior without an adapter."""

import asyncio

from imo import IMOClient
from imo.errors import FeatureUnavailableError


async def main() -> None:
    try:
        async with IMOClient("main") as client:
            print(await client.get_me())
    except FeatureUnavailableError as error:
        print(error)


if __name__ == "__main__":
    asyncio.run(main())
