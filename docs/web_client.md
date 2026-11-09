# imo-python 0.3.0

[English](web_client.en.md) · [Русский](web_client.md) · [Türkmençe](web_client.tk.md)

`imo-python` — синхронный клиент, созданный на основе анализа протокола IMO Web. Он открывает отдельную сессию, которую вы подтверждаете в официальном мобильном приложении IMO. Для работы нужен Python 3.8 или новее. Сессия хранится в памяти. Используйте каждый экземпляр клиента из одного потока. [Официальный IMO Web](https://web.imo.im/) · [Справка IMO о QR-входе](https://imo.im/faq/More-Ways-to-Login)

## Установка и вход по QR-коду

Из каталога проекта установите библиотеку и запустите интерактивный пример.

```text
python -m pip install -e ".[qr]"
python examples/web_qr.py --download-dir imo-downloads
```

Отсканируйте QR-код телефоном и подтвердите вход в IMO. В примере команда `chats` показывает идентификаторы бесед, `history BUID` читает последнюю страницу истории, а `download BUID 20` сохраняет вложения из 20 последних сообщений. `BUID` — идентификатор беседы, который возвращает IMO.

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
        # Отправка сообщения в эту беседу
        # receipt = client.send_message(buid, "Salam!")
```

`QRChallenge.ttl` задаёт срок действия в секундах. Храните `QRChallenge.payload` в тайне. Для сигнального канала доступны регионы `sgp`, `sjc` и `fra`. Если код истёк или соединение потеряно, заново вызовите `begin_qr_login()`.

## История, входящие сообщения и вложения

- `get_contacts()` возвращает список `Head` и автоматически обходит страницы контактов.
- `get_chats()` возвращает список бесед в виде словарей. Передайте `buid` из записи беседы в `get_history()` или `send_message()`.
- `get_history(buid, limit=50, before=None)` возвращает страницу серверных записей, начиная с новых. Для следующей страницы передайте `timestamp_nano_str` последней записи как `before`. Допустимый размер страницы — от 1 до 100.
- `receive_message(timeout=30)` возвращает данные одного входящего события. Их можно сразу передать в `download_attachments()`. По истечении времени ожидания возникает `IMOTimeoutError`, при этом соединение остаётся открытым.
- `extract_attachments(message)` извлекает метаданные без сетевого запроса. Принимает запись истории, данные входящего события или словарь `imdata`. Возвращает объекты `Attachment` с полями `kind`, `filename` и `size` в байтах, если размер известен.
- `download_attachment(attachment, directory, max_bytes=268435456)` возвращает путь `pathlib.Path`. `download_attachments(message, directory, max_bytes=268435456)` возвращает список путей или пустой список, если в сообщении нет поддерживаемых оригиналов. Если при загрузке следующего вложения возникает ошибка, ранее скачанные файлы остаются в папке.

Поддерживаются оригиналы документов, фото, видео, аудио и голосовых сообщений, а также GIF, которые IMO хранит как скачиваемые медиа. Клиент выбирает Nerv, Pixel или HTTPS-ссылку хранилища IMO по метаданным вложения. Данные записываются во временный файл по мере получения. Клиент удаляет незавершённые загрузки и добавляет числовой суффикс при совпадении имён. Лимит по умолчанию — 256 МиБ на вложение. Для недоступных или истёкших файлов возникает `IMOAttachmentUnavailable`, для превышения лимита — `IMOAttachmentTooLarge`. Остальные ошибки загрузки возвращаются как `IMODownloadError`, ошибки сигнального соединения — как `IMOTransportError` или `IMOTimeoutError`, ошибки файловой системы — как `OSError`.

```python
from imo import extract_attachments

# Выполняется внутри авторизованной сессии.
message = client.receive_message(timeout=30)
for attachment in extract_attachments(message):
    print(attachment.kind, attachment.filename, attachment.size)
    print(client.download_attachment(attachment, "incoming", max_bytes=32 * 1024 * 1024))
```

## Отправка и завершение сессии

`send_message(buid, text)` возвращает `SentMessage` с полями `buid`, `message_id` и `timestamp_nano` после ответа сервера. Доставка и прочтение подтверждаются отдельно. Если время ожидания истекло, проверьте беседу перед повторной отправкой. `logout()` просит IMO завершить текущую веб-сессию. `close()` закрывает локальное соединение и очищает состояние в памяти. При выходе из блока `with` клиент вызывает `close()`.

## Проверка

Реальный сервер IMO выдал QR-код, а публичный CDN IMO вернул PNG через реализованный HTTPS-путь. Скачивание в авторизованной сессии проверено на имитаторе. Пакеты Nerv и хеш идентификатора сверены с результатом официального веб-клиента на синтетических данных. Для сквозной проверки скачивания вложений из личных чатов требуется подтверждённая QR-сессия. Форматы протокола могут измениться при обновлении IMO Web.

```text
python -m pip install -e ".[dev,qr]"
python -m pytest -q tests/test_web_client.py tests/test_attachments.py
```

Установите переменную среды `IMO_WEB_LIVE` в `1`, чтобы дополнительно проверить получение реального QR-кода и загрузку с публичного CDN.
