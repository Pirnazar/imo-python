# Воспроизведение исследования жизненного цикла

Из корня проекта после подготовки Mono.Cecil и референсных сборок по [README](../../README.md#воспроизведение):

```powershell
$app = Get-Process -Name ImoDesktopApp
$install = Split-Path $app.Path
$work = Join-Path $env:TEMP 'imo-research-tools'
$refs = "$work\microsoft.netframework.referenceassemblies.net461\build\.NETFramework\v4.6.1"
$exe = .\research\harness\Build.ps1 -ReferenceAssemblies $refs -OutputDirectory "$work\harness"

.\research\diagnostic_tools\Get-LifecycleMap.ps1 -InstallDirectory $install -CecilDll "$work\mono.cecil\lib\net40\Mono.Cecil.dll" -OutputFile .\research\assembly_map\installed.json
python -B .\research\cold_probe.py $install $exe --lifecycle
.\research\diagnostic_tools\Get-ImoObservation.ps1 -ProcessId $app.Id
```

Режим `--lifecycle` запускает x86-стенд с копиями официальных бинарников в отдельном временном AppContainer без capabilities. В нём выполняются инициализаторы модулей, чтение IL, проверка DTO и TTL и синтетический тест делегатов. Из IL выводятся сигнатуры, ссылки на методы и поля, переходы и ограниченный список названий полей и ветвей. Прочие строковые литералы заменяются на `<redacted>`. Дамп памяти, содержимое профиля, журналы IMO, сетевые пакеты и QR-изображения не сохраняются.

ОС-диагностика возвращает имена известных модулей и количество сокетов по PID. Она не прикрепляет отладчик, не приостанавливает процесс и не читает его память. Она не классифицирует состояние аккаунта. CLR ETW на исследованном хосте оказался недоступен. Даже при наличии Loader/JIT ETW событие JIT означает компиляцию метода. Для повторных вызовов это не трасса доставки сообщения. [CLR ETW](https://learn.microsoft.com/en-us/dotnet/framework/performance/clr-etw-providers)

```powershell
$env:IMO_INSTALL = $install
$env:IMO_HARNESS = $exe
$env:IMO_PID = $app.Id
python -B -m pytest -q
```
