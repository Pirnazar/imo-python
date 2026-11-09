# Интеграция с IMO Windows 1.5.9.3

## Проверенная сборка

Исполняемый файл найден по пути запущенного процесса. В этой установке это `%APPDATA%\imo\1.5.9.3\ImoDesktopApp.exe`. Версии файла, продукта и сборки совпали. EXE помечен `I386`, `ILOnly` и `Required32Bit`. WPF подтверждён ссылками на `PresentationFramework`, `PresentationCore` и `WindowsBase`. Метаданные EXE и его конфигурация указывают .NET Framework 4.6.1. Стенд собран с референсными сборками 4.6.1 и запущен на установленном CLR `4.0.30319.42000`. Подписи EXE, DataCore, ChannelNetwork и Message проверены Windows и принадлежат Pagebites, Inc.

| Файл | SHA-256 |
| --- | --- |
| `ImoDesktopApp.exe` | `7A361A41DA2AC1E2505443BEE9B8E9158509B9C8841FDEAB7169BBD3C26E6685` |
| `Imo.DataCore.dll` | `4B213E72C6CDB8F59A67A53A4127FD8C4B30161BB754C8F9AE15211978538C2B` |
| `Imo.ChannelNetwork.dll` | `00415068501301AD3B9F549972FABB1F2F14E40D0DC238E6ADA4D81EA25DCE6F` |

## Зависимости и операции

Стрелки на [графе зависимостей](../research/evidence/dependencies.dot) идут от сборки к её зависимости. Граф охватывает прямые ссылки между найденными IMO-сборками и выбранные платформенные и нативные границы. `Imo.Dispatcher.Manager.LoadPlugModule` динамически загружает `Imo.Contact.dll` и `Imo.Message.dll` в процесс IMO. Эта связь отсутствует в статических ссылках EXE.

| Действие | Цепочка внутри процесса |
| --- | --- |
| Отправка текста | `ConversationViewModel.SendNormalMessage` формирует `MsgSendModel` с `Buid = Chater.KeyID` и вызывает `BasePlug.StartAction(MessageSend)`. `Market.RunTask` вызывает подходящий `BaseTask.StartTask`. `ForMessagesTask.MessageSend → SendNormalMessage` устанавливает отправителя из текущего пользователя, обращается к локальному `DBMarket` и передаёт работу в `NetMarket.Work → BaseService.DoRequest`. |
| Контакты | `GetAllBuddies → ForChatersTask.GetAllBuddies → ContactHashPool`. `SyncBuddyList` использует `NetMarket.Work`. `ContactsManager.HandleMessage` обрабатывает добавление, удаление и обновление контактов. |
| Чаты | `ForChatersTask.GetChaters` имеет локальную ветвь через `DBMarket.Execute` и сетевую ветвь с версией чатов текущего пользователя. `OpenChat` также идёт через `NetMarket.Work`. |
| Входящие | `Network.HandleMessageReceived → Connection.Dispatcher.ProcessServerMessage`. `NetMarket.RegisterEvent` подписывается на событие сетевого диспетчера. `Market.InitConnect` регистрирует `Market.ReceiveMessageHandler` в `NetMarket.ReceiveMessageHandler`. `MessageManager.HandleRecvIm → ForMessagesTask.MessageReceived → HandleMessageReceive → Market.OnReceivedData` передаёт объект сообщения в событие. `Manager.Initialize` связывает диспетчер с `Market`, а `MessagePlugEntry.OnAction(MessageReceive)` передаёт результат в `HandleOnlineMessage`. |

Публичные методы CLR включают `Market.Initialize`, `Market.RunTask`, `NetMarket.InitConnect` и `DevMessageManager.GetReceivedMessages`. `Market.ReceivedData` и `NetMarket.ReceiveMessageHandler` — события над объектами в памяти процесса. `ReceivedDataHandler` — тип делегата. У `DevMessageManager` три локальные `ConcurrentQueue`, а `Market.DevMessage` проверяет `ApplicationProperties.IsRelease` перед обращением к менеджеру. Среди публичных .NET-интерфейсов найдены модельные `IKeyId` и `IStreamId`, телеметрия `IEventTracking` и интерфейсы захвата аудио и видео. Отдельного контракта внешней подписки или отправки метаданные IMO-сборок не показали.

## Два опыта с CLR

1. Обычный x86-стенд загрузил девять сборок через `Assembly.LoadFrom`, создал четыре модели и получил один синтетический callback от своего `Imo.Dispatcher.Manager`. То же событие на втором объекте `Manager` не вызвало callback первого.
2. В AppContainer без capabilities `Market.Instance` вернул `null`. Методы `GetReceivedMessages`, `GetSentMessages` и `GetProcessedMessages` вернули пустые последовательности. Одновременно на хосте оставался запущен IMO. IL `get_Instance` читает статическое поле. `Market.Initialize` создаёт экземпляр `Market` и записывает в это поле. `Market.InitConnect` через `NetMarket.InitConnect` запускает `Network.Reconnect` и поток подключения. В IL есть ветвь `Session.CookieLogin`. Методы инициализации сессии и подключения разобраны как код. Они не вызывались.

В EXE, DataCore и ChannelNetwork секция `.text` имеет виртуальный диапазон при нулевом объёме данных в файле. ILSpy сообщает `Invalid relative virtual address`, Cecil читает метаданные. После штатной инициализации модулей в отдельном AppContainer тела методов доступны через `GetMethodBody`. Стенд выводит только имена целей вызовов и отдельные ссылки на поля. Он не извлекает строки IL, значения учётных данных, идентификаторы пользователей или содержимое сообщений. [Трасса вызовов](../research/evidence/cold.txt)

## Интерфейсы снаружи процесса

| Возможность | Наблюдение |
| --- | --- |
| TCP и shared memory | У наблюдаемого PID один TCP-слушатель, `127.0.0.1:10598`. Порт из карты активации .NET Framework, вычисленной по GUID и версии EXE, совпал с портом владельца в `netstat -ano`. В установленной `Microsoft.VisualBasic.dll` метод `RemoteCommunicator.RunNextInstance` передаёт аргументы второго запуска. IL IMO `OnStartupNextInstance` показывает журналирование аргументов, вызов базового обработчика и `AppHelper.Activate`. |
| Именованные каналы | Нативные зависимости импортируют named-pipe API. В crashpad обнаружен шаблон имени его канала. Снимок дескрипторов IMO распознал девять сокетов и ни одного подтверждённого pipe endpoint. Для 368 дескрипторов дублирование было недоступно, поэтому снимок неполный. Подключение к каналам и чтение их данных не выполнялись. |
| COM и PE-экспорты | IMO-сборки помечены `ComVisible(false)`. Публичных переопределений не найдено. Поиск CLSID в пользовательской и системной ветках реестра, в 32- и 64-битном представлениях, не нашёл регистрации для проверенной установки. У EXE, Dispatcher, DataCore, ChannelNetwork и штатных плагинов ноль PE-экспортов. У `libtitancpp` 21 экспорт C++, у `libgonet` 19 и у `proxy` 65. Найденные операции создают и обслуживают транспорт. В смешанной C++/CLI-сборке есть `MediaProtoX`, `Nerv` и `AntibanHttpClient`. Интерфейса присоединения к сессии десктопного клиента среди исследованных экспортов и метаданных не найдено. |
| SQLite | `SQLiteExcutor.InitDB` открывает `db1.db` профиля пользователя. Проверены пути под Roaming и Documents. Найден один файл с таблицей `T_Chater` и нулём строк. `T_Message` и `T_User` отсутствовали. Проверены схема и количество строк. Получение сообщений через кэш для этого профиля не подтверждено. Содержимое кэша другого профиля может отличаться. |
| Публичная интеграция | Официальные материалы описывают настольный и веб-клиент. В просмотренных материалах SDK для отправки сообщений или подписки на события установленного Windows-клиента не найден. |

[Модель единственного экземпляра .NET Framework](https://learn.microsoft.com/en-us/dotnet/visual-basic/developing-apps/customizing-extending-my/extending-the-visual-basic-application-model) · [Документация IMO для Windows](https://imo.im/faq/How-to-download-imo-desktop-version) · [Снимок измерений](../research/evidence/snapshot.txt)

## Граница результата

Точное препятствие — собственное состояние каждого процесса и отсутствие у подтверждённого IPC операций над сообщениями и чатами. Загрузка DLL даёт доступ к локальным объектам. Для связи с сервером эти же сборки запускают подключение и используют сессию своего процесса. Штатная загрузка своего плагина означала бы выполнение собственного кода внутри IMO.

Подтвердились вызовы моделей и локальных диагностик, а также чтение метаданных активации. Отправка и получение реального сообщения не подтверждены, поэтому Python Bridge и клиентский API не выпущены. Проверка относится к указанным хешам, обнаруженным интерфейсам и наблюдаемому процессу. Динамические измерения не устанавливают отсутствие любого возможного endpoint в других состояниях клиента. Состояние авторизации работающего процесса отдельно не считывалось.

Все 16 тестов прошли, в том числе три теста с установленным IMO. Чтение офлайн-таблицы чатов проверено на синтетических строках с наблюдаемой схемой. [Команды воспроизведения](../README.md#воспроизведение)
