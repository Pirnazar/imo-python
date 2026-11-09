"""Run the cold-core experiment on copied DLLs in a temporary AppContainer."""
import ctypes as c
import ctypes.wintypes as w
import msvcrt
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import uuid

kernel = c.WinDLL("kernel32", use_last_error=True)
userenv = c.WinDLL("userenv")
advapi = c.WinDLL("advapi32", use_last_error=True)
handle = w.HANDLE
pointer = c.c_void_p
size = c.c_size_t


class Capabilities(c.Structure):
    _fields_ = [("sid", pointer), ("capabilities", pointer), ("count", w.DWORD), ("reserved", w.DWORD)]


class StartupInfo(c.Structure):
    _fields_ = [("cb", w.DWORD), ("reserved", w.LPWSTR), ("desktop", w.LPWSTR), ("title", w.LPWSTR),
                *[(name, w.DWORD) for name in ("x", "y", "width", "height", "chars_x", "chars_y",
                                                "fill", "flags")],
                ("show", w.WORD), ("reserved2_count", w.WORD), ("reserved2", pointer),
                ("stdin", handle), ("stdout", handle), ("stderr", handle)]


class StartupInfoEx(c.Structure):
    _fields_ = [("startup", StartupInfo), ("attributes", pointer)]


class ProcessInfo(c.Structure):
    _fields_ = [("process", handle), ("thread", handle), ("pid", w.DWORD), ("tid", w.DWORD)]


def bind(dll, name, result, *parameters):
    fn = getattr(dll, name)
    fn.restype = result
    fn.argtypes = parameters
    return fn


def check(success):
    if not success:
        raise c.WinError(c.get_last_error())


def launch(executable, directory, sid, output_file, mode):
    initialize = bind(kernel, "InitializeProcThreadAttributeList", w.BOOL,
                      pointer, w.DWORD, w.DWORD, c.POINTER(size))
    update = bind(kernel, "UpdateProcThreadAttribute", w.BOOL, pointer, w.DWORD, size,
                  pointer, size, pointer, pointer)
    delete = bind(kernel, "DeleteProcThreadAttributeList", None, pointer)
    create = bind(kernel, "CreateProcessW", w.BOOL, w.LPCWSTR, w.LPWSTR, pointer, pointer,
                  w.BOOL, w.DWORD, pointer, w.LPCWSTR, c.POINTER(StartupInfoEx), c.POINTER(ProcessInfo))
    wait = bind(kernel, "WaitForSingleObject", w.DWORD, handle, w.DWORD)
    terminate = bind(kernel, "TerminateProcess", w.BOOL, handle, w.UINT)
    exit_code = bind(kernel, "GetExitCodeProcess", w.BOOL, handle, c.POINTER(w.DWORD))
    close = bind(kernel, "CloseHandle", w.BOOL, handle)

    attribute_size = size()
    initialize(None, 2, 0, c.byref(attribute_size))
    attributes = c.create_string_buffer(attribute_size.value)
    check(initialize(attributes, 2, 0, c.byref(attribute_size)))
    try:
        capabilities = Capabilities(sid, None, 0, 0)
        check(update(attributes, 0, 0x00020009, c.byref(capabilities),
                     c.sizeof(capabilities), None, None))
        startup = StartupInfoEx()
        startup.startup.cb = c.sizeof(startup)
        startup.startup.flags = 0x100  # STARTF_USESTDHANDLES
        with open(output_file, "wb") as output, open(os.devnull, "rb") as stdin:
            output_handle = msvcrt.get_osfhandle(output.fileno())
            input_handle = msvcrt.get_osfhandle(stdin.fileno())
            os.set_handle_inheritable(output_handle, True)
            os.set_handle_inheritable(input_handle, True)
            inherited_handles = (handle * 2)(input_handle, output_handle)
            check(update(attributes, 0, 0x00020002, inherited_handles,
                         c.sizeof(inherited_handles), None, None))
            startup.startup.stdin = input_handle
            startup.startup.stdout = startup.startup.stderr = output_handle
            startup.attributes = c.cast(attributes, pointer)
            process = ProcessInfo()
            command = c.create_unicode_buffer(subprocess.list2cmdline([
                str(executable), str(directory), mode]))
            names = ("APPDATA", "LOCALAPPDATA", "SystemDrive", "SystemRoot", "TEMP", "TMP", "USERPROFILE", "WINDIR")
            variables = [f"{name}={os.environ[name]}" for name in names if name in os.environ]
            environment = c.create_unicode_buffer("\0".join(variables) + "\0\0")
            check(create(str(executable), command, None, None, True,
                         0x00080000 | 0x08000000 | 0x00000400, environment, str(directory),
                         c.byref(startup), c.byref(process)))
            try:
                if wait(process.process, 30_000) != 0:
                    check(terminate(process.process, 1))
                    wait(process.process, 5_000)
                    raise TimeoutError("Cold-core child timed out")
                code = w.DWORD()
                check(exit_code(process.process, c.byref(code)))
                return code.value
            finally:
                close(process.thread)
                close(process.process)
    finally:
        delete(attributes)


def main(install, harness, mode="--cold-core"):
    create_profile = bind(userenv, "CreateAppContainerProfile", c.c_long,
                          w.LPCWSTR, w.LPCWSTR, w.LPCWSTR, pointer, w.DWORD, c.POINTER(pointer))
    remove_profile = bind(userenv, "DeleteAppContainerProfile", c.c_long, w.LPCWSTR)
    sid_string = bind(advapi, "ConvertSidToStringSidW", w.BOOL, pointer, c.POINTER(pointer))
    free_sid = bind(advapi, "FreeSid", pointer, pointer)
    local_free = bind(kernel, "LocalFree", pointer, pointer)
    profile = "ImoColdProbe." + uuid.uuid4().hex
    sid = pointer()
    result = create_profile(profile, "IMO cold core probe", "Temporary harness", None, 0, c.byref(sid))
    if result:
        raise OSError(f"CreateAppContainerProfile HRESULT=0x{result & 0xFFFFFFFF:08X}")
    try:
        string = pointer()
        check(sid_string(sid, c.byref(string)))
        try:
            grant = "*" + c.wstring_at(string) + ":(OI)(CI)(RX)"
        finally:
            local_free(string)

        with tempfile.TemporaryDirectory(prefix="imo-cold-") as tmp:
            root = Path(tmp)
            binaries = root / "binaries"
            binaries.mkdir()
            for source in install.iterdir():
                if source.is_file() and (source.suffix.casefold() == ".dll"
                                         or source.name == "ImoDesktopApp.exe"):
                    shutil.copy2(source, binaries)
            if mode == "--lifecycle":
                (binaries / "Plugs").mkdir()
                for name in ("Imo.Contact.dll", "Imo.Message.dll"):
                    shutil.copy2(install / "Plugs" / name, binaries / "Plugs" / name)
            for source in (harness, harness.with_suffix(".exe.config")):
                shutil.copy2(source, binaries)
            subprocess.run(["icacls.exe", str(binaries), "/grant", grant],
                           check=True, capture_output=True)
            output = root / "stdout.txt"
            code = launch(binaries / harness.name, binaries, sid, output, mode)
            stdout = output.read_text(errors="replace")
            if mode == "--native-probe" and code == 0:
                for line in stdout.splitlines():
                    if (line.startswith(("process=", "gonet_", "module ", "method "))
                            or ("cppcli_titancpp." in line and " call" in line)):
                        print(line)
                recovered = stdout.count("invalid memory address or nil pointer dereference")
                print(f"gonet_destroy_uninitialized_recovered_errors={recovered}")
            else:
                print(stdout, end="")
            print("child exit =", hex(code))
            return code
    finally:
        free_sid(sid)
        result = remove_profile(profile)
        if result:
            raise OSError(f"DeleteAppContainerProfile HRESULT=0x{result & 0xFFFFFFFF:08X}")


if __name__ == "__main__":
    if len(sys.argv) not in (3, 4) or (len(sys.argv) == 4 and sys.argv[3] not in ("--lifecycle", "--native-probe")):
        raise SystemExit("Usage: cold_probe.py <install directory> <Harness.exe> [--lifecycle|--native-probe]")
    install, harness = (Path(arg).resolve(strict=True) for arg in sys.argv[1:3])
    raise SystemExit(main(install, harness, *sys.argv[3:]))
