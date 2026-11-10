"""Template for an adapter that provides events and replies."""

from imo import IMOClient, Message, filters
from imo.transport import Transport


def run(transport: Transport) -> None:
    client = IMOClient("main", transport=transport)

    @client.on_message(filters.incoming & filters.text)
    async def handle(client: IMOClient, message: Message) -> None:
        print(client.account_id, message.text)
        await message.reply("Hello!")

    client.run()
