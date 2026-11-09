# Incoming-message pipeline (confirmed static map)

Your hypothesised chain, mapped to the real classes/methods found by reflection. Everything
here runs **inside** `ImoDesktopApp.exe`.

```
Native transport            libgonet.dll / libtitancpp.dll        (opaque; encryption+protocol)
        │  push (JObject)
        ▼
NetMarket (ChannelNetwork)  NetMarket.Instance
        │   Instance_ReceiveMessageHandler(JObject)
        │   event Action<JObject> ReceiveMessageHandler
        ▼
Market (DataCore)           Market.Instance
        │   ReceiveMessageHandler(JObject mObj)      ← main receive entry (private)
        │   builds MessageModel from the imdata JObject (IL; see imdata_format.md)
        │   OnReceivedData(ActionTypes, TaskResult)  ← raises the public event
        ▼
Public .NET events          Market.Instance.ReceivedData    (ReceivedDataHandler)
                            Market.Instance.ReceivedDevData (ReceivedDevDataHandler)
                            DevMessageManager.GetReceivedMessages()  (diagnostic log)
        ▼
Subscribers                 WPF view-models in Imo.Dispatcher / Imo.Message
                            (INotifyPropertyChanged / ObservableCollection update the chat UI)
```

Mapping to your 7 questions:

1. **Where `recv_im` is handled:** `NetMarket.Instance_ReceiveMessageHandler(JObject)` →
   `Market.ReceiveMessageHandler(JObject)`.
2. **Method on receive:** `Market.ReceiveMessageHandler(JObject mObj)` (private, DataCore).
3. **Data passed:** a Newtonsoft `JObject` = the `imdata` envelope (`imdata_format.md`).
4. **Where `MessageModel` is created:** downstream of `Market.ReceiveMessageHandler`
   (construction is in IL; the shape it fills is `data_models.md`).
5. **Where it enters chat history:** DataCore message/task layer updates the conversation
   model; the WPF `ConversationViewModel` (plugin `Imo.Message`) observes it.
6. **Events raised after processing:** `Market.ReceivedData(ActionTypes, TaskResult)` and
   `ReceivedDevData(DevDataType, TimestampedObject<>)`; collection/property-changed on the
   view-models.
7. **Who can subscribe:** any code **in-process** can do
   `Market.Instance.ReceivedData += handler`. Nothing out-of-process can.

## Fields realistically available on an incoming message

From the `imdata` JObject + `MessageModel` (see `data_models.md`), the realistically present
fields map to your target `Message` as:

| target | source | notes |
|--------|--------|-------|
| `chat_id` | `buid` | always |
| `text` | `objects[].text` | text messages only |
| `content_type` | `object_type` | text/photo/file/… |
| `timestamp` | `timestamp_nano` | int64 nanoseconds |
| `sender_id` | `author_uid` / `author` | groups; often absent for 1:1 |
| `is_group` | from `ChatType` (Group_Chat=2) | derived |
| `is_outgoing` | `MessageType.Sent` vs `Received` | |
| `id` | not a stable public field at this layer | may be absent |

`parse_imdata` in `python/imo/models.py` already produces this typed view from a payload.

## The subscription blocker

The only real event source is `Market.Instance.ReceivedData`, an in-process .NET event. A real
Python `on_message` callback on a live incoming message would require subscribing to it, which
requires executing code inside the IMO process (injection) — out of scope, and the success
criterion therefore cannot be met under the constraints. On-disk logs carry no message events.
See `in_process_blocker.md` and `recv_im_analysis.md`.
