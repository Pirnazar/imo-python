# Headless-мост на сборках IMO 1.5.9.3 — состояние и план

Статус: **реализовано.** Актуальное описание — [desktop_bridge.md](desktop_bridge.md). Ниже — исходные заметки исследования; раздел «Что осталось» устарел.

## Выбранный подход

Отдельный x86-процесс .NET Framework 4.6.1 (`ImoBridge.exe`) загружает официальные сборки, входит по QR как второй клиент и общается с Python по JSON-строкам через stdin/stdout. Python-пакет `imo` оборачивает его в `IMOClient` (отправка текста, пакетная отправка, список чатов, `on_message`).

## Что установлено

- **Изолированный профиль.** Настройки и cookie лежат в `AppDomain.BaseDirectory\data` (`FSUtils.GetOrCreateCacheDir`). Копия бинарников без `data`, `data1`, `Logs`, `nativeCrash` уже создана в `%LOCALAPPDATA%\imo-python\runtime\1.5.9.3` (139 МБ). Хост нужно запускать из этой папки, тогда cookie настольного клиента не затрагивается.
- **Общие ресурсы с настольным клиентом, которые изолировать не удаётся:**
  - UDID читается из `HKCU\SOFTWARE\imo.im\ImoMessenger\UDID` — сервер увидит тот же ПК.
  - База `%APPDATA%\imo\<uid>\DB\db1.db` общая при входе в тот же аккаунт. На время работы моста настольный IMO лучше закрывать.
  - `EnumStartupMode.ForcePCOff` указывает, что сервер может завершить сессию настольного клиента при втором входе.
- **Опасный побочный эффект.** `ApplicationSettings.IsStartupItem()` перезаписывает `HKCU\...\Run\"Imo Messenger"` командой запуска текущего EXE. На этой машине ключ существует. Мост обязан прочитать значение до первого обращения к `ApplicationSettings.Instance` и восстановить его сразу после.
- **Минимальная инициализация** (без WPF-окна, плагинов, AppCenter, статистики и APM):
  1. STA-поток с `new System.Windows.Application()` и запущенным Dispatcher — ядро вызывает `Utils.InvokeOnUI`, который молча ничего не делает при `Application.Current == null`.
  2. `ApplicationProperties.Instance.Version = new ImoVersion(1, 5, 9, 3)` (как `AppHelper.InitVersion`, версия из `ImoDesktopApp.exe`).
  3. `Market.Initialize()`; подписка на `Market.Instance.ReceivedData(ActionTypes, TaskResult)`.
  4. `Market.Instance.InitConnect()`; ждать `ActionTypes` 27 (`SignalConnected`).
- **QR-вход:**
  - `Market.Instance.RunTask((ActionTypes)25, new ActionParamer { SuccessCallback = cb })`; в `cb` приходит `JToken` со `status == "success"`, `result.qr_link`, `result.code_ttl`.
  - Событие 136 — QR отсканирован; 138 — отменён (запросить новый QR).
  - Событие 137 — завершён: вызвать `RunTask((ActionTypes)7, new ActionParamer { Str0 = "qr_login" })` (`CookieLogin`).
  - Событие 8 — `SignedOn`; 9 — `SignOff`; 28 — `SignalDisconnected`.
- **Сборки без защиты** (`Imo.DataModel`, `Imo.DataCommon`, `Imo.CommonHelper`, `Imo.DB`) декомпилируются ILSpy. Для `ImoDesktopApp.exe`, `Imo.DataCore`, `Imo.ChannelNetwork` IL читается через рефлексию после инициализатора модуля.

## Что осталось

1. Разобрать формирование `MsgSendModel` в `ConversationViewModel.SendNormalMessage` (`Plugs\Imo.Message.dll`) и номера `ActionTypes` для `MessageSend`, `MessageReceive`, `GetChaters`, `GetAllBuddies`.
2. Написать `native/bridge/ImoBridge.cs` и скрипт сборки (csc x86, ссылки на сборки из runtime-папки).
3. Проверить подключение и получение QR без входа; затем вход сканированием с телефона.
4. Написать `python/imo/client.py` (`IMOClient`), тесты на поддельном мосте, обновить README.
5. Убрать `bridge` и `ipc` из `.gitignore`.

## Риски

Автоматизированный второй клиент нарушает условия IMO и может привести к ограничению аккаунта. Эксперимент лучше проводить на тестовом номере.
