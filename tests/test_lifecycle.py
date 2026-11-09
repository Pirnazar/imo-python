import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

RESEARCH = Path(__file__).resolve().parents[1] / "research"


class LifecycleEvidenceTests(unittest.TestCase):
    def test_enum_map_separates_signon_signal_and_qr(self):
        assemblies = json.loads((RESEARCH / "assembly_map" / "installed.json").read_text(encoding="utf-8-sig"))
        types = {entry["name"]: entry for assembly in assemblies for entry in assembly["types"]}
        events = types["Imo.DataModel.Enums.ActionTypes"]["enum_values"]
        self.assertEqual({name: events[name] for name in (
            "SignedOn", "SignalConnected", "QrCodeScanned", "QrCodeLoginCompleted", "QrCodeLoginCancelled"
        )}, {
            "SignedOn": 8, "SignalConnected": 27, "QrCodeScanned": 136,
            "QrCodeLoginCompleted": 137, "QrCodeLoginCancelled": 138,
        })

    @unittest.skipUnless(os.environ.get("IMO_INSTALL") and os.environ.get("IMO_HARNESS"),
                         "Set IMO_INSTALL and IMO_HARNESS for the x86 isolation test")
    def test_isolated_qr_and_receive_boundaries(self):
        run = subprocess.run([
            sys.executable, str(RESEARCH / "cold_probe.py"), os.environ["IMO_INSTALL"],
            os.environ["IMO_HARNESS"], "--lifecycle",
        ], capture_output=True, text=True, errors="replace", timeout=55)
        self.assertEqual(run.returncode, 0, run.stdout[-2000:] + run.stderr)
        for marker in (
            "synthetic_qr_response_mapping=pass",
            "synthetic_qr_ttl=default:60,positive:45",
            "synthetic_receive_boundaries=NetMarket.ReceiveMessageHandler -> fixture -> Market.ReceivedData",
        ):
            self.assertIn(marker, run.stdout)
        self.assertNotIn("<unresolved:", run.stdout)
        self.assertNotIn("fixture-only", run.stdout)
