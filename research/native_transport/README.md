# Воспроизведение нативного анализа

Из корня проекта, после подготовки референсных сборок и Mono.Cecil по [главному README](../../README.md):

```powershell
$install = Split-Path (Get-Process -Name ImoDesktopApp).Path
$work = Join-Path $env:TEMP 'imo-research-tools'
python -m pip install --target "$work\python" pefile==2024.8.26 capstone==5.0.6
$env:PYTHONPATH = "$work\python"

go version -m "$install\libgonet.dll"
python -B .\research\native_transport\inspect_transport.py $install
.\research\native_transport\Get-TitanInterop.ps1 -InstallDirectory $install -CecilDll "$work\mono.cecil\lib\net40\Mono.Cecil.dll"

$refs = "$work\microsoft.netframework.referenceassemblies.net461\build\.NETFramework\v4.6.1"
$exe = .\research\harness\Build.ps1 -ReferenceAssemblies $refs -OutputDirectory "$work\harness"
python -B .\research\cold_probe.py $install $exe --native-probe
```

Статический скрипт выдаёт хеши, PE, Go-символы, xrefs загрузчика, RTTI и CLR fixups. Его разбор `pclntab` предназначен для наблюдаемого формата Go 1.20+ x86 little-endian. Отдельный PowerShell-скрипт сопоставляет CLR-сигнатуры, токены и вызовы из C++/CLI. LLVM-объектный дизассемблер может независимо подтвердить выбранные адреса. Например, VA `0x10153c43` соответствует вызову `LoadLibraryW` в проверенной версии `proxy.dll`.

Стенд `--native-probe` проверяет токен AppContainer до загрузки DLL. Он проверяет возврат при нулевом дескрипторе и создание локальных дескрипторов, затем намеренно упражняет отрицательный сценарий удаления до HTTP-инициализации. Сетевые функции с действительными дескрипторами не вызываются. Для выбранных методов IMO стенд читает IL, показывая места вызова C++/CLI.

[Отчёт](../../docs/native_transport_reverse.md) · [Статические данные](native-evidence.json) · [Трасса C++/CLI](titan-interop.txt) · [Изолированный опыт](isolated-probe.txt)
