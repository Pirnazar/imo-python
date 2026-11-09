"""Read-only evidence collection for IMO 1.5.9.3. No IMO transport calls."""
import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess


def run(args):
    return subprocess.run(args, capture_output=True, text=True, errors="replace",
                          timeout=30, check=True).stdout


def tcp_listeners(netstat_output, pid):
    listeners = []
    for line in netstat_output.splitlines():
        fields = line.split()
        if (len(fields) == 5 and fields[0] == "TCP" and fields[4] == str(pid)
                and fields[2] in {"0.0.0.0:0", "[::]:0"}):
            listeners.append(fields[1])
    return sorted(listeners)


def activation_port(output):
    matches = re.findall(r"^activation_port=([0-9]+)$", output, re.MULTILINE)
    if len(matches) != 1 or not 1 <= int(matches[0]) <= 65535:
        raise ValueError("Harness did not return one valid activation port")
    return int(matches[0])


def cache_status(db):
    """Read stable, rollback-journal schema and counts without creating SQLite sidecars."""
    before = db.stat()
    with db.open("rb") as stream:
        header = stream.read(20)
    if not header.startswith(b"SQLite format 3\0") or len(header) < 20:
        return {"skipped": "unrecognized SQLite header"}
    sidecars = [db.with_name(db.name + suffix) for suffix in ("-wal", "-shm", "-journal")]
    if header[18:20] != b"\x01\x01" or any(path.exists() for path in sidecars):
        return {"skipped": "WAL or active journal"}
    uri = db.resolve().as_uri() + "?mode=ro&immutable=1"
    with closing(sqlite3.connect(uri, uri=True)) as conn:
        known_tables = ("T_Chater", "T_Message", "T_User")
        counts = {}
        for table in known_tables:
            if conn.execute("SELECT 1 FROM sqlite_schema WHERE type='table' AND name=?",
                            (table,)).fetchone():
                counts[table] = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            else:
                counts[table] = None
        total = conn.execute("SELECT COUNT(*) FROM sqlite_schema WHERE type='table'").fetchone()[0]
    after = db.stat()
    if ((before.st_ino, before.st_mtime_ns, before.st_size)
            != (after.st_ino, after.st_mtime_ns, after.st_size)
            or any(path.exists() for path in sidecars)):
        return {"skipped": "database changed during inspection"}
    return {"journal_mode": "rollback", "table_count": total, "rows": counts}


def com_matches(installation):
    import winreg

    # Search both COM registry views, including per-user overrides. Return counts only.
    binaries = {p.stem.casefold() for p in installation.glob("Imo*.dll")}
    binaries.update(p.stem.casefold() for p in (installation / "Plugs").glob("Imo*.dll"))
    binaries.add("imodesktopapp")
    matches = set()
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY):
            access = winreg.KEY_READ | view
            with winreg.OpenKey(hive, r"Software\Classes\CLSID", 0, access) as classes:
                for index in range(winreg.QueryInfoKey(classes)[0]):
                    clsid = winreg.EnumKey(classes, index)
                    for kind in ("InprocServer32", "LocalServer32"):
                        try:
                            key = winreg.OpenKey(classes, clsid + "\\" + kind, 0, access)
                        except FileNotFoundError:
                            continue
                        with key:
                            for name in ("", "Assembly", "CodeBase"):
                                try:
                                    value, _ = winreg.QueryValueEx(key, name)
                                except FileNotFoundError:
                                    continue
                                text = str(value).casefold()
                                if (text.split(",")[0].strip() in binaries
                                        or str(installation).casefold() in text):
                                    matches.add(clsid)
    return len(matches)


def live(args):
    executable = args.install / "ImoDesktopApp.exe"
    if not executable.is_file():
        raise FileNotFoundError(executable)
    port = activation_port(run([str(args.harness), str(args.install), "--activation"]))
    listeners = tcp_listeners(run(["netstat.exe", "-ano"]), args.pid)
    loopback = f"127.0.0.1:{port}"
    print(json.dumps({
        "pid": args.pid,
        "activation_listener_matched": loopback in listeners,
        "tcp_listener_count": len(listeners),
        "other_tcp_listener_count": sum(endpoint != loopback for endpoint in listeners),
        "matching_registered_com_classes": com_matches(args.install.resolve()),
    }, indent=2))
    return 0 if loopback in listeners else 1


def cache(args):
    documents = run(["powershell.exe", "-NoProfile", "-Command",
                     "[Environment]::GetFolderPath('MyDocuments')"]).strip()
    roots = {"roaming": Path(os.environ["APPDATA"]) / "imo"}
    if documents:
        roots["documents"] = Path(documents) / "imo"
    for label, root in roots.items():
        candidates = sorted(root.glob("*/DB/db1.db"))
        print(json.dumps({"root": label, "candidates": len(candidates),
                          "databases": [cache_status(db) for db in candidates]}, indent=2))
    return 0


def pe(args):
    import pefile  # Optional dependency for static PE inspection only.

    ipc = re.compile(r"Pipe|FileMapping|RegisterClassObject|RpcServer|bind$|listen$|HttpListener",
                     re.IGNORECASE)
    for name in args.files:
        file = args.install / name
        with pefile.PE(str(file), fast_load=True) as image:
            image.parse_data_directories(directories=[0, 1, 13])
            exports = []
            if hasattr(image, "DIRECTORY_ENTRY_EXPORT"):
                exports = [entry.name.decode("ascii", errors="replace") if entry.name
                           else f"ordinal {entry.ordinal}"
                           for entry in image.DIRECTORY_ENTRY_EXPORT.symbols]
            imports = sorted({entry.name.decode("ascii", errors="replace")
                              for directory in ("DIRECTORY_ENTRY_IMPORT", "DIRECTORY_ENTRY_DELAY_IMPORT")
                              for library in getattr(image, directory, [])
                              for entry in library.imports
                              if entry.name and ipc.search(entry.name.decode("ascii", errors="replace"))})
            print(json.dumps({
                "file": name, "machine": hex(image.FILE_HEADER.Machine),
                "sections": [{"name": section.Name.rstrip(b"\0").decode("ascii", errors="replace"),
                              "rva": hex(section.VirtualAddress), "file_bytes": section.SizeOfRawData}
                             for section in image.sections],
                "exports": exports, "ipc_related_imports": imports,
            }))
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    command = commands.add_parser("live", help="Match the activation port to the live IMO PID")
    command.add_argument("--pid", type=int, required=True)
    command.add_argument("--install", type=Path, required=True)
    command.add_argument("--harness", type=Path, required=True)
    command.set_defaults(action=live)
    command = commands.add_parser("cache", help="Report only SQLite schema presence and row counts")
    command.set_defaults(action=cache)
    command = commands.add_parser("pe", help="List native exports and IPC-related imports")
    command.add_argument("--install", type=Path, required=True)
    command.add_argument("files", nargs="+")
    command.set_defaults(action=pe)
    args = parser.parse_args()
    return args.action(args)


if __name__ == "__main__":
    raise SystemExit(main())
