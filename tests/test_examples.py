"""Exercise the example entry points without contacting any real account."""

import json
from pathlib import Path
import runpy
import sys

import pytest

from imo import IMOClient, IMOLoginError, IMOPartialSendError, IMORequestError, SentMessage
import test_web_client


EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
CONTACTS = [{"buid": "contact-a", "alias": "Enem"}, {"buid": "other", "alias": "Another Example"}]
scripted_socket = test_web_client.scripted


@pytest.fixture(autouse=True)
def block_network(monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("An example attempted a real connection")

    monkeypatch.setattr("imo._web_transport.create_connection", unexpected)


def run_example(monkeypatch, script, *args):
    path = EXAMPLES / script
    monkeypatch.setattr(sys, "argv", [str(path), *(str(arg) for arg in args)])
    runpy.run_path(str(path), run_name="__main__")


@pytest.mark.parametrize("path", sorted(EXAMPLES.glob("*.py")), ids=lambda path: path.name)
def test_help_without_connecting(monkeypatch, path, capsys):
    with pytest.raises(SystemExit) as result:
        run_example(monkeypatch, path.name, "--help")
    assert result.value.code == 0
    assert "usage:" in capsys.readouterr().out


def test_offline_attachment_and_batch_examples(monkeypatch, capsys):
    run_example(monkeypatch, "inspect_attachments.py")
    assert capsys.readouterr().out == "photo\tsample.jpg\t1024\n"
    run_example(monkeypatch, "send_batch.py", EXAMPLES / "batch.example.csv")
    assert "2 message(s) in the preview" in capsys.readouterr().out


@pytest.mark.parametrize("cancelled", [False, True])
def test_svg_login_writes_and_removes_qr(monkeypatch, scripted_socket, tmp_path, cancelled):
    socket = scripted_socket(cancelled=cancelled)
    output = tmp_path / "qr.svg"
    original_wait = IMOClient.wait_for_login

    def wait_for_login(client, **kwargs):
        assert b"<svg" in output.read_bytes()
        return original_wait(client, **kwargs)

    monkeypatch.setattr(IMOClient, "wait_for_login", wait_for_login)
    if cancelled:
        with pytest.raises(IMOLoginError, match="cancelled"):
            run_example(monkeypatch, "qr_to_file.py", "--output", output)
    else:
        run_example(monkeypatch, "qr_to_file.py", "--output", output)
    assert socket.closed
    assert not output.exists()


def test_account_and_exact_contact_examples(monkeypatch, scripted_socket, capsys):
    scripted_socket()
    run_example(monkeypatch, "login.py")
    assert "Signed in as Test" in capsys.readouterr().out
    scripted_socket(buddies=CONTACTS)
    run_example(monkeypatch, "contacts.py", "--name", " eNeM ")
    assert capsys.readouterr().out == "contact-a\tEnem\n"


def test_group_members_example(monkeypatch, scripted_socket, capsys):
    scripted_socket()
    run_example(monkeypatch, "chats.py", "--group", "group;")
    assert "owner\tOwner\towner" in capsys.readouterr().out


def test_send_text_resolves_exact_recipient(monkeypatch, scripted_socket, capsys):
    socket = scripted_socket(buddies=CONTACTS)
    run_example(monkeypatch, "send_text.py", "--name", "Enem", "Salam")
    (params,) = [params for _, method, params in socket.calls if method == "send_im"]
    assert (params["buid"], params["msg"]) == ("contact-a", "Salam")
    assert capsys.readouterr().out.startswith("contact-a\t")


def test_send_file_reports_partial_result(monkeypatch, scripted_socket, tmp_path, capsys):
    scripted_socket()
    path = tmp_path / "attachment.txt"
    path.write_text("example", encoding="utf-8")

    def send_message(client, **kwargs):
        assert client.is_authenticated
        assert kwargs == {"id": "contact-a", "name": None, "text": "Salam", "media": path}
        receipt = SentMessage("contact-a", "file-id", "900")
        raise IMOPartialSendError(receipt, IMORequestError("fixture"))

    monkeypatch.setattr(IMOClient, "send_message", send_message)
    with pytest.raises(SystemExit) as result:
        run_example(monkeypatch, "send_file.py", "--id", "contact-a", path, "--text", "Salam")
    assert result.value.code == 1
    assert "File confirmed (file-id)" in capsys.readouterr().err


@pytest.mark.parametrize("second", ["Another Example", "Another"])
def test_batch_preflights_every_recipient(monkeypatch, scripted_socket, tmp_path, second):
    socket = scripted_socket(buddies=CONTACTS)
    path = tmp_path / "batch.csv"
    path.write_text(f"contact;text\nEnem;Salam\n{second};Salam\n", encoding="utf-8")
    if second == "Another":
        with pytest.raises(SystemExit) as result:
            run_example(monkeypatch, "send_batch.py", path, "--apply", "--delay", 0)
        assert result.value.code == 1
        expected = []
    else:
        run_example(monkeypatch, "send_batch.py", path, "--apply", "--delay", 0)
        expected = ["contact-a", "other"]
    assert [params["buid"] for _, method, params in socket.calls if method == "send_im"] == expected


def test_batch_rejects_malformed_csv_before_login(monkeypatch, tmp_path, capsys):
    path = tmp_path / "batch.csv"
    path.write_text('contact;text\nEnem;"unfinished\n', encoding="utf-8")
    with pytest.raises(SystemExit) as result:
        run_example(monkeypatch, "send_batch.py", path, "--apply")
    assert result.value.code == 2
    assert "unexpected end" in capsys.readouterr().err


def test_history_and_download_examples(monkeypatch, scripted_socket, tmp_path, capsys):
    row = {
        "buid": "contact-a",
        "msg": "History message",
        "msg_id": "m1",
        "timestamp_nano_str": "800",
        "imdata": {"type": "photo_uploaded_2", "objects": [{"object_id": "imo/photo-history", "ext": "jpg"}]},
    }
    scripted_socket(history_pages={("900", 50): [row]})
    run_example(monkeypatch, "history.py", "contact-a", "--limit", 1, "--before", "900")
    exported = json.loads(capsys.readouterr().out)
    assert (exported["message_id"], exported["attachment_count"]) == ("m1", 1)
    assert "imdata" not in exported

    scripted_socket(history_pages={("900", 50): [row]})
    monkeypatch.setattr("imo._web_transport.WebTransport.now_ns", lambda _: 900)
    run_example(monkeypatch, "download_media.py", "contact-a", tmp_path, "--limit", 1)
    assert (tmp_path / "photo.jpg").read_bytes() == b"photo"


@pytest.mark.parametrize("script,args", [
    ("receive_one.py", ("--timeout", 1)),
    ("listen.py", ("--buid", "contact-a", "--count", 1)),
])
def test_incoming_examples(monkeypatch, scripted_socket, capsys, script, args):
    socket = scripted_socket()
    original_connect = IMOClient.connect

    def connect(client):
        original_connect(client)
        if script == "listen.py":
            socket.downlink(socket.envelope({
                "type": "conv", "name": "recv_im", "edata": {"buid": "other", "msg": "filtered"},
            }))
        socket.downlink(socket.envelope({
            "type": "conv", "name": "recv_im", "edata": {"buid": "contact-a", "msg": "Received"},
        }))

    monkeypatch.setattr(IMOClient, "connect", connect)
    run_example(monkeypatch, script, *args)
    assert capsys.readouterr().out == "contact-a\t\tReceived\n"
