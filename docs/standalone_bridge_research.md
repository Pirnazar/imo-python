# IMO Windows 1.5.9.3 — Standalone .NET bridge: experimental result

> Historical notes. The independent [integration report](integration-report.md) identifies a live loopback .NET Remoting endpoint for single-instance activation and describes the shipped in-process plug loader.

Scope: test the hypothesis that the installed managed assemblies can be used from a
**separate** .NET process to drive the already-running, authorized IMO client — using
only assembly loading + reflection, no process injection, no protocol re-implementation,
no token extraction, no protection bypass.

Method: reflection-only metadata mapping (PowerShell `ReflectionOnlyLoadFrom`) plus a
read-only C# harness (`research/harness/Harness.cs`) compiled x86 against the real
.NET Framework and run. The harness loads the assemblies, constructs data models, and
**reflects** the service facades without ever calling a connect/send/login method.

## What was tested and confirmed (verifiable)

Run `research/harness/Harness.exe "%APPDATA%\imo\1.5.9.3"` to reproduce.

| # | Question | Result |
|---|----------|--------|
| 1 | Do the `Imo.*` assemblies load in a standalone 4.6.1 **x86** process? | **Yes.** All 8 targets (DataModel, DataCommon, CommonHelper, CommonLog, Language, DB, ChannelNetwork, DataCore) load via `LoadFrom`; inter-assembly references resolve from the install dir. |
| 2 | Are the chat/contact/message **data models** usable standalone? | **Yes.** `TextMessage`, `MessageModel` (78 props), `ChaterModel` (27 props) construct in-memory with no network/session. They are plain POCOs (`MessageOrigin` ctor arg). |
| 3 | Is there a **public Send/Receive API**? | **No.** Across `Imo.DataCore` + `Imo.ChannelNetwork` no public type exposes a `Send*` method. The real send/receive code (`DevIncommingMessage`, `ReceiveMessageHandler`) is non-public plumbing. |
| 4 | What are the **service entrypoints**? | Singleton facades: `Imo.DataCore.Market.Instance` and `Imo.ChannelNetwork.NetMarket.Instance` (also `Market` in DataCore). |
| 5 | What do those facades require to do anything? | A live connection. Public surface is `InitConnect()`, `Reconnect(...)`, `CheckConnection()`, `DisConnect()`; messages arrive via events `ReceivedData` / `ReceiveMessageHandler`. |

## The boundary (this is the actual answer)

Separate the three things you asked me to keep separate:

**A. Technically impossible as specified — attach to the live session from another process.**
A `Market.Instance` created in a *new* process is a brand-new object, not the singleton
living inside the running `ImoDesktopApp.exe`. Managed singletons are not shared across
processes. The running client exposes **no** managed IPC server, no COM registration, no
named pipe, no local socket (confirmed earlier). So there is no supported channel by which
an external process can reach the authorized session's objects. Reaching them anyway is
exactly the injection the task excludes.

**B. Not "no proof" — it is a positive finding that the only self-driven path is a second client.**
The facades *can* be initialized standalone, but the only way to make them send/receive is
`NetMarket.InitConnect()` / `Reconnect()`, which **open a new connection to imo servers**.
That is building an independent client that performs its own network auth — explicitly out
of scope ("не реализуй собственную сетевую авторизацию… отдельный клиент закрытого
протокола"). The harness therefore does not call it.

**C. Terms-of-service — separate and additional.** Even where B were attempted, running a
second/automated client is very likely against imo's terms and risks account action. This is
independent of A and B; it is not the basis for the conclusion, only an added reason.

On your point 9: this conclusion does **not** rest on the crash-reporting libs. It rests on
(A) the absence of any cross-process managed interface and (B) the connection-gated facade
surface — both observed directly in the harness output. The `apm-*`/crashpad libraries were
not treated as anti-tamper and play no role here.

## Consequence for the deliverables

- `research/harness/Harness.cs` + `Harness.exe` — the read-only test project (step 6). Ships and runs.
- Python ↔ C# live bridge (step 7) is **not** implemented, because the required integration
  point (step 8 — interacting with the *already-authorized* session through a supported
  mechanism) does not exist. Implementing a bridge would mean either injection (A) or a
  second self-authenticating client (B), both of which you ruled out. Per the brief, this is
  reported rather than faked.

## What a standalone .NET bridge *could* legitimately do (and its hard limit)

It can load these assemblies and reuse the **data model / serialization** types (e.g. build
or parse `MessageModel`/`TextMessage` objects) in-process. That has value for tooling, but it
is inert: it cannot observe or send anything on your live account without opening its own
connection. The managed layer is a thin facade over the native `libgonet.dll` / `libtitancpp.dll`
transport, and the session state lives there and in the running process — not in anything an
external managed process can bind to.

If the goal remains "automate my own authorized IMO," the only non-injection options are the
ones outside this experiment's constraints (driving the existing client's UI, or the Android
client), or switching to a messenger that offers an official API.
