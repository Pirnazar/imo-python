# imo-python 0.6.0 asinhron API

[English](api.md) · [Русский](api.ru.md) · [Türkmençe](api.tk.md)

`imo` tipleri kesgitlenen modelleri, habar işleýjilerini we her hasap üçin aýratyn ýagdaýy bolan asinhron SDK-dyr. Tor amallary üçin `transport=` arkaly adapter beriň. Asinhron SDK-nyň düzüminde hakyky IMO serwerine birikýän taýýar adapter entek ýok. Adapter berilmese, `connect()` usuly `FeatureUnavailableError` ýalňyşlygyny berýär.

## Gurnamak we ilkinji işlediş

Python 3.11 ýa-da has täze wersiýa gerek. Bu buýruklary taslamanyň esasy bukjasynda işlediň.

```sh
python -m pip install .
python examples/basic.py
python examples/parse_messages.py
```

Birinji mysal adapter bolmadyk ýagdaýy görkezýär. Ikinjisi ýerli habar nusgalaryny seljerýär. Aşakdaky mysal `ACCOUNT` we `CHATS` mümkinçilikleri bolan sazlanan adapteri talap edýär.

```python
from imo import IMOClient
from imo.transport import Transport


async def show_account(transport: Transport) -> None:
    async with IMOClient("main", transport=transport) as client:
        print(await client.get_me())
        async for chat in client.get_chats():
            print(chat.id, chat.title)
```

## Habarlar we wakalar

- Adapter `SEND_TEXT` mümkinçiligini goldaýan bolsa, `await client.send_message(chat_id, text)` tekst iberýär we `Message` gaýtarýar.
- `client.get_contacts()`, `client.get_chats()` we `client.get_history(chat_id, limit=20)` netijelerini `async for` bilen okaň.
- `message.id`, `sender_id`, `text`, `date`, `is_outgoing` we `chat_kind` meýdanlary `None` bolup biler. Bu bahalary maglumat çeşmesi berýär.
- `await message.reply(text)` baglanyşykly müşderi arkaly jogap iberýär we habaryň durnukly ID-sini talap edýär. `await message.download(directory)` faýl ýollarynyň týuplini gaýtarýar. Bu amallar üçin degişlilikde `REPLY` we `DOWNLOAD` mümkinçilikleri gerek.

Asinhron işleýjileri `@client.on_message(filters.incoming & filters.text)` arkaly hasaba alyň. Süzgüçleri `&`, `|` we `~` bilen birleşdirip bolýar. Her çatdaky habarlaryň geliş tertibi saklanýar. Sinhron kodda `client.run()`, işleýän waka siklinde bolsa `await client.run_until_disconnected()` ulanyň. [Habar işleýjisiniň mysaly](../examples/incoming.py) · [Wakalaryň tertibi we gaýtadan birikmek](architecture.md)

## Birnäçe hasap we ýalňyşlyklar

Her hasaba başga at we aýratyn adapter berip, müşderileri `IMOManager.add(client)` arkaly hasaba alyň. Diňleýjiler tamamlananda, `await manager.run_async()` ýalňyşlyklary hasap atlary boýunça gaýtarýar. Hasaplaryň aýratyn işleýşi synag adapterleri bilen barlandy. Bir wagtda birnäçe hakyky IMO sessiýasyny ulanmak entek barlanmaly.

Ýalňyşlyklaryň esasy klasy `imo.errors` modulyndaky `IMOError`. `FeatureUnavailableError` adapteriň ýa-da mümkinçiligiň ýokdugyny aňladýar. `AuthenticationRequired` we `SessionExpired` hasaby tassyklamagyň zerurdygyny görkezýär. Iberiş tassyklanmasa, täzeden ibermezden öň çaty barlaň.

## Sinhron müşderi we barlaglar

QR kod bilen giriş we kontaktyň ady boýunça iberiş üçin `from imo.legacy import IMOClient` we `.[qr]` goşundysyny ulanyň. Windows köprüsi `imo.desktop`, ýerli maglumatlar bolsa `imo.models` we `imo.localdb` arkaly elýeterli. [Sinhron IMO Web](web_client.tk.md) · [Windows köprüsi](desktop_bridge.md) · [Barlaglar](research_index.md)
