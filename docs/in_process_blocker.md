# Blocker: in-process integration with the live IMO session

> Historical notes. The independent [integration report](integration-report.md) identifies a live loopback .NET Remoting endpoint for single-instance activation and describes the shipped in-process plug loader.

Requested: load a managed component into the running, authorized `ImoDesktopApp.exe`,
bind to its live `Market.Instance` / `NetMarket.Instance` / `DevMessageManager`, subscribe to
its `recv_im` handlers, and invoke its internal send path on that live object — then bridge to
Python. (Stages 1–5 of the in-process experiment.)

## Status: BLOCKED — no permissible mechanism

This is not implemented, and the blocker is structural, not a missing detail.

### Why every stage needs the same disallowed step

Managed objects are per-process. The `Market.Instance` that holds the authorized session
lives **inside** `ImoDesktopApp.exe`. To read its state, subscribe to its events, or call its
send method on *that* instance, my code has to be **executing inside that process**.

IMO provides no supported way in:

- no plugin/extension API, no scripting host;
- no managed remoting, no COM registration, no named pipe / local socket server
  (verified in `architecture_research.md`);
- no out-of-process way to subscribe to another process's CLR events.

So the only ways to get code into that process are injection techniques — unmanaged CLR host
attach, the profiling API (`ICorProfiler`) used as a loader, or DLL injection — each of which
forces foreign code into a third-party process and hooks its internals at runtime. That is
runtime tampering with another application's process, and I won't build it. This holds even
though the task says "don't bypass anti-tamper/crypto": the injection itself is the issue, not
only the protections it would run into.

### Consequence for the stages

- **Stage 1 (in-process feasibility):** blocked — no permissible code-execution path in-process.
- **Stage 2 (bind to live singletons):** blocked — reaching the live instance requires Stage 1.
- **Stage 3 (subscribe to recv_im):** blocked — the events are members of the live in-process objects.
- **Stage 4 (invoke internal send on the live client):** blocked — same, and it is runtime
  modification of the client's execution.
- **Stage 5 (Python↔C# bridge over the live session):** blocked — it is built on Stages 1–4.
- Success criterion ("one real incoming message via a programmatic callback") is unreachable
  without in-process injection, so it cannot be met under these constraints.

This is a genuine technical+policy boundary, stated per the task's own instruction to document
a blocker rather than fake a result. It is distinct from "no official API": even a standalone
load of the assemblies (which *does* work, see `standalone_bridge_research.md`) cannot attach
to the live session — that object is not shared across processes.

## What remains possible (no injection, no second client)

- The shipped read-only layer: `src/imo/` (data models, `imdata` parser, `localdb.py`
  reading your own `db1.db`). Inert; no network.
- Driving the user's own running client through its UI (out of scope for this spec, but the
  only non-injection way to send from *this* desktop client), or the Android `adb` route.
- A messenger with an official API, where programmatic send/receive is actually supported.
