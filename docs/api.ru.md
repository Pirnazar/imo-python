# Асинхронный API imo-python 0.6.0

[English](api.md) · [Русский](api.ru.md) · [Türkmençe](api.tk.md)

`imo` предоставляет асинхронный SDK с типизированными моделями, обработчиками сообщений и отдельным состоянием для каждого аккаунта. Для сетевых операций передайте адаптер через `transport=`. Готового адаптера для реального IMO в асинхронном SDK пока нет. Без адаптера `connect()` сообщает об этом через `FeatureUnavailableError`.

## Установка и первый запуск

Нужен Python 3.11 или новее. Выполните из корня репозитория.

```sh
python -m pip install .
python examples/basic.py
python examples/parse_messages.py
```

Первый пример показывает, что происходит без адаптера. Второй разбирает локальные примеры сообщений. Следующий фрагмент рассчитан на уже настроенный адаптер с возможностями `ACCOUNT` и `CHATS`.

```python
from imo import IMOClient
from imo.transport import Transport


async def show_account(transport: Transport) -> None:
    async with IMOClient("main", transport=transport) as client:
        print(await client.get_me())
        async for chat in client.get_chats():
            print(chat.id, chat.title)
```

## Сообщения и события

- `await client.send_message(chat_id, text)` отправляет текст и возвращает `Message`, если адаптер поддерживает `SEND_TEXT`.
- `client.get_contacts()`, `client.get_chats()` и `client.get_history(chat_id, limit=20)` обходятся через `async for`.
- `message.id`, `sender_id`, `text`, `date`, `is_outgoing` и `chat_kind` могут быть `None`. Источник задаёт эти значения.
- `await message.reply(text)` использует связанный клиент и требует стабильный ID сообщения. `await message.download(directory)` возвращает кортеж путей. Для этих операций нужны возможности `REPLY` и `DOWNLOAD` соответственно.

Регистрируйте асинхронные обработчики через `@client.on_message(filters.incoming & filters.text)`. Для фильтров доступны `&`, `|` и `~`. Порядок поступления сообщений сохраняется внутри каждого чата. `client.run()` запускает цикл из синхронного кода. В уже работающем цикле используйте `await client.run_until_disconnected()`. [Пример обработчика](../examples/incoming.py) · [Порядок событий и переподключение](architecture.md)

## Несколько аккаунтов и ошибки

Зарегистрируйте клиентов через `IMOManager.add(client)` с разными именами и отдельным адаптером на аккаунт. `await manager.run_async()` возвращает ошибки по именам аккаунтов после завершения слушателей. Изоляция проверена на тестовых адаптерах. Одновременные реальные сессии IMO ещё требуют проверки.

Базовый класс ошибок — `IMOError` из `imo.errors`. `FeatureUnavailableError` означает, что нет адаптера или возможности. `AuthenticationRequired` и `SessionExpired` сообщают о необходимости авторизации. При ошибке подтверждения отправки проверьте беседу перед повтором.

## Синхронный клиент и материалы исследования

Существующие сценарии QR-входа и отправки по имени используют `from imo.legacy import IMOClient` и дополнение `.[qr]`. Нативный Windows-мост доступен через `imo.desktop`, а локальные данные — через `imo.models` и `imo.localdb`. [Синхронный IMO Web](web_client.md) · [Windows-мост](desktop_bridge.md) · [Исследования](research_index.md)
