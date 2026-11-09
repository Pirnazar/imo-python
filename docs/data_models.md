# IMO 1.5.9.3 — data model layer (`Imo.DataModel`)

Static map of the chat/contact/message DTOs, from reflection-only metadata (no code run,
no process touched). This is the layer a standalone tool can legitimately reuse in-memory;
the networking/session limit from `standalone_bridge_research.md` still applies.

## Message type hierarchy

All message kinds derive from `Imo.DataModel.Models.MessageModel : BaseModel`.
Ctor is `(MessageOrigin origin)`; `MessageModel()` also exists. One class per content kind:

`TextMessage`, `PhotoMessage`, `VideoMessage`, `AudioMessage`, `FileMessage`, `GifMessage`,
`StickerMessage`, `NewStikcerMessage`, `MessageReplyMessage`, `ObjectReplyMessage`,
`StoryReplyMessage`, `UserProfileMessage`, `UniversalCardmMessage`, `DiceMessage`,
`CallLogMessage`, `GroupCallMessage`, `BigGroupInviteMessage`, `SystemMessage`.

### Content-type enum ↔ class

`Imo.DataModel.Enums.MessageContentType` (the on-wire discriminator):

| value | enum | class |
|------|------|-------|
| 0 | Text | TextMessage |
| 1 | Photo | PhotoMessage |
| 2 | File | FileMessage |
| 3 | Audio | AudioMessage |
| 4 | Reply | ObjectReplyMessage |
| 5 | Sticker | StickerMessage |
| 6 | System | SystemMessage |
| 7 | Video | VideoMessage |
| 8 | MessageReply | MessageReplyMessage |
| 9 | Dice | DiceMessage |
| 10 | Gif | GifMessage |
| 11 | NewSticker | NewStikcerMessage |
| 12 | UserProfile | UserProfileMessage |
| 13 | BigGroupInvite | BigGroupInviteMessage |
| 14 | UniversalCard | UniversalCardmMessage |
| 15 | CallLog | CallLogMessage |
| 16 | GroupCall | GroupCallMessage |

## Delivery / send states

Answers the earlier "submitted / sent / delivered / read" question — these are distinct and modeled:

- `MessageState`: `SENDING=0, ACKED=1, DELIVERED=2, SEEN=3, SENDFAILED=4`
  (ACKED = server accepted ≈ "sent"; DELIVERED = reached peer; SEEN = read.)
- `MessageSendState`: `Success=0, Sending=2, Fail=-1, Hide=3, Retract=4`
- `MessageType`: `Sent=0, Received=1, System=2`

## Chats and contacts

- `ChatTypes`: `Unknow=-1, Person_Chat=0, Group_Chat=2, Story_Chat=3, FileHelper_Chat=4`
- `ChaterModel` — conversation wrapper; ctors `()`, `(UserModel)`, `(GroupModel)`, `(StoryModel)`, `(FileHelperModel)`.
- `HeadModel` — contact/chat head, the main contact DTO. Wire fields:

  | json | type | meaning |
  |------|------|---------|
  | `alias` | string | contact alias |
  | `display` | string | display name |
  | `icon` | string | avatar id/url |
  | `is_buddy` | bool | in address book |
  | `favorite` | bool | starred |
  | `is_muted` | bool | muted |
  | `note` | string | personal note / remark |

  A chat/buddy is addressed by **`buid`** (buddy/chat id, on `BaseModel`), not by phone number —
  confirming the earlier finding that there is no "find contact by +phone" primitive at this layer.

## Serialization

- The layer serializes with **Newtonsoft.Json** — 145 `[JsonProperty]`, 13 `[JsonIgnore]`,
  7 `[JsonConverter]` across `Imo.DataModel`. Field names are snake_case (`timestamp_nano`,
  `is_buddy`, `call_end_reason`).
- Richest fully-mapped DTO is `MessageReplyMessage+QuoteMessageModel` (12 fields:
  `author`, `authorAlias`, `message`, `photo`, `sticker`, `type`, `timestamp`,
  `sender_timestamp_nano`, `is_audio`, `call_end_reason`, `messageData`, …).

### Important limit — content is NOT a flat serializable graph

`TextMessage` itself exposes only `timestamp_nano` + `buid` as `[JsonProperty]`; the visible
text and media fields on the subclasses (`PhotoUrl`, `FileUrl`, …) are **display properties
without JSON attributes**. The actual outbound payload is assembled separately:

`Imo.DataModel.Models.MsgSendModel` = the send envelope:
`Buid` (target), `Content` (string), `SendMessageType` (MessageContentType),
`FileInfo` (AppendFileInfo), `Model` (BaseModel) and **`Imdata` (JObject)** — a raw,
app-built JSON blob (`imdata`) plus custom `JsonConverter`s.

So you can construct and read these model objects standalone, but you **cannot** derive the
exact wire bytes from the model layer alone: the `imdata` assembly and the converters live in
the non-public send path (and ultimately the native transport). This is the concrete reason
the model layer is reusable for tooling/parsing but is **inert for sending** without the
client's own code and connection — consistent with the bridge conclusion.

## What this enables (safely) vs not

- Safe/useful: build and inspect `MessageModel`/`HeadModel`/`ChaterModel` objects, map
  content types and states, drive a typed representation in your own tools, parse structures
  you already have.
- Not possible from this layer alone: produce a valid outbound `imdata` or read your live
  account — those need the session + native transport, which no external process can attach to.
