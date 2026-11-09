# `recv_im` receive-handler analysis (static)

Exact classes/signatures from reflection of the installed assemblies (no process touched).
All of this is **in-process** code in `ImoDesktopApp.exe`; see the blocker note at the end.

## Transport-facing (ChannelNetwork)

`Imo.ChannelNetwork.NetMarket` (singleton `NetMarket.Instance`) sits over the native
transport (`libgonet.dll` / `libtitancpp.dll`) and surfaces incoming data:

```csharp
// events
event Action<JObject>        ReceiveMessageHandler        // raw incoming payload
event EventHandler<...>       DevToolsMessage
event EventHandler<...>       OnSignalConnectChanged       // connection state
// internal plumbing
private void Instance_ReceiveMessageHandler(JObject obj)
private void Instance_ReceivedMessage(Object sender, EventArg`2 e)
private void Instance_IncommingMessage(Object sender, EventArg`2 e)
```

Incoming messages arrive as a **Newtonsoft `JObject`** (the `imdata` envelope documented in
`imdata_format.md`), not as a typed object at this layer.

## Processing / dispatch (DataCore)

`Imo.DataCore.Market` (singleton `Market.Instance`) subscribes to the transport and dispatches:

```csharp
private  void ReceiveMessageHandler(JObject mObj)                       // main receive entry
private  void DevIncommingMessage(JObject mObj)                         // devtools copy
internal void OnReceivedData(ActionTypes actionType, TaskResult e)      // raises ReceivedData
internal void OnReceivedDevData(DevDataType type, TimestampedObject<> d)// raises ReceivedDevData

// PUBLIC subscription surface:
event ReceivedDataHandler    ReceivedData;     // delegate: void(ActionTypes, TaskResult)
event ReceivedDevDataHandler ReceivedDevData;  // delegate: void(DevDataType, TimestampedObject<>)
```

Delegate signatures (both in `Imo.DataCore`):

```csharp
delegate void ReceivedDataHandler(ActionTypes actionType, TaskResult e);
delegate void ReceivedDevDataHandler(DevDataType type, TimestampedObject<object> data);
```

`Imo.DataCore.Message.DevMessageManager` is the diagnostic message log:

```csharp
internal void HandlerDevMessage(DevDataType type, TimestampedObject<> data);
public IEnumerable<...> GetReceivedMessages();
public IEnumerable<...> GetSentMessages();
public IEnumerable<...> GetProcessedMessages();
```

## The one public subscription point

For "notify me on an incoming message", the intended in-app hook is:

```csharp
Imo.DataCore.Market.Instance.ReceivedData += (actionType, taskResult) => { ... };
```

`actionType` (`ActionTypes`) discriminates the server push (incoming im vs. ack vs. seen …),
`taskResult` carries the payload. `MessageModel` instances are built downstream of
`Market.ReceiveMessageHandler(JObject)` from that payload (the construction method bodies are
IL, not exposed by metadata).

## Blocker (receive-specific)

`Market.Instance` and this event live **inside the running IMO process**. A `.ReceivedData`
subscription only fires for the `Market` instance in that process. Subscribing from an external
C#/Python component requires executing code inside `ImoDesktopApp.exe` — i.e. injection — which
is out of scope. There is no out-of-process, no-injection way to attach to this event, and the
on-disk logs (`Logs/*.log`, `*.xlog`) do **not** contain incoming-message events or text. So the
success criterion (a real Python callback on a live incoming message) is not reachable under the
stated constraints. Full reasoning in `in_process_blocker.md`.
