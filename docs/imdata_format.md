# IMO 1.5.9.3 — `imdata` message format (static map)

Reconstructed from string literals and metadata in `Imo.DataCore` / `Imo.DataModel` /
`Imo.ChannelNetwork` (read-only; no process, session, or network touched). This documents
the **shape** of the client's messaging payloads. It is not a working client and does not
produce valid wire bytes — see "Boundary" at the end.

## Signaling layer (method names)

The client talks to imo servers with named RPC-style methods (string literals found in
`Imo.DataCore` / `Imo.ChannelNetwork`). Grouped by purpose:

- **Send:** `send_im`, `send_message`, `send_message_with_reply`, `send_photo`/`send_photos`,
  `send_video`, `send_audio`/`send_audios`, `send_files`, `broadcast`, `send_reflect`.
- **Receive / state:** `recv_im`, `recv_unread_msgs`, `message_acked`, `message_seen`,
  `group_message_seen`, `mark_msgs_as_read`, `marked_msgs_as_read`, `im_typing`/`not_typing`,
  `delete_im`, `replace_im` (edit), `replaced_msg`.
- **Read / history:** `get_chat_list`, `get_conversation`, `get_recent_messages`,
  `get_user_messages`, `get_media_msgs`, `convhistory`, `get_topped_chats`,
  `last_unread_ts_nano`.
- **Profile / misc:** `get_my_profile`, `get_user_status_v2`, `get_group_members`,
  `get_blocked_buddies`, `get_pack_stickers`/`get_packs`, `get_auth_token`.

These map onto the state enums in `data_models.md` (`message_acked`→ACKED, `message_seen`→SEEN).

## `imdata` envelope

`Imo.DataModel.Models.MsgSendModel` carries `Buid`, `Content`, `SendMessageType`,
`FileInfo` and **`Imdata` (JObject)**. The `imdata` blob is an object wrapper; the observed
shape is:

```jsonc
{
  "buid": "<chat/buddy id>",      // target
  "object_type": "<type token>",  // discriminator (see table)
  "objects": [ { /* one content object, keyed by object_type */ } ],
  "anon_id": "...",               // present for some flows
  "trace_id": "...",
  "timestamp_nano": 0,
  "is_silent": false              // seen for notifications
}
```

### `object_type` tokens ↔ content keys

`object_type` values found as literals: `text, photo, video, audio, sticker, gif, dice,
file, object_reply, universal_card, call_log, big_group_invite, Contact`.

| object_type | key content fields (string literals) |
|------------|---------------------------------------|
| text | `text` |
| photo | `photo`, `photo_uploaded_2` / `photo_uploaded`, `original_width`, `original_height`, `img_url`, `thumb_url` |
| video | `video`, `video_uploaded_2` / `video_uploaded`, `thumb_url`, `bigo_url`, `bigo_uploaded`, `bigo_thumbnail_url`, `original_width/height` |
| audio | `audio`, `audio_uploaded_2` / `audio_uploaded`, `local_path`, `duration` |
| file | `file_name`, `file_size`, `file_uploaded`, `ext`, `too_big` |
| sticker | `sticker`, `sticker_id`, `pack_type`, `pack_id` |
| new_sticker | `new_sticker_id`, `lottie_url`, `lottie_url_sub_1/2` |
| gif | `gif_id`, `web_url`, `http_url` |
| dice | `dice` |
| object_reply / message_reply | `object_reply`, `reply`, `reply_sticker`, `replaced_im`, `replace_im`, `replace_im_ts`, `replaced_im_type` |
| universal_card | `universal_card` (CardBody/CardConfig/CardInfo/CardTail/CardAction sub-DTOs) |
| call_log | `call_log`, `call_type`, `call_duration`, `call_end_reason`, `call_not_answered_uids`, `missed_call` |
| group_call | `group_call_invite`, `joined_group_call`, `joining_members_count`, `group_call_sync_ts` |
| mentions (any text) | `at_uids` (array of mentioned user ids) |

Media uploads reference separate upload methods: `upload_photos`, `upload_videos`,
`upload_audio` — i.e. media is uploaded first, then referenced by url/id inside `imdata`.

## Enum serialization detail

Enum-typed fields in the model use a **`LowercaseEnumConverter`** (e.g. `UserModel.Primitive`,
`QuoteMessageModel.QuoteMessageType`, card styles). So enum values go on the wire lowercased —
consistent with the lowercase `object_type` tokens above.

## Boundary (unchanged)

This is a **descriptive** map of the format, recovered from static strings. It does **not**
constitute a working encoder or client:

- The exact nesting, required vs optional fields, id/hash derivations, `ssid`/`edata` framing
  and the signing/transport all live in the non-public send path and the native
  `libgonet.dll` / `libtitancpp.dll` layer — not reproduced here.
- Assembling and transmitting a valid `imdata` would mean re-implementing imo's closed
  messaging protocol and running its own authenticated connection — explicitly out of scope.

Use this to **understand/parse** structures and to type your tooling (see `python/imo/models.py`),
not to send on your account.
