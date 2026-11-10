# Runnable examples

[English guide](../docs/web_client.en.md) · [Русское руководство](../docs/web_client.md) · [Türkmençe gollanma](../docs/web_client.tk.md) · [API reference](../docs/api.md)

Run commands from the repository root after installing the package with `python -m pip install -e ".[qr]"`. Scripts that access an account open a fresh QR session. Use the interactive shell to run several commands after one scan. Replace BUIDs and file paths with your own values. Quote a group BUID that ends in `;` when passing it to a shell.

| Script | Command | Effect |
| --- | --- | --- |
| [web_qr.py](web_qr.py) | `python examples/web_qr.py` | Interactive shell for one QR session |
| [login.py](login.py) | `python examples/login.py` | Confirm QR login and print the account name |
| [qr_to_file.py](qr_to_file.py) | `python examples/qr_to_file.py --output imo-qr.svg` | Render a temporary local QR image |
| [contacts.py](contacts.py) | `python examples/contacts.py --name "Enem"` | Look up one exact contact match. Omit `--name` to list contacts |
| [chats.py](chats.py) | `python examples/chats.py` | List chat BUIDs and last-message previews |
| [chats.py](chats.py) | `python examples/chats.py --group "GROUP_BUID;"` | List group members |
| [send_text.py](send_text.py) | `python examples/send_text.py --name "Enem" "Salam!"` | Send one text message |
| [send_to_enem.py](send_to_enem.py) | `python examples/send_to_enem.py "Salam!"` | Send to the exact contact name `Enem` |
| [send_file.py](send_file.py) | `python examples/send_file.py --id BUID photo.jpg --text "Salam!"` | Send a file, then a separate text |
| [send_batch.py](send_batch.py) | `python examples/send_batch.py examples/batch.example.csv` | Preview a CSV offline. Add `--apply` to send to exact matches |
| [history.py](history.py) | `python examples/history.py BUID --limit 100 > history.jsonl` | Export messages as JSON Lines, newest first |
| [download_media.py](download_media.py) | `python examples/download_media.py BUID imo-downloads --limit 30 --max-mib 32` | Inspect the last 30 messages and download supported attachments up to 32 MiB each |
| [receive_one.py](receive_one.py) | `python examples/receive_one.py --timeout 30` | Wait for one incoming event |
| [listen.py](listen.py) | `python examples/listen.py --buid BUID --count 3` | Print up to three matching incoming messages |
| [inspect_attachments.py](inspect_attachments.py) | `python examples/inspect_attachments.py` | Read attachment metadata from an included offline sample. Optionally pass a JSON file |

## One QR scan for multiple operations

Start `web_qr.py` and enter these commands at the `imo>` prompt. Replace `BUID` with a value from `chats` or `contacts`.

```text
contacts
chats
history BUID
download BUID 20
receive
logout
```

`download BUID 20` checks the 20 latest messages for attachments. `logout` ends the session on the server. `exit` closes the local connection.

## CSV batches

Copy [batch.example.csv](batch.example.csv) and edit the copy. Keep the UTF-8 header `contact;text`. Use the preview first to check the intended recipients and messages.

```sh
python examples/send_batch.py my-batch.csv
python examples/send_batch.py my-batch.csv --apply
```

With `--apply`, the script resolves every name to one exact contact match before sending the first message. It stops on the first failed result. A timeout can leave the result unknown, so check the chat before retrying.

## Local files

`history.py` writes message text and IDs to standard output. Shell redirection saves that output as a private local export. `download_media.py` prints saved paths and reports unavailable attachments individually. The SVG example removes the generated QR file when its login attempt ends.
