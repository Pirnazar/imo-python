# QR-авторизация в IMO Windows 1.5.9.3

## Запрос и отображение

`Imo.Main.Views.NewSignIn.SignInWithScanPageView` создаёт `Imo.Main.ViewModels.NewSignIn.SignInWithScanPageViewModel`. VM подписывается на `Imo.Dispatcher.Manager.ReceivedData` и `IMO.Instance.User.PropertyChanged`. При `IsCookieSignedOn == true` конструктор сначала показывает индикатор ожидания. Иначе включает `ShowBeginScanCode`, чей callback вызывает `RequestAndGeneateQRcode(bool, bool)`. Написание имени сохранено из бинарника.

```text
SignInWithScanPageViewModel.RequestAndGeneateQRcode(bool, bool)
  → MainEntry.StartAction(ActionTypes.RequestQRcode, ActionParamer)
  → Market.RunTask(ActionTypes, ActionParamer)
  → QRcodeTask.StartTask → QRcodeTask.RequestQRcode
  → NetMarket.Work(NetActionTypes.RequestQRcode, ActionParamer)
  → LoginService.RequestQRcode → NetManager.Send
```

У запроса есть охранные условия по `User.State`, `isRequest`, состоянию свёрнутого окна и `QRCodeStatus.Confirm`. `LoginService` использует диспетчер текущего процесса. Для QR есть отдельные операции `InvalidateQRcode` на уровнях `QRcodeTask` и `LoginService`. Ветка обычного автоматического обновления вызывает повторный запрос. В исследованном коде таймера вызова invalidate не видно.

## Структура данных и TTL

Успешный callback `<RequestAndGeneateQRcode>b__73_0(JToken)` проверяет `status == "success"`, читает `result.qr_link` как строку и `result.code_ttl` как целое число. CLR-модель `ResRequestQRcode.ResResult` содержит свойства `QrLink` и `CodeTtl` с этими JSON-именами. Подтверждённая структура ответа:

```text
status          string
result          object
  qr_link       string, содержимое для QR
  code_ttl      int, секунды
```

При успехе VM сохраняет время получения, переводит страницу в `QRCodeStatus.Success` и вызывает `Utils.GenerateQRcodeWithLogo(string, int, int)` с полученной строкой и размерами 180 × 180. Результат записывается в `QRCodeSource`. Состав и внутренние поля реального `qr_link` не проверялись.

- `get_Ttl()` возвращает положительный `codeTtl` либо 60 секунд. `StartAutoRefreshQRcodeTimer()` задаёт интервал при создании `DispatcherTimer`. При повторном запуске уже существующего таймера этот метод интервал не переписывает.
- `AutoRefreshQRcode_trick(object, EventArgs)` снова вызывает `RequestAndGeneateQRcode`. `RefreshExpiredQRcodeWhenActivated()` отдельно сравнивает текущую дату с временем успешного ответа плюс TTL, если QR-режим активен. При автоматическом обновлении в свёрнутом окне предусмотрено состояние `Invalid`, ветвь которого очищает источник и переводит состояние в `Error`.
- Ошибка ответа приводит к `Error`. Проверка сети может выставить `NetworkError`. Переход в `Confirm` очищает картинку и останавливает таймер.

## Как клиент узнаёт о сканировании и завершении

`Market.ReceiveMessageHandler(JObject)` направляет аккаунтный push в `AccountMessageManager.HandleMessage(JObject)`. В его async state machine различаются три именных события. VM получает соответствующий `ActionTypes` через `Market.ReceivedData → Manager.Instance_ReceivedData → Manager.ReceivedData`.

| Серверное имя | Локальное событие и результат |
| --- | --- |
| `qr_code_scanned` | `AccountMessageManager.QrCodeScanned(JObject)` устанавливает поля профиля сканирования в `ApplicationSettings` и поднимает `QrCodeScanned` (136). VM вызывает `UpdateQRCodeStatus(Confirm, null)` и ждёт дальнейшего события. |
| `qr_code_login_completed` | `QrCodeLoginCompleted` (137). VM скрывает QR, показывает ожидание и вызывает `StartAction(ActionTypes.CookieLogin)` с внутренним признаком QR-ветки. Далее работают `LoginTask.CookieLogin(ActionParamer)` и `LoginService.CookieLogin(NetActionTypes, ActionParamer)`. |
| `qr_code_login_cancelled` | `QrCodeLoginCancelled` (138). VM вызывает повторный запрос QR в UI-контексте. |
| `signed_on` | Отдельный push. `AccountMessageManager` обновляет пользователя, состояние и локальные компоненты, затем поднимает `SignedOn` (8). |

Это четыре разные точки. Сканирование меняет состояние QR-страницы. О завершении QR-ветки сообщает сервер. Признак авторизации выставляется только в ветви `signed_on`. По Windows IL нельзя установить, всегда ли мобильное приложение требует дополнительного нажатия, как подписана кнопка и какие правила сервера влияют на этот шаг. Официальная справка подтверждает вход по QR на Desktop, а пользователь подтвердил, что ранее отсканировал QR через IMO на телефоне. [Справка IMO](https://imo.im/faq/More-Ways-to-Login)

## Эксперимент

В AppContainer выполнены штатная десериализация синтетического ответа и вызов реального `get_Ttl` на отдельном объекте с тестовыми значениями. Получены значения 60 и 45 секунд. Рендеринг действующего QR, сканирование, подтверждение на телефоне и ответы сервера в этом прогоне не выполнялись. Не считывались журналы IMO: IL успешного callback показывает, что значение QR может передаваться в диагностический вызов. [Трасса](../research/lifecycle_traces/isolated-il.txt)
