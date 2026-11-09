# imo-python

## Python-клиент IMO Web

Версия 0.3.0 добавляет скачивание файлов и медиа из истории чатов и входящих сообщений. Клиент поддерживает вход по QR-коду, контакты, список бесед, историю и отправку текста. В руководствах описаны установка, API и результаты проверок.

[English](docs/web_client.en.md) · [Русский](docs/web_client.md) · [Türkmençe](docs/web_client.tk.md)

## Исследование IMO Windows


Проверка установленной сборки от 10 ноября 2026 года. Загрузка и вызов локальных .NET-функций из отдельного x86-процесса работают. Подключение к сессии запущенного IMO через обнаруженные интерфейсы не подтвердилось. Тестовый стенд и диагностические скрипты воспроизводят результат.

[Технический отчёт](docs/integration-report.md) · [Граф зависимостей](research/evidence/dependencies.dot) · [Снимок измерений](research/evidence/snapshot.txt) · [Вызовы из IL](research/evidence/cold.txt)

## QR-вход и жизненный цикл сессии

- [Запуск, профиль и загрузка чатов](docs/application_lifecycle.md)
- [Запрос QR, TTL, сканирование и завершение](docs/qr_authentication_flow.md)
- [Состояния входа, восстановление и sign-off](docs/session_state_machine.md)
- [Сигнальное соединение и reconnect](docs/connection_lifecycle.md)
- [Путь входящего сообщения](docs/incoming_message_flow.md)
- [Архитектура Python-интеграции](docs/python_integration_feasibility.md)

[Карта сборок](research/assembly_map/README.md) · [Трассы и наблюдения](research/lifecycle_traces/README.md) · [Воспроизведение](research/diagnostic_tools/README.md)

## Нативный транспорт

[Реверс libgonet и libtitancpp](docs/native_transport_reverse.md) · [ABI, RTTI, таблицы вызовов и воспроизведение](research/native_transport/README.md)

## Офлайн-функции Python

Пакет содержит модели, парсер `parse_imdata` для уже имеющихся JSON-объектов и `imo.localdb.LocalDB` для чтения `T_Chater` из отдельной копии SQLite. Передавайте файл явно.

```python
from imo.localdb import LocalDB

cache = LocalDB(path=r"D:\snapshots\db1.db")
for chat in cache.chats():
    print(chat.key_id, chat.chat_type.name)
```

Для SQLite используйте согласованную копию, включающую изменения из журнала на момент копирования. На установленной копии IMO таблица чатов существует и пуста. Разбор заполненной таблицы проверен на синтетических строках той же схемы.

```powershell
python -m pip install -e '.[dev]'
python -B -m pytest -q
```

## Воспроизведение

Нужны Windows, PowerShell, Python 3.10+, .NET Framework 4.6.1 или более новая версия семейства 4.x и референсные сборки 4.6.1. Для статического анализа использованы [Mono.Cecil 0.11.6](https://www.nuget.org/packages/Mono.Cecil/0.11.6), [ILSpy CLI 9.1](https://www.nuget.org/packages/ilspycmd/9.1.0.7988) с .NET 8 и [pefile 2024.8.26](https://pypi.org/project/pefile/2024.8.26/).

Из корня проекта в PowerShell, при запущенном IMO:

```powershell
$imo = Get-Process -Name ImoDesktopApp
$install = Split-Path $imo.Path
$work = Join-Path $env:TEMP 'imo-research-tools'
New-Item -ItemType Directory -Force $work | Out-Null

$packages = @{
    'microsoft.netframework.referenceassemblies.net461' = '1.0.3'
    'mono.cecil' = '0.11.6'
    'ilspycmd' = '9.1.0.7988'
}
foreach ($name in $packages.Keys) {
    $version = $packages[$name]
    $zip = Join-Path $work "$name.zip"
    curl.exe --fail --silent --show-error --location "https://api.nuget.org/v3-flatcontainer/$name/$version/$name.$version.nupkg" -o $zip
    if ($LASTEXITCODE) { throw "Download failed for $name" }
    Expand-Archive -LiteralPath $zip -DestinationPath (Join-Path $work $name) -Force
}

$refs = "$work\microsoft.netframework.referenceassemblies.net461\build\.NETFramework\v4.6.1"
$exe = .\research\harness\Build.ps1 -ReferenceAssemblies $refs -OutputDirectory "$work\harness"
& $exe $install
python -B .\research\cold_probe.py $install $exe
python -B .\research\probe.py live --pid $imo.Id --install $install --harness $exe
python -B .\research\probe.py cache
```

`cold_probe.py` создаёт временный профиль AppContainer без capabilities и копирует туда бинарники для теста. Дочерний стенд проверяет токен до инициализации защищённых модулей. Профиль и копии удаляются по окончании.

```powershell
$env:IMO_INSTALL = $install
$env:IMO_HARNESS = $exe
$env:IMO_PID = $imo.Id
python -B -m unittest discover -s tests -v
```

Без переменных `IMO_*` запускаются пять локальных тестов диагностики.

## Статический анализ

```powershell
.\research\Inspect-Managed.ps1 -InstallDirectory $install -CecilDll "$work\mono.cecil\lib\net40\Mono.Cecil.dll" -OutputDirectory "$work\inventory"

$ilspy = "$work\ilspycmd\tools\net8.0\any\ilspycmd.dll"
dotnet $ilspy --disable-updatecheck -t Imo.Dispatcher.Manager "$install\Imo.Dispatcher.dll"
dotnet $ilspy --disable-updatecheck -t Imo.Message.ViewModels.ConversationViewModel -r $install "$install\Plugs\Imo.Message.dll"

python -m pip install --target "$work\python" pefile==2024.8.26
$env:PYTHONPATH = "$work\python"
python -B .\research\probe.py pe --install $install ImoDesktopApp.exe Imo.DataCore.dll Imo.ChannelNetwork.dll libtitancpp.dll libgonet.dll proxy.dll apm-nativecrash.dll
```

Дополнительная проверка типов дескрипторов через снимок NT требует 64-битного Python на 64-битной Windows. Она может вернуть неполный список.

```powershell
python -B .\research\probe_handles.py $imo.Id
```
