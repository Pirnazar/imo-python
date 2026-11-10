# Клиент IMO Web

[English](web_client.en.md) · [Русский](web_client.md) · [Türkmençe](web_client.tk.md)

`imo.IMOClient` — синхронный клиент на основе анализа протокола IMO Web в пакете `imo-python 0.7.0`. Он открывает отдельную сессию, которую вы подтверждаете в официальном мобильном приложении IMO. Для работы нужен Python 3.11 или новее. Сессия хранится в памяти. Используйте каждый экземпляр клиента из одного потока. [Официальный IMO Web](https://web.imo.im/) · [Справка IMO о QR-входе](https://imo.im/faq/More-Ways-to-Login)

## Установка и вход по QR-коду

Из каталога проекта установите библиотеку и запустите интерактивный пример.

```text
python -m pip install -e ".[qr]"
python examples/web_qr.py --download-dir imo-downloads
```

Отсканируйте QR-код телефоном и подтвердите вход в IMO. В примере команда `chats` показывает идентификаторы бесед, `history BUID` читает последнюю страницу истории, `download BUID 20` сохраняет вложения из 20 последних сообщений, а `members BUID` выводит участников группы. `BUID` — идентификатор беседы, который возвращает IMO.

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
        # Отправка сообщения в эту беседу
        # receipt = client.send_message(chat, "Salam!")
```

`connect()` показывает QR-код в терминале с дополнением `qr`. Для своего способа отображения передайте `connect(show_qr=callback)`. Функция получит объект `QRChallenge`. Вход также можно выполнить в два шага через `begin_qr_login()` и `wait_for_login()`. `QRChallenge.ttl` задаёт срок действия в секундах. Храните `QRChallenge.payload` в тайне. Для сигнального канала доступны регионы `sgp`, `sjc` и `fra`. Если код истёк или соединение потеряно, вызовите `connect()` заново.

## История, входящие сообщения и вложения

- `get_contacts()` возвращает список `Head` и автоматически обходит страницы контактов.
- `get_chats()` возвращает список бесед в виде словарей. Передайте `buid` из записи беседы в `get_history()` или `send_message()`.
- `list_chats()` возвращает объекты `Chat` с полями `buid`, `is_group`, `changed_at_nano` и последним сообщением `last_message`, если оно есть. `get_group_members(chat)` принимает групповой `Chat` или его BUID и возвращает список `GroupMember`.
- `get_history(buid, limit=50, before=None)` возвращает страницу серверных записей, начиная с новых. Для следующей страницы передайте `timestamp_nano_str` последней записи как `before`. Допустимый размер страницы — от 1 до 100.
- `iter_history(buid, page_size=50, before=None, max_messages=None)` загружает страницы по мере обхода и пропускает повторяющиеся записи на их границах. Возвращает объекты `WebMessage` с текстом, автором, меткой времени, вложениями и исходной записью `raw`. Если курсор перестаёт продвигаться, метод сообщает об ошибке `IMORequestError`.
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

```python
client.send_message(id="BUID_FROM_CONTACTS", text="Salam!")
client.send_message(name="Enem", text="Salam!")
client.send_message(name="Enem", media="photo.jpg")
file_receipt, text_receipt = client.send_message(name="Enem", text="Salam!", media="photo.jpg")
```

Укажите одного получателя. `id` принимает идентификатор беседы. `name` ищет одно точное совпадение с заметкой, псевдонимом или отображаемым именем контакта без учёта регистра и лишних пробелов. Если совпадений нет или их несколько, возникает `IMOContactNotFound`. В позиционной форме `send_message(buid, text)` получателем также может быть `Head` или `Chat`.

`media` принимает путь к одному непустому локальному файлу размером до 256 МиБ. IMO получает его как файловое вложение. После подтверждения сервера для текста и файла возвращается `SentMessage` с полями `buid`, `message_id` и `timestamp_nano`. При передаче обоих аргументов сначала отправляется файл, затем текст. Результат — `(file_receipt, text_receipt)`. Если файл подтверждён, а текст нет, квитанция файла доступна в `IMOPartialSendError.attachment`. Загрузку сверили с официальным кодировщиком и проверили на имитаторе. Отправка файла с реального аккаунта пока не подтверждена.

Доставка и прочтение подтверждаются отдельно. Если время ожидания истекло, проверьте беседу перед повторной отправкой. `logout()` просит IMO завершить текущую веб-сессию. `close()` закрывает локальное соединение и очищает состояние в памяти. При выходе из блока `with` клиент вызывает `close()`.

## Отправка по имени и пакетная отправка

`find_contact(name)` возвращает `Head` контакта по имени без учёта регистра и повторных пробелов. Сначала ищется точное совпадение с заметкой, псевдонимом или отображаемым именем, затем единственное частичное. Если подходящих контактов нет или их несколько, возникает `IMOContactNotFound`. Чтобы не запрашивать список повторно, передайте `contacts=` из `get_contacts()`.

`send_many(messages, delay=8.0, jitter=0.3, by_name=False, stop_on_error=False)` отправляет пары `(получатель, текст)` по порядку и возвращает список `SendResult` с полями `target`, `text`, `sent`, `error` и свойством `ok`. Получатель — BUID, `Head` или `Chat`; с `by_name=True` строки считаются именами контактов, а список контактов запрашивается один раз. Между сообщениями клиент ждёт `delay` секунд с отклонением до `jitter` (по умолчанию ±30 %) и продолжает подтверждать входящие события, поэтому сообщения, пришедшие во время паузы, остаются доступны `receive_message()`.

```python
client.send_message(client.find_contact("Mom"), "Salam!")

rows = [("Mom", "I'll be home by 7"), ("Father", "Call me back")]
for result in client.send_many(rows, delay=8, by_name=True):
    print(result.target, "ok" if result.ok else result.error)
```

Все строки проверяются до первой отправки: пустой текст или получатель вызывают `ValueError`, и ничего не отправляется. Если сервер не подтвердил сообщение или имя не найдено, ошибка записывается в `SendResult.error`, а рассылка продолжается; `stop_on_error=True` останавливает её на первой ошибке. Тайм-аут или обрыв соединения завершают сессию, поэтому рассылка останавливается, последняя запись содержит ошибку, а оставшиеся строки в результат не попадают. Сообщение без ответа повторно не отправляется. Рассылки незнакомым людям — это спам и быстрый путь к блокировке аккаунта.

## Обработка входящих сообщений

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

`run()` вызывает обработчики в порядке регистрации в том же потоке. Во время ожидания клиент отправляет служебный запрос IMO Web после трёх минут без сигнального трафика. Цикл продолжает работу после тайм-аута ожидания и передаёт вызывающему коду ошибки соединения и обработчиков. Вызовите `stop()` из обработчика, чтобы выйти из цикла после текущего сообщения и оставить сессию открытой. `remove_message_handler(handle)` удаляет обработчик.

## Проверка

Реальный сервер IMO выдал QR-код, а публичный CDN IMO вернул PNG через реализованный HTTPS-путь. Списки участников, обход истории, вызов обработчиков и скачивание из чатов проверены на имитаторе. Пакеты Nerv и хеш идентификатора сверены с результатом официального веб-клиента на синтетических данных. Для сквозной проверки операций с аккаунтом требуется подтверждённая QR-сессия. Форматы протокола могут измениться при обновлении IMO Web.

```text
python -m pip install -e ".[dev,qr]"
python -m pytest -q tests/test_web_client.py tests/test_attachments.py
```

Установите переменную среды `IMO_WEB_LIVE` в `1`, чтобы дополнительно проверить получение реального QR-кода и загрузку с публичного CDN.
