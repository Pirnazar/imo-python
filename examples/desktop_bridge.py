"""Command-line example for the desktop bridge backend (imo.desktop).

Build the bridge once:   powershell -File native\\bridge\\Build.ps1

    python examples/desktop_bridge.py login
    python examples/desktop_bridge.py chats
    python examples/desktop_bridge.py send "Мама" "Привет!"
    python examples/desktop_bridge.py batch messages.csv --delay 8
    python examples/desktop_bridge.py listen

The first ``login`` prints a QR code: scan it in the imo phone app. Later runs reuse the
saved session. ``--dump FILE`` appends every raw bridge event to FILE as JSON lines.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))

from imo.desktop import IMOClient, IMOError, _show_qr  # noqa: E402

QR_IMAGE = Path("imo-qr.png")


def show_qr(link: str, ttl: int) -> None:
    """Print the code and also save it as an image, for terminals that garble block characters."""
    _show_qr(link, ttl)
    try:
        import qrcode
        qrcode.make(link).save(QR_IMAGE)
        print(f"Картинка с тем же кодом: {QR_IMAGE.resolve()}", flush=True)
    except ImportError:
        pass


def read_batch(path: Path) -> list[tuple[str, str]]:
    """CSV rows ``contact;text``. Lines starting with # and a header row are skipped."""
    raw = path.read_text(encoding="utf-8-sig")
    lines = [line for line in raw.splitlines() if line.strip()]
    if not lines:
        return []
    dialect = csv.Sniffer().sniff(lines[0], delimiters=";,\t")
    rows = []
    for row in csv.reader(lines, dialect):
        if not row or row[0].strip().startswith("#"):
            continue
        if len(row) < 2:
            raise SystemExit(f"Строка без текста: {row}")
        if row[0].strip().casefold() in ("contact", "контакт"):
            continue
        rows.append((row[0].strip(), row[1].replace("\\n", "\n")))
    return rows


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    ap = argparse.ArgumentParser(description="imo через мост к настольному клиенту")
    ap.add_argument("--dump", type=Path, help="дописывать сырые события моста в файл (JSON lines)")
    ap.add_argument("--debug", action="store_true", help="показывать журнал клиента imo")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("login", help="войти (QR при первом запуске) и показать статус")
    sub.add_parser("chats", help="список чатов")
    sub.add_parser("contacts", help="список контактов")
    s = sub.add_parser("send", help="отправить сообщение")
    s.add_argument("to", help="имя контакта/группы или buid")
    s.add_argument("text")
    s.add_argument("--buid", action="store_true", help="`to` — это buid, а не имя")
    b = sub.add_parser("batch", help="отправить сообщения из CSV (контакт;текст)")
    b.add_argument("file", type=Path)
    b.add_argument("--delay", type=float, default=8.0, help="пауза между сообщениями, сек (±30%%)")
    listen = sub.add_parser("listen", help="печатать входящие сообщения до Ctrl+C")
    listen.add_argument("--seconds", type=float, default=0, help="остановиться через N секунд")
    args = ap.parse_args()

    try:
        with IMOClient(debug=args.debug) as imo:
            if args.dump:
                dump = args.dump.open("a", encoding="utf-8")
                imo.on_event(lambda e: (dump.write(json.dumps(e, ensure_ascii=False) + "\n"), dump.flush()))
            status = imo.login(on_qr=show_qr)
            QR_IMAGE.unlink(missing_ok=True)
            user = status.get("user") or {}
            print(f"Вход выполнен: uid={status.get('uid')} имя={user.get('DisplayName') or user.get('Alias') or '-'}")

            if args.cmd == "chats":
                for chat in imo.chats():
                    kind = "группа" if chat.is_group else "личный"
                    print(f"{chat.buid:<28} {kind:<7} {chat.name!r:<30} {chat.last_message[:40]!r}")
            elif args.cmd == "contacts":
                for contact in imo.contacts():
                    print(f"{contact.buid:<28} {contact.name!r}")
            elif args.cmd == "send":
                ok = imo.send(args.to, args.text, buid=args.buid)
                print("✓ доставлено на сервер" if ok else "… отправлено, подтверждение не получено")
            elif args.cmd == "batch":
                results = imo.send_many(read_batch(args.file), delay=args.delay)
                for r in results:
                    print(("✓ " if r.ok else "✗ ") + r.to + ("" if r.ok else f" — {r.error}"))
                print(f"Итого: успешно {sum(r.ok for r in results)}, ошибок {sum(not r.ok for r in results)}")
            elif args.cmd == "listen":
                @imo.on_message
                def show(message) -> None:
                    arrow = "→" if message.outgoing else "←"
                    print(f"{arrow} [{message.chat}] {message.sender_name or message.sender}: "
                          f"{message.text or '<' + message.kind + '>'}", flush=True)

                print("Жду сообщения… Ctrl+C для выхода")
                if args.seconds:
                    import time
                    time.sleep(args.seconds)
                else:
                    imo.run_forever()
    except (IMOError, TimeoutError) as e:
        print(f"Ошибка: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
