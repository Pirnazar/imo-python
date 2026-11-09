# imo-python 0.3.0

[English](web_client.en.md) · [Русский](web_client.md) · [Türkmençe](web_client.tk.md)

`imo-python` — IMO Web protokolynyň seljermesi esasynda taýýarlanan sinhron Python müşderisi. Ol aýratyn sessiýa açýar, siz bolsa ony resmi IMO mobil programmasynda tassyklaýarsyňyz. Python 3.8 ýa-da has täze wersiýa gerek. Sessiýa programmanyň ýadynda saklanýar. Her müşderi nusgasyny bir akymda ulanyň. [Resmi IMO Web](https://web.imo.im/) · [QR kod bilen giriş boýunça IMO gollanmasy](https://imo.im/faq/More-Ways-to-Login)

## Gurnamak we QR kod bilen girmek

Taslamanyň bukjasyndan kitaphanany guruň we interaktiw mysaly işlediň.

```text
python -m pip install -e ".[qr]"
python examples/web_qr.py --download-dir imo-downloads
```

QR kody telefonda skanirläň we IMO-da girişi tassyklaň. Mysalda `chats` buýrugy çatlaryň identifikatorlaryny görkezýär, `history BUID` taryhyň iň soňky sahypasyny okaýar, `download BUID 20` bolsa soňky 20 habaryň goşundylaryny ýatda saklaýar. `BUID` — IMO-nyň gaýtarýan çat identifikatory.

```python
import qrcode

from imo import IMOClient

with IMOClient(region="sgp", timeout=15) as client:
    challenge = client.begin_qr_login()
    qr = qrcode.QRCode(border=4)
    qr.add_data(challenge.payload)
    qr.print_ascii(invert=True)
    client.wait_for_login()

    profile = client.get_me()
    contacts = client.get_contacts()
    chats = client.get_chats()

    if chats:
        buid = chats[0]["buid"]
        for row in client.get_history(buid, limit=20):
            for path in client.download_attachments(row, "imo-downloads"):
                print(path)
        # Şu çata habar ibermek
        # receipt = client.send_message(buid, "Salam!")
```

`QRChallenge.ttl` kodyň näçe sekunt güýjünde bolýandygyny görkezýär. `QRChallenge.payload` bahasyny gizlin saklaň. Signal birikmesi üçin `sgp`, `sjc` we `fra` sebitleri elýeterli. Kodyň möhleti gutarsa ýa-da birikme üzülse, `begin_qr_login()` usulyny gaýtadan çagyryň.

## Çat taryhy, gelýän habarlar we goşundylar

- `get_contacts()` `Head` ýazgylarynyň sanawyny gaýtarýar we kontaktlaryň ähli sahypalaryny awtomatik okaýar.
- `get_chats()` çatlaryň sanawyny Python sözlükleri görnüşinde gaýtarýar. Çat ýazgysyndaky `buid` bahasyny `get_history()` ýa-da `send_message()` usulyna beriň.
- `get_history(buid, limit=50, before=None)` serwerdäki ýazgylaryň bir sahypasyny iň täze habarlardan başlap gaýtarýar. Has köne habarlary almak üçin soňky ýazgynyň `timestamp_nano_str` bahasyny `before` parametrine beriň. Bir sahypada 1-den 100-e çenli ýazgy bolup biler.
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

`send_message(buid, text)` serwerden jogap gelende `buid`, `message_id` we `timestamp_nano` meýdanlary bolan `SentMessage` obýektini gaýtarýar. Habaryň eltilendigi we okalandygy aýratyn tassyklanýar. Jogaba garaşmagyň möhleti dolsa, habary gaýtadan ibermezden öň çaty barlaň. `logout()` IMO-dan häzirki web sessiýasyny ýapmagy soraýar. `close()` ýerli birikmäni ýapýar we sessiýanyň maglumatlaryny ýatdan aýyrýar. `with` blogundan çykanyňyzda müşderi `close()` usulyny çagyrýar.

## Barlag

Hakyky IMO serweri QR kod berdi we IMO-nyň açyk CDN-i kitaphananyň HTTPS ýükleýjisi arkaly PNG faýlyny gaýtardy. Tassyklanan sessiýadaky ýüklemeler synag serwerinde barlandy. Nerv paketleri we hasabyň heşi ýasama maglumatlar bilen resmi web müşderisiniň netijesine deňeşdirildi. Şahsy çatdan goşundy göçürip almagy başdan ahyra çenli barlamak üçin QR kod bilen tassyklanan sessiýa gerek. IMO Web täzelenende protokolyň görnüşi üýtgäp biler.

```text
python -m pip install -e ".[dev,qr]"
python -m pytest -q tests/test_web_client.py tests/test_attachments.py
```

Hakyky QR kod alnyşyny we açyk CDN-den ýüklemäni hem barlamak üçin `IMO_WEB_LIVE` gurşaw üýtgeýjisine `1` bahasyny beriň.
