"""imo.desktop.IMOClient against a fake bridge process (no network, no IMO binaries)."""
import threading
from pathlib import Path

import pytest

from imo.desktop import BridgeError, ContactNotFound, IMOClient, NotSignedIn

FAKE = Path(__file__).parent / "fixtures" / "fake_bridge.py"


def write_bridge(tmp_path, *flags):
    """A copy of the fake bridge with command-line flags baked in."""
    script = tmp_path / "bridge.py"
    script.write_text(
        "import sys\nsys.argv += %r\n" % (list(flags),) + FAKE.read_text(encoding="utf-8"), encoding="utf-8")
    return script


@pytest.fixture
def client(tmp_path):
    with IMOClient(write_bridge(tmp_path, "--signed-on")) as c:
        c.login()
        yield c


def test_login_shows_qr_and_signs_in(tmp_path):
    shown = []
    with IMOClient(write_bridge(tmp_path)) as c:
        assert c.connected and not c.signed_in
        status = c.login(on_qr=lambda link, ttl: shown.append((link, ttl)), timeout=10)
        assert shown == [("https://example.invalid/qr", 60)]
        assert c.signed_in and status["signed_on"]


def test_saved_session_needs_no_qr(tmp_path):
    with IMOClient(write_bridge(tmp_path, "--signed-on")) as c:
        status = c.login(on_qr=lambda *a: pytest.fail("QR requested for a saved session"), timeout=10)
        assert status["uid"] == "999"


def test_operations_require_login(tmp_path):
    with IMOClient(write_bridge(tmp_path)) as c:
        with pytest.raises(NotSignedIn):
            c.send("Mom", "hi")
        with pytest.raises(NotSignedIn):
            c.chats()


def test_chats_are_mapped_and_sorted(client):
    chats = client.chats()
    assert [(c.buid, c.name, c.is_group) for c in chats] == [("grp;", "Work Group", True), ("111", "Mom", False)]
    assert chats[1].last_message == "hi"


def test_contacts_include_groups_and_prefer_remark(client):
    contacts = {c.buid: c for c in client.contacts()}
    assert set(contacts) == {"111", "222", "333", "grp;"}
    assert contacts["222"].name == "Father"
    assert contacts["grp;"].is_group


def test_send_resolves_names(client):
    assert client.send("mom", "one")                 # exact name, case-insensitive
    assert client.send("Work Group", "two")
    assert client.send("222", "three", buid=True)
    assert client.send("Fati", "four")               # unique partial match
    assert client._call("sent") == [["111", "one"], ["grp;", "two"], ["222", "three"], ["333", "four"]]


def test_send_rejects_unknown_and_ambiguous_names(client):
    with pytest.raises(ContactNotFound):
        client.send("Nobody", "x")
    with pytest.raises(ContactNotFound, match="several"):
        client.send("Fat", "x")                      # Father and Fatima
    assert client._call("sent") == []


def test_send_without_ack_returns_false(tmp_path):
    with IMOClient(write_bridge(tmp_path, "--signed-on", "--no-ack")) as c:
        c.login()
        assert c.send("111", "x", buid=True, ack_timeout=0.3) is False


def test_send_many_reports_each_row(client):
    results = client.send_many([("Mom", "a"), ("Nobody", "b"), ("Father", "c")], delay=0)
    assert [(r.to, r.ok) for r in results] == [("Mom", True), ("Nobody", False), ("Father", True)]
    assert "Nobody" in results[1].error
    stopped = client.send_many([("Nobody", "b"), ("Mom", "a")], delay=0, stop_on_error=True)
    assert len(stopped) == 1


def test_on_message_receives_incoming(client):
    got = []
    arrived = threading.Event()

    @client.on_message
    def handler(message):
        got.append(message)
        arrived.set()

    client.send("111", "echo", buid=True)
    assert arrived.wait(5)
    m = got[0]
    assert (m.chat, m.sender, m.sender_name, m.text, m.kind, m.outgoing) == ("111", "111", "Mom", "ping", "Text", False)


def test_missing_bridge_is_reported(tmp_path):
    with pytest.raises(BridgeError):
        IMOClient(tmp_path / "nope.exe").start()
