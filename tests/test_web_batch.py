"""find_contact and send_many of the IMO Web client, on the scripted socket."""
import pytest

from imo import Chat, IMOClient, IMOContactNotFound, IMORequestError, IMOTimeoutError

from test_web_client import login, scripted  # noqa: F401  (scripted is a fixture)

BUDDIES = [
    {"buid": "mom", "alias": "Mom"},
    {"buid": "dad", "alias": "Dad", "note": "Father"},
    {"buid": "fatima", "alias": "Fatima  Nur", "display": "fatima_n"},
]


def sent_rows(sock):
    return [(params["buid"], params["msg"]) for _, method, params in sock.calls if method == "send_im"]


def test_find_contact_prefers_exact_names_and_rejects_ambiguity(scripted):
    scripted(buddies=BUDDIES)
    with IMOClient() as client:
        login(client)
        assert client.find_contact(" MOM ").buid == "mom"
        assert client.find_contact("father").buid == "dad"          # the note set for the contact
        assert client.find_contact("fatima nur").buid == "fatima"   # repeated spaces are ignored
        assert client.find_contact("nur").buid == "fatima"          # the only partial match
        with pytest.raises(IMOContactNotFound, match="2 contacts"):
            client.find_contact("fat")                              # Father and Fatima
        with pytest.raises(IMOContactNotFound, match="No contact"):
            client.find_contact("nobody")
        with pytest.raises(ValueError):
            client.find_contact("  ")


def test_send_many_reports_each_row_and_continues_after_rejection(scripted):
    sock = scripted(unconfirmed={"b"})
    with IMOClient() as client:
        login(client)
        results = client.send_many([("a", "Salam"), ("b", "Salam"), (Chat.from_record({"buid": "c"}), "Salam")],
                                   delay=0)
        assert [(r.target, r.ok) for r in results] == [("a", True), ("b", False), ("c", True)]
        assert results[0].sent.timestamp_nano == "901" and results[0].error is None
        assert isinstance(results[1].error, IMORequestError) and results[1].sent is None
        assert sent_rows(sock) == [("a", "Salam"), ("b", "Salam"), ("c", "Salam")]
        assert client.is_authenticated

        stopped = client.send_many([("b", "Salam"), ("a", "Salam")], delay=0, stop_on_error=True)
        assert [(r.target, r.ok) for r in stopped] == [("b", False)]


def test_send_many_resolves_names_with_one_contact_fetch(scripted):
    sock = scripted(buddies=BUDDIES)
    with IMOClient() as client:
        login(client)
        results = client.send_many([("Mom", "Salam"), ("Nobody", "Salam"), ("Father", "Salam")],
                                   delay=0, by_name=True)
        assert [(r.target, r.ok) for r in results] == [("Mom", True), ("Nobody", False), ("Father", True)]
        assert isinstance(results[1].error, IMOContactNotFound)
        assert sent_rows(sock) == [("mom", "Salam"), ("dad", "Salam")]
        assert [method for _, method, _ in sock.calls].count("sync_full_buddies") == 1


def test_send_many_validates_every_row_before_sending(scripted):
    sock = scripted()
    with IMOClient() as client:
        login(client)
        for rows in ([("a", "Salam"), ("b", " ")], [("a", "Salam"), ("", "Salam")], [("a", "Salam"), "bad"]):
            with pytest.raises(ValueError):
                client.send_many(rows, delay=0)
        with pytest.raises(ValueError):
            client.send_many([("a", "Salam")], delay=-1)
        with pytest.raises(ValueError):
            client.send_many([("a", "Salam")], jitter=1)
        assert sent_rows(sock) == []
        assert client.send_many([], delay=0) == []


def test_send_many_stops_when_the_session_is_lost(scripted):
    sock = scripted(timeout_on_send=True)
    with IMOClient() as client:
        login(client)
        results = client.send_many([("a", "Salam"), ("b", "Salam")], delay=0)
        assert len(results) == 1 and isinstance(results[0].error, IMOTimeoutError)
        assert sent_rows(sock) == [("a", "Salam")]                  # the unanswered send is never retried
        assert not client.is_authenticated


def test_send_many_pauses_between_rows_and_keeps_incoming_messages(scripted, monkeypatch):
    sock = scripted()
    with IMOClient() as client:
        login(client)
        pauses = []
        real_pause = client._pause

        def pause(seconds):
            pauses.append(seconds)
            sock.downlink(sock.envelope({"type": "conv", "name": "recv_im", "edata": {"msg": "during pause"}}))
            real_pause(0.01)

        monkeypatch.setattr(client, "_pause", pause)
        results = client.send_many([("a", "Salam"), ("b", "Salam"), ("c", "Salam")], delay=10, jitter=0.3)
        assert all(r.ok for r in results)
        assert len(pauses) == 2 and all(7 <= seconds <= 13 for seconds in pauses)   # none after the last row
        assert client.receive_message() == {"msg": "during pause"}
