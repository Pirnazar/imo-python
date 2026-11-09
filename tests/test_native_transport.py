import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

RESEARCH = Path(__file__).resolve().parents[1] / "research"
NATIVE = RESEARCH / "native_transport"


class NativeTransportTests(unittest.TestCase):
    def test_binary_evidence_agrees_across_layer_boundaries(self):
        data = json.loads((NATIVE / "native-evidence.json").read_text(encoding="utf-8-sig"))
        wrappers = {item["export"]: item for item in data["gonet"]["wrappers"]}
        self.assertEqual(len(wrappers), 18)
        self.assertTrue(wrappers["gonet_conn_write"]["go_trampoline"].endswith("_gonet_conn_write"))
        self.assertTrue(all(item["ret"] == "plain" for item in wrappers.values()))
        imports = data["titan"]["proxy_imports"]
        self.assertTrue(any("createHttpClient@Proxy" in item["symbol"] for item in imports))
        self.assertTrue(any(hit["label"] == "libgonet.dll" and hit["iat_symbol"] == "LoadLibraryW"
                            for hit in data["proxy_loader_xrefs"]))
        slots = data["titan"]["msvc_rtti"]["MediaProtoXImpl@titancpp"][0]["consecutive_code_pointers"]
        il = (NATIVE / "titan-interop.txt").read_text(encoding="utf-8-sig")
        self.assertEqual(slots[1]["method_token"], "0x60015c4")
        self.assertIn("methoddef 0x060015c4 rva=0xbe5fc titancpp.MediaProtoXImpl.sendJSONWithParams", il)

    @unittest.skipUnless(os.environ.get("IMO_INSTALL") and os.environ.get("IMO_HARNESS"),
                         "Set IMO_INSTALL and IMO_HARNESS to exercise the isolated native ABI")
    def test_local_native_handles(self):
        result = subprocess.run([
            sys.executable, str(RESEARCH / "cold_probe.py"), os.environ["IMO_INSTALL"],
            os.environ["IMO_HARNESS"], "--native-probe",
        ], capture_output=True, text=True, errors="replace", timeout=55)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for marker in (
            "gonet_write_unregistered_handle=-2",
            "gonet_local_handles=2 distinct,nonzero",
            "gonet_destroy_uninitialized_recovered_errors=2",
        ):
            self.assertIn(marker, result.stdout)
