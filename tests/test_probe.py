import hashlib
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

RESEARCH = Path(__file__).resolve().parents[1] / "research"
sys.path.insert(0, str(RESEARCH))
from probe import activation_port, cache_status, tcp_listeners


class ProbeTests(unittest.TestCase):
    def test_only_owned_tcp_listeners(self):
        table = """
  TCP    127.0.0.1:10598       0.0.0.0:0         LISTENING    42
  TCP    [::1]:9001            [::]:0            LISTENING    42
  TCP    10.0.0.1:2000         10.0.0.2:443      ESTABLISHED  42
  TCP    127.0.0.1:8888        0.0.0.0:0         LISTENING    142
  UDP    127.0.0.1:42          *:*                            42
"""
        self.assertEqual(tcp_listeners(table, 42), ["127.0.0.1:10598", "[::1]:9001"])
        self.assertEqual(tcp_listeners(table, 99), [])

    def test_only_one_valid_activation_port(self):
        self.assertEqual(activation_port("process=x86\nactivation_port=10598\n"), 10598)
        for output in ("", "activation_port=0", "activation_port=65536",
                       "activation_port=4\nactivation_port=5"):
            with self.subTest(output=output), self.assertRaises(ValueError):
                activation_port(output)

    def test_schema_only_distinguishes_missing_tables_and_empty_tables(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Path(folder) / "cache & #1.db"
            conn = sqlite3.connect(db)
            try:
                conn.executescript("""
                    CREATE TABLE T_Chater (unused TEXT);
                    CREATE TABLE T_Message (unused TEXT);
                    INSERT INTO T_Message VALUES ('synthetic test text');
                """)
            finally:
                conn.close()
            before = hashlib.sha256(db.read_bytes()).digest()
            self.assertEqual(cache_status(db)["rows"],
                             {"T_Chater": 0, "T_Message": 1, "T_User": None})
            self.assertEqual(hashlib.sha256(db.read_bytes()).digest(), before)

    def test_wal_cache_is_skipped(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Path(folder) / "cache.db"
            conn = sqlite3.connect(db)
            try:
                self.assertEqual(conn.execute("PRAGMA journal_mode=WAL").fetchone(), ("wal",))
                conn.execute("CREATE TABLE T_Chater (unused TEXT)")
                self.assertEqual(cache_status(db), {"skipped": "WAL or active journal"})
            finally:
                conn.close()

    def test_missing_cache_is_not_created(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Path(folder) / "missing.db"
            with self.assertRaises(FileNotFoundError):
                cache_status(db)
            self.assertFalse(db.exists())


@unittest.skipUnless(os.environ.get("IMO_INSTALL") and os.environ.get("IMO_HARNESS"),
                     "Set IMO_INSTALL and IMO_HARNESS for x86 integration tests")
class InstalledIMOTests(unittest.TestCase):
    def run_probe(self, *args):
        result = subprocess.run(args, capture_output=True, text=True, errors="replace", timeout=55)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    def test_load_and_local_event(self):
        output = self.run_probe(os.environ["IMO_HARNESS"], os.environ["IMO_INSTALL"])
        self.assertIn("process=x86", output)
        self.assertEqual(sum(line.startswith("loaded ") for line in output.splitlines()), 9)
        self.assertIn("dispatcher callback: other instance=0, local synthetic dispatch=1", output)

    def test_cold_state_and_real_call_edges(self):
        output = self.run_probe(sys.executable, str(RESEARCH / "cold_probe.py"),
                                os.environ["IMO_INSTALL"], os.environ["IMO_HARNESS"])
        self.assertIn("cold_market_instance=null", output)
        self.assertIn("cold_GetReceivedMessages_empty=True", output)
        self.assertIn("cold_GetSentMessages_empty=True", output)
        self.assertIn("cold_GetProcessedMessages_empty=True", output)
        for caller, callee in (
            ("Imo.DataCore.Market::get_Instance", "ldsfld Imo.DataCore.Market::<Instance>k__BackingField"),
            ("Imo.DataCore.Market::RunTask", "Imo.DataCore.Tasks.BaseTask::StartTask"),
            ("Imo.DataCore.Tasks.ForMessagesTask::SendNormalMessage", "Imo.ChannelNetwork.NetMarket::Work"),
            ("Imo.DataCore.Message.MessageManager::HandleRecvIm", "ForMessagesTask::MessageReceived"),
            ("Imo.ChannelNetwork.NetMarket::InitConnect", "Imo.ChannelNetwork.Connection.Network::Reconnect"),
            ("Imo.Main.SingleInstanceAppWrpper::OnStartupNextInstance", "Imo.Main.Helper.AppHelper::Activate"),
        ):
            with self.subTest(caller=caller):
                section = output.split("calls " + caller + " ", 1)[1].split("\ncalls ", 1)[0]
                self.assertIn(callee, section)

    @unittest.skipUnless(os.environ.get("IMO_PID"), "Set IMO_PID for the live IPC test")
    def test_live_listener_is_the_activation_listener(self):
        output = self.run_probe(sys.executable, str(RESEARCH / "probe.py"), "live",
                                "--pid", os.environ["IMO_PID"], "--install", os.environ["IMO_INSTALL"],
                                "--harness", os.environ["IMO_HARNESS"])
        self.assertIn('"activation_listener_matched": true', output)
        self.assertIn('"other_tcp_listener_count": 0', output)


if __name__ == "__main__":
    unittest.main()
