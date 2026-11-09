"""Inspect handle types for an IMO PID without opening pipe connections or reading payloads."""
import ctypes as c
import ctypes.wintypes as w
import sys
from collections import Counter

k = c.WinDLL("kernel32", use_last_error=True)
n = c.WinDLL("ntdll")
hptr = c.POINTER(w.HANDLE)

def bind(dll, name, result, *args):
    fn = getattr(dll, name)
    fn.argtypes, fn.restype = args, result
    return fn

open_process = bind(k, "OpenProcess", w.HANDLE, w.DWORD, w.BOOL, w.DWORD)
duplicate = bind(k, "DuplicateHandle", w.BOOL, w.HANDLE, w.HANDLE, w.HANDLE, hptr,
                 w.DWORD, w.BOOL, w.DWORD)
close = bind(k, "CloseHandle", w.BOOL, w.HANDLE)
self_process = bind(k, "GetCurrentProcess", w.HANDLE)
file_type = bind(k, "GetFileType", w.DWORD, w.HANDLE)
pipe_info = bind(k, "GetNamedPipeInfo", w.BOOL, w.HANDLE, c.POINTER(w.DWORD),
                 c.c_void_p, c.c_void_p, c.c_void_p)
query_handles = bind(n, "NtQueryInformationProcess", c.c_long, w.HANDLE, w.ULONG,
                     c.c_void_p, w.ULONG, c.POINTER(w.ULONG))
query_name = bind(n, "NtQueryObject", c.c_long, w.HANDLE, w.ULONG,
                  c.c_void_p, w.ULONG, c.POINTER(w.ULONG))

class HandleEntry(c.Structure):
    _fields_ = [("value", w.HANDLE), ("handle_count", c.c_size_t), ("pointer_count", c.c_size_t),
                ("access", w.ULONG), ("type_index", w.ULONG), ("attrs", w.ULONG), ("reserved", w.ULONG)]

class UnicodeString(c.Structure):
    _fields_ = [("length", w.USHORT), ("capacity", w.USHORT), ("buffer", c.c_void_p)]

def tally_handles(pid):
    process = open_process(0x440, False, pid)
    if not process:
        raise c.WinError(c.get_last_error())
    counts = Counter()
    try:
        length = w.ULONG()
        buf = c.create_string_buffer(1024 * 1024)
        status = query_handles(process, 51, buf, len(buf), c.byref(length))
        if status:
            raise OSError(f"ProcessHandleInformation NTSTATUS={status & 0xffffffff:#x}")
        count = c.c_size_t.from_buffer(buf).value
        entries = (HandleEntry * count).from_buffer(buf, 2 * c.sizeof(c.c_size_t))
        for entry in entries:
            copied = w.HANDLE()
            if not duplicate(process, entry.value, self_process(), c.byref(copied), 0, False, 2):
                counts["duplicate_unavailable"] += 1
                continue
            try:
                if file_type(copied) != 3:
                    continue
                flags = w.DWORD()
                if pipe_info(copied, c.byref(flags), None, None, None):
                    counts["pipe_server" if flags.value & 1 else "pipe_client"] += 1
                    continue
                name_buf = c.create_string_buffer(4096)
                status = query_name(copied, 1, name_buf, len(name_buf), c.byref(length))
                name = UnicodeString.from_buffer(name_buf)
                device = c.wstring_at(name.buffer, name.length // 2) if status == 0 and name.buffer else ""
                if device.casefold().startswith(r"\device\afd"):
                    counts["socket"] += 1
                elif device.casefold().startswith(r"\device\namedpipe"):
                    counts["pipe_unclassified"] += 1
                else:
                    counts["unknown_pipe_type"] += 1
            finally:
                close(copied)
    finally:
        close(process)
    return dict(counts)

if __name__ == "__main__":
    if len(sys.argv) != 2 or c.sizeof(c.c_void_p) != 8:
        raise SystemExit("Usage: 64-bit python probe_handles.py <IMO PID>")
    print(tally_handles(int(sys.argv[1])))
