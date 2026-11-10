# Troubleshooting

[English guide](web_client.en.md) · [Русское руководство](web_client.md) · [Türkmençe gollanma](web_client.tk.md) · [API reference](api.md)

| Symptom | What to do |
| --- | --- |
| Terminal QR display requires `imo-python[qr]` | Install `python -m pip install -e ".[qr]"` in the Python environment running your script. |
| The QR is hard to scan in the terminal | Run `python examples/qr_to_file.py`. Open the local SVG in a browser, scan it in the official app, and confirm the login before the code expires. |
| The QR expired or login timed out | Start a fresh `connect()` attempt and scan the new code. Terminal and SVG examples request a new code on each run. |
| The server reports `QR login has not completed` | Run `client.connect()` before account operations. With a split login, call `wait_for_login()` after `begin_qr_login()`. |
| The account was signed out or the socket disconnected | Start a fresh QR session. The client stores its current session in memory. |
| A name is missing or ambiguous | Run `contacts.py --name "Exact Name"` or list all contacts. Use the unique BUID to address the recipient when several entries share the same name. |
| A BUID works in Python but fails in a shell | Quote it in the shell, especially when the ID ends in `;`. Use a conversation ID from IMO. |
| No send receipt arrives | Check the conversation before sending again. A timeout can occur after the server receives the request. |
| The file was sent, but the text failed | If you catch `IMOPartialSendError`, inspect `error.attachment` for the confirmed file receipt and check the chat before retrying the text. |
| An attachment expired or exceeded the size limit | Handle `IMOAttachmentUnavailable` or `IMOAttachmentTooLarge` and continue with the other attachments. Set a per-file limit with `max_bytes=`. |
| History pagination stops with a cursor error | Keep the last valid timestamp and inspect that page via `get_history()`. The iterator raises when the cursor cannot safely advance. |
| The listener is idle | `receive_message(timeout=30)` raises `IMOTimeoutError` when no event arrives. `run()` keeps listening after idle timeouts. |

## Verification levels

The live checks obtain a QR challenge and download a public CDN image. Scripted protocol tests cover authenticated operations. To confirm a private send or download against IMO, complete QR login with your account and run the relevant script against a chosen conversation.
