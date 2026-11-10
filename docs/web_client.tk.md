# IMO Web müşderisi

[English](web_client.en.md) · [Русский](web_client.md) · [Türkmençe](web_client.tk.md) · [Mysallar](../examples/README.md) · [API maglumatnamasy](api.md)

`imo.IMOClient` — `imo-python 0.7.0` paketindäki sinhron IMO Web müşderisi. Ol aýratyn sessiýa açýar, siz bolsa ony resmi IMO mobil programmasynda tassyklaýarsyňyz. Python 3.11 ýa-da has täze wersiýa gerek. Sessiýa programmanyň ýadynda saklanýar. Her müşderi nusgasyny bir akymda ulanyň. [Resmi IMO Web](https://web.imo.im/) · [QR kod bilen giriş boýunça IMO gollanmasy](https://imo.im/faq/More-Ways-to-Login)

## Gurnamak we QR kod bilen girmek

Taslamanyň bukjasyndan kitaphanany guruň we interaktiw mysaly işlediň.

```text
python -m pip install -e ".[qr]"
python examples/web_qr.py --download-dir imo-downloads
```

QR kody telefonda skanirläň we IMO-da girişi tassyklaň. Mysalda `chats` çatlaryň identifikatorlaryny görkezýär, `history BUID` taryhyň iň soňky sahypasyny okaýar, `download BUID 20` soňky 20 habaryň goşundylaryny göçürýär, `members BUID` bolsa toparyň agzalaryny görkezýär. `BUID` — IMO-nyň gaýtarýan çat identifikatory.

Terminaldaky QR kody skanirlemek kyn bolsa, [qr_to_file.py](../examples/qr_to_file.py) skriptini işlediň we ýerli SVG faýlyny brauzerde açyň. Hasaba girmän [inspect_attachments.py](../examples/inspect_attachments.py) mysalyny işledip bolýar. Tor bilen işleýän her skript täze sessiýa açýar. Bir gezek skanirläp birnäçe amal ýerine ýetirmek üçin interaktiw mysaly ulanyň.

```python
from imo import IMOClient

with IMOClient(region="sgp", timeout=15) as client:
    client.connect()
    profile = client.get_me()
    contacts = client.get_contacts()
    chats = client.list_chats()

    if chats:
        chat = chats[0]
        for message in client.iter_history(chat.buid, max_messages=20):
            for path in client.download_attachments(message, "imo-downloads"):
                print(path)
        # Şu çata habar ibermek
        # receipt = client.send_message(chat, "Salam!")
```

`connect()` `qr` goşundysynyň kömegi bilen QR kody terminalda görkezýär. Kody başga usul bilen görkezmek üçin `connect(show_qr=callback)` çagyryň. Funksiýa `QRChallenge` obýektini alýar. Girişi `begin_qr_login()` we `wait_for_login()` bilen iki ädimde hem ýerine ýetirip bolýar. `QRChallenge.ttl` kodyň näçe sekunt güýjünde bolýandygyny görkezýär. `QRChallenge.payload` bahasyny gizlin saklaň. Signal birikmesi üçin `sgp`, `sjc` we `fra` sebitleri elýeterli. Kodyň möhleti gutarsa ýa-da birikme üzülse, `connect()` usulyny gaýtadan çagyryň.

## Çat taryhy, gelýän habarlar we goşundylar

- `get_contacts()` `Head` ýazgylarynyň sanawyny gaýtarýar we kontaktlaryň ähli sahypalaryny awtomatik okaýar.
- `get_chats()` çatlaryň sanawyny Python sözlükleri görnüşinde gaýtarýar. Çat ýazgysyndaky `buid` bahasyny `get_history()` ýa-da `send_message()` usulyna beriň.
- `list_chats()` `buid`, `is_group`, `changed_at_nano` we bar bolsa `last_message` meýdanlary bolan `Chat` obýektlerini gaýtarýar. `get_group_members(chat)` toparyň `Chat` obýektini ýa-da BUID-sini kabul edýär we `GroupMember` ýazgylaryny gaýtarýar.
- `get_history(buid, limit=50, before=None)` serwerdäki ýazgylaryň bir sahypasyny iň täze habarlardan başlap gaýtarýar. Has köne habarlary almak üçin soňky ýazgynyň `timestamp_nano_str` bahasyny `before` parametrine beriň. Bir sahypada 1-den 100-e çenli ýazgy bolup biler.
- `iter_history(buid, page_size=50, before=None, max_messages=None)` sahypalary zerur bolanda okaýar we sahypalaryň çäginde gaýtalanýan ýazgylary aýyrýar. Habaryň teksti, awtory, wagt belgisi, goşundylary we asyl `raw` ýazgysy bolan `WebMessage` obýektlerini berýär. Indiki sahypa geçip bolmasa, `IMORequestError` ýüze çykýar.
- `receive_message(timeout=30)` gelen bir habaryň maglumatlaryny gaýtarýar. Olary göni `download_attachments()` usulyna berip bilersiňiz. Garaşmagyň möhleti dolanda `IMOTimeoutError` ýüze çykýar we birikme açyk galýar.
- `extract_attachments(message)` tor arkaly sorag ibermezden goşundylaryň maglumatlaryny okaýar. Çat taryhynyň ýazgysyny, gelen habaryň maglumatlaryny ýa-da `imdata` sözlügini kabul edýär. Netijede `kind`, `filename` we ölçegi belli bolsa, baýtlardaky `size` meýdanlary bolan `Attachment` obýektlerini gaýtarýar.
- `download_attachment(attachment, directory, max_bytes=268435456)` `pathlib.Path` görnüşindäki faýl ýoluny gaýtarýar. `download_attachments(message, directory, max_bytes=268435456)` ýatda saklanan faýllaryň ýollaryny gaýtarýar. Habarda göçürip alyp bolýan goşundy ýok bolsa, sanaw boş bolýar. Soňky goşundylaryň biri göçürilende ýalňyşlyk ýüze çyksa, öň göçürilen faýllar bukjada galýar.

Resminamalaryň, suratlaryň, wideolaryň, ses faýllarynyň we sesli habarlaryň asyl nusgalaryny, şeýle hem IMO-da göçürip alyp bolýan media hökmünde saklanýan GIF-leri ýükläp bolýar. Müşderi goşundynyň maglumatlaryna görä Nerv, Pixel ýa-da IMO ammarynyň HTTPS salgysyny saýlaýar. Maglumat bölekleýin wagtlaýyn faýla ýazylýar. Müşderi tamamlanmadyk faýllary aýyrýar we atlary gabat gelýän faýllara san goşýar. Her goşundy üçin deslapky çäk 256 MiB. Faýl elýeterli bolmasa ýa-da möhleti gutaran bolsa, `IMOAttachmentUnavailable` ýüze çykýar. Faýl çäkden uly bolsa, `IMOAttachmentTooLarge` ýüze çykýar. Ýüklemegiň beýleki ýalňyşlyklary `IMODownloadError`, signal birikmesiniň ýalňyşlyklary `IMOTransportError` ýa-da `IMOTimeoutError`, faýl ulgamynyň ýalňyşlyklary bolsa `OSError` görnüşinde berilýär.

```python
from imo import extract_attachments

# Sessiýa tassyklanandan soň işlediň.
message = client.receive_message(timeout=30)
for attachment in extract_attachments(message):
    print(attachment.kind, attachment.filename, attachment.size)
    print(client.download_attachment(attachment, "incoming", max_bytes=32 * 1024 * 1024))
```

## Habar ibermek we sessiýany ýapmak

```python
client.send_message(id="BUID_FROM_CONTACTS", text="Salam!")
client.send_message(name="Enem", text="Salam!")
client.send_message(name="Enem", media="photo.jpg")
file_receipt, text_receipt = client.send_message(name="Enem", text="Salam!", media="photo.jpg")
```

Bir alyjyny görkeziň. `id` çatyň identifikatoryny kabul edýär. `name` kontaktyň belligi, lakamy ýa-da görkezilýän ady boýunça doly gabat gelýän ýeke-täk kontakty gözleýär. Uly we kiçi harplar hem-de artykmaç boşluklar hasaba alynmaýar. Kontakt tapylmasa ýa-da birnäçe kontakt gabat gelse, `IMOContactNotFound` ýüze çykýar. `send_message(buid, text)` görnüşinde alyjy hökmünde `Head` ýa-da `Chat` obýektini hem berip bolýar.

`media` 256 MiB-dan uly bolmadyk bir ýerli faýlyň ýoluny kabul edýär. Faýl boş bolup bilmez. IMO ony faýl goşundysy hökmünde alýar. Serwer tassyklanda tekst we faýl üçin `buid`, `message_id` we `timestamp_nano` meýdanlary bolan `SentMessage` gaýtarylýar. Ikisi hem berilse, ilki faýl, soňra tekst iberilýär we `(file_receipt, text_receipt)` gaýtarylýar. Faýl tassyklanyp, tekst tassyklanmasa, faýlyň tassyklamasy `IMOPartialSendError.attachment` meýdanynda bolýar. Faýl iberilişi resmi web kodlaýjysy we synag serweri bilen barlandy. Hakyky hasapdan faýl iberilişi entek tassyklanmady.

Habaryň eltilendigi we okalandygy aýratyn tassyklanýar. Jogaba garaşmagyň möhleti dolsa, habary gaýtadan ibermezden öň çaty barlaň. `logout()` IMO-dan häzirki web sessiýasyny ýapmagy soraýar. `close()` ýerli birikmäni ýapýar we sessiýanyň maglumatlaryny ýatdan aýyrýar. `with` blogundan çykanyňyzda müşderi `close()` usulyny çagyrýar.

## At boýunça we toparlaýyn ibermek

`find_contact(name)` kontaktyň `Head` obýektini ady boýunça gaýtarýar; baş we setir harplar hem-de gaýtalanýan boşluklar hasaba alynmaýar. Ilki bellik, lakam ýa-da görkezilýän at bilen doly gabat gelýän kontakt gözlenýär, soňra adyň bir bölegi boýunça ýeke-täk gabat gelme. Kontakt tapylmasa ýa-da birnäçesi gabat gelse, `IMOContactNotFound` ýüze çykýar. Sanawy gaýtadan soramazlyk üçin `get_contacts()` netijesini `contacts=` arkaly beriň.

`send_many(messages, delay=8.0, jitter=0.3, by_name=False, stop_on_error=False)` `(alyjy, tekst)` jübütlerini tertip boýunça iberýär we `target`, `text`, `sent`, `error` meýdanlary hem-de `ok` häsiýeti bolan `SendResult` sanawyny gaýtarýar. Alyjy — BUID, `Head` ýa-da `Chat`; `by_name=True` bolsa setirler kontakt atlary hasaplanýar we kontaktlaryň sanawy bir gezek soralýar. Habarlaryň arasynda müşderi `delay` sekunt garaşýar (`jitter` çäginde, adatça ±30 %) we gelýän wakalary tassyklamagyny dowam edýär, şonuň üçin arakesme wagtynda gelen habarlar `receive_message()` üçin elýeterli galýar.

```python
client.send_message(client.find_contact("Mom"), "Salam!")

rows = [("Mom", "I'll be home by 7"), ("Father", "Call me back")]
for result in client.send_many(rows, delay=8, by_name=True):
    print(result.target, "ok" if result.ok else result.error)
```

Müşderi ilkinji habary ibermezden öň setirleriň gurluşyny we tekstini barlaýar. `stop_on_error=True` netijelerde ilkinji ýalňyşlyk ýüze çykanda ibermegi bes edýär. Soraga garaşmagyň möhleti dolsa, sessiýa ýapylýar we ýalňyşlyk setiriň netijesinde görkezilýär. Arakesme wagtynda birikme üzülse, usul ýalňyşlyk bilen tamamlanyp biler. CSV-ni öňünden görmek we ähli alyjylary doly gabat gelýän atlary boýunça tapmak üçin [send_batch.py](../examples/send_batch.py) ulanyň.

## Gelýän habarlary işlemek

```python
from imo import IMOClient

with IMOClient() as client:
    client.connect()

    @client.on_message
    def handle(message):
        print(message.buid, message.text)
        for path in client.download_attachments(message, "incoming"):
            print(path)

    client.run()
```

`run()` habarlary işleýän funksiýalary hasaba alnan tertipde şol bir akymda çagyrýar. Garaşylýan wagty signal birikmesinde üç minut maglumat alyş-çalşy bolmasa, müşderi birikmäni açyk saklamak üçin IMO Web-e hyzmat soragyny iberýär. Garaşmagyň möhleti dolsa, diňlemek dowam edýär. Birikme üzülse ýa-da funksiýada ýalňyşlyk ýüze çyksa, ýalňyşlyk çagyryjy koda geçirilýär. Häzirki habar işlenenden soň diňlemegi bes etmek we sessiýany açyk goýmak üçin işleýji funksiýanyň içinde `stop()` çagyryň. `remove_message_handler(handle)` funksiýany sanawdan aýyrýar.

## Barlag

Hakyky IMO serweri QR kod berdi we IMO-nyň açyk CDN-i kitaphananyň HTTPS ýükleýjisi arkaly PNG faýlyny gaýtardy. Topar agzalarynyň sanawy, çat taryhynyň sahypalary, gelen habarlaryň işlenişi we goşundylaryň göçürilişi synag serwerinde barlandy. Nerv paketleri we hasabyň heşi ýasama maglumatlar bilen resmi web müşderisiniň netijesine deňeşdirildi. Hasapdaky amallary başdan ahyra çenli barlamak üçin QR kod bilen tassyklanan sessiýa gerek. IMO Web täzelenende protokolyň görnüşi üýtgäp biler.

```text
python -m pip install -e ".[dev,qr]"
python -m pytest -q
```

Hakyky QR kod alnyşyny we açyk CDN-den ýüklemäni hem barlamak üçin `IMO_WEB_LIVE` gurşaw üýtgeýjisine `1` bahasyny beriň.

Serwer iberişi tassyklamasa, habaryň çatda peýda bolandygyny barlaň. `IMOPartialSendError` ýüze çyksa, faýlyň tassyklamasy `error.attachment` meýdanynda bolýar. At boýunça birnäçe kontakt gabat gelse, kontaktlaryň sanawyndaky BUID-ni ulanyň. [Beýleki ýalňyşlyklar we çözgütler](troubleshooting.md)
