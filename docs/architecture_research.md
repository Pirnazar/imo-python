# IMO Windows 1.5.9.3 — architecture (confirmed)

> Historical notes. The independent [integration report](integration-report.md) identifies a live loopback .NET Remoting endpoint for single-instance activation and describes the shipped in-process plug loader.

Static, non-destructive findings about the installed client.

## Application

- **Publisher:** PageBites, Inc (installer Authenticode signature valid).
- **Install dir:** `%APPDATA%\imo\1.5.9.3`; main binary `ImoDesktopApp.exe`.
- **Runtime:** .NET Framework **4.6.1**, **x86** (IL-only, 32-bit flagged); UI is **WPF**
  (`PresentationFramework`, custom `Imo.CommonControls`).
- **User data:** per-account folder with a SQLite DB (`DB/db1.db`) and image cache; app
  settings in `settingconfig/imoSettingConfig` (JSON). Logs via NLog.

## Module layers

- **Managed (readable metadata):** `Imo.DataModel` (DTOs/enums), `Imo.DataCommon`,
  `Imo.DataCore` (message/task orchestration, `Market` facade), `Imo.ChannelNetwork`
  (`NetMarket` connection facade), `Imo.DB`, `Imo.Dispatcher` (WPF view-models). Serialization
  is Newtonsoft.Json. Only part of `Imo.DataCore` is name-obfuscated.
- **Native transport/crypto:** `libgonet.dll` (~10 MB, Go), `libtitancpp.dll` (~10 MB, C++),
  `proxy.dll`. The actual connection, encryption and protocol framing live here.

## Integration surface

- **No** official API/SDK, plugin model, or documented extension point.
- **No** local IPC server exposed by the running client: no named pipe, no COM registration,
  no `imo://` URL handler, no local socket. (No managed `Mutex`/pipe server string present.)
- The only managed messaging entrypoints are the `Market` / `NetMarket` **singletons**, whose
  public surface is connection-oriented (`InitConnect`, `Reconnect`, `CheckConnection`) with
  message delivery via events — no public `Send*` method.

## Consequence

Automation without UI must either drive the existing client (UI) or reach its internals.
A separate process can load the assemblies and reuse the data layer, but cannot attach to the
running authorized session (see `standalone_bridge_research.md`). This package therefore
ships the data/`imdata` layer only (`data_models.md`, `imdata_format.md`).
