# Мост к настольному клиенту IMO (`imo.desktop`)

Второй бэкенд библиотеки. `imo.desktop.IMOClient` запускает `ImoBridge.exe` — процесс без окна, который загружает .NET-сборки установленного IMO для Windows и вызывает их так же, как это делает интерфейс программы. Протокол IMO при этом не воспроизводится: вход, шифрование и доставку выполняет код самого клиента.

Синхронный [IMO Web](web_client.md) доступен как `imo.legacy.IMOClient`. Асинхронный SDK и его требования к адаптерам описаны отдельно. [Публичный API](api.md)

> Это неофициальный способ. У IMO нет публичного API, автоматизация аккаунта нарушает условия сервиса и может привести к ограничению аккаунта. Используйте только свой аккаунт и свои контакты.

## Требования

- Windows, .NET Framework 4.6.1 или новее семейства 4.x.
- Установленный IMO для Windows (проверено на 1.5.9.3).
- Python 3.11+ для текущего пакета. Для QR-кода в терминале установите дополнение `pip install -e ".[native]"`.

## Сборка

```powershell
powershell -File native\bridge\Build.ps1 -RuntimeRoot .runtime
```

Скрипт копирует бинарники IMO в `.runtime\<версия>` без профиля (`data`, `data1`), журналов и дампов, затем компилирует туда `ImoBridge.exe`. Без `-RuntimeRoot` используется `%LOCALAPPDATA%\imo-python\runtime`. Клиент ищет мост в `$IMO_BRIDGE`, затем в `.runtime` проекта, затем в `%LOCALAPPDATA%`. После обновления IMO запустите сборку заново.

## Использование

```python
from imo.desktop import IMOClient

with IMOClient() as imo:
    imo.login()                               # первый раз показывает QR-код

    for chat in imo.chats()[:5]:
        print(chat.buid, chat.name, chat.last_message)

    imo.send("Мама", "Привет!")               # по имени контакта или группы
    imo.send("BUID_FROM_CONTACTS", "Привет!", buid=True)

    results = imo.send_many([("Мама", "Доеду к 7"), ("Work Group", "Отчёт готов")], delay=8)

    @imo.on_message
    def handle(message):
        print(message.sender_name, message.text)

    imo.run_forever()
```

| Метод | Что делает |
| --- | --- |
| `login(on_qr=None, timeout=300)` | Восстанавливает сохранённую сессию или показывает QR-коды, пока один не отсканирован. `on_qr(link, ttl)` заменяет вывод в терминал. |
| `chats(refresh=True)` | Список `Chat` (`buid`, `name`, `is_group`, `last_message`, `last_activity`), новые сверху. |
| `contacts(refresh=False)` | Список `Contact`, включая группы. Первый вызов синхронизирует список с сервером. |
| `send(to, text, buid=False)` | Отправляет текст. `True` — сервер подтвердил приём; `False` — подтверждение не пришло за `ack_timeout`. |
| `send_many(pairs, delay=8.0, stop_on_error=False)` | Отправляет пары `(кому, текст)` с паузой ±30 %. Возвращает список `SendResult`. |
| `on_message(handler)` | Обработчик входящих `IncomingMessage` (`chat`, `sender`, `sender_name`, `text`, `kind`, `timestamp`, `outgoing`). Вызывается в потоке чтения моста. |
| `run_forever()` | Ждёт сообщения до Ctrl+C. |
| `on_event(handler)` | Все сырые события моста — для отладки. |

Имя в `send` сопоставляется без учёта регистра: сначала точное совпадение, затем единственное частичное. Несколько частичных совпадений дают `ContactNotFound`. Ошибки: `NotSignedIn`, `ContactNotFound`, `BridgeError`; все наследуют `IMOError`.

Пример командной строки — `python examples/desktop_bridge.py chats`. Команды и параметры доступны через `python examples/desktop_bridge.py --help`. Для `batch` передайте CSV, где каждая строка содержит контакт и текст через точку с запятой.

## Как это устроено

```text
Python (imo.desktop)  ⇄  JSON-строки по stdin/stdout  ⇄  ImoBridge.exe (x86, .NET 4.6.1)
                                                          └ Market.RunTask / Market.ReceivedData
```

- Запуск: `Market.Initialize()`, подписка на `Market.ReceivedData`, `Market.InitConnect()`.
- QR: `RunTask(RequestQRcode)`; после события `QrCodeLoginCompleted` мост вызывает `RunTask(CookieLogin, Str0="qr_login")`, как страница входа клиента. Событие `SignedOn` означает вход.
- Отправка: `RunTask(MessageSend)` с `MsgSendModel`, как `ConversationViewModel.SendNormalMessage`.
- Чаты: `RunTask(GetChaters)` → событие `GetChaters`. Контакты: `SyncBuddyList`, затем `GetAllBuddies` и `GetAllGroups`.
- Входящие: событие `MessageReceive` с `MessageModel`.
- Команда `run` моста вызывает любой `ActionTypes` с параметрами `ActionParamer`, поэтому новые операции добавляются в Python без пересборки.

## Что нужно знать

- **Профиль отдельный.** Сессия моста хранится в `.runtime\<версия>\data`. Удаление этой папки сбрасывает вход. Cookie настольного клиента мост не читает.
- **Идентификатор устройства общий.** UDID берётся из `HKCU\SOFTWARE\imo.im\ImoMessenger`, поэтому для сервера мост — тот же компьютер.
- **База сообщений общая.** `%APPDATA%\imo\<uid>\DB` используют и мост, и настольный IMO. Не запускайте их одновременно.
- **Автозапуск.** Код IMO при старте переписывает запись автозапуска Windows на текущий EXE. Мост сохраняет исходное значение и сразу возвращает его.
- **Журнал клиента** выключен. `IMOClient(debug=True)` выводит его в stderr; в нём могут быть QR-ссылки и содержимое сообщений.
- **Телеметрия** клиента (AppCenter, статистика, APM) и обновление мостом не инициализируются.

## Что проверено

В предыдущем эксперименте с IMO 1.5.9.3 были зафиксированы получение QR, вход, повторное использование сессии, чтение чатов и контактов и получение входящего события. При повторной проверке мост собрался как x86. Запуск в AppContainer остановился до подключения из-за отсутствия доступа к записи реестра автозапуска. Для свежей сквозной проверки нужен отдельный Windows-профиль. Логику обмена Python с мостом проверяют тесты с имитатором. [Тесты](../tests/test_desktop_client.py)
