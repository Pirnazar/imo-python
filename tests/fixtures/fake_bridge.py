"""Stand-in for ImoBridge.exe: speaks the same JSON-lines protocol with canned data."""
import json
import sys

CHATS = [
    {"_type": "ChaterModel", "KeyID": "111", "ChatType": "Person_Chat", "LastMessageContent": "hi",
     "LastActivityTimestamp": 5, "ChatTarget": {"KeyID": "111", "Alias": "Mom", "IsGroup": False}},
    {"_type": "ChaterModel", "KeyID": "grp;", "ChatType": "Group_Chat", "LastActivityTimestamp": 9,
     "ChatTarget": {"KeyID": "grp;", "Display": "Work Group", "IsGroup": True}},
]
BUDDIES = [
    {"_type": "UserModel", "KeyID": "111", "Alias": "Mom", "IsGroup": False},
    {"_type": "UserModel", "KeyID": "222", "Alias": "Dad", "Remark": "Father", "AliasByRemark": "Father"},
    {"_type": "UserModel", "KeyID": "333", "Alias": "Fatima"},
]
GROUPS = [{"_type": "GroupModel", "KeyID": "grp;", "Display": "Work Group", "IsGroup": True}]
MESSAGE = {"_type": "TextMessage", "ConvBuid": "111", "Sender_buid": "111", "Msg": "ping",
           "MessageContentType": "Text", "TimestampNano": 42, "IsMyMessage": False,
           "Sender": {"KeyID": "111", "Alias": "Mom"}}

signed_on = "--signed-on" in sys.argv
no_ack = "--no-ack" in sys.argv
sent = []


def emit(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def action(kind, **extra):
    emit({"event": "action", "type": kind, "result_type": "Success", **extra})


emit({"event": "ready", "version": "0.0.0.0", "signed_on_before": signed_on})
for line in sys.stdin:
    cmd = json.loads(line)
    ident, name = cmd["id"], cmd["cmd"]

    def reply(result):
        emit({"id": ident, "ok": True, "result": result})

    if name == "connect":
        reply(True)
        action("SignalConnected")
    elif name == "status":
        reply({"signed_on": signed_on, "cookie_signed_on": signed_on, "uid": "999" if signed_on else None,
               "user": {"Alias": "Me"}})
    elif name == "request_qr":
        reply({"status": "success", "result": {"qr_link": "https://example.invalid/qr", "code_ttl": 60}})
        action("QrCodeScanned")
        action("QrCodeLoginCompleted")
        signed_on = True
        action("SignedOn")
    elif name == "run":
        kind = cmd["action"]
        if kind == "GetChaters":
            reply(None)
            action("GetChaters", data=CHATS)
        elif kind == "SyncBuddyList":
            reply(None)
            action("SyncBuddyList")
        elif kind == "GetAllBuddies":
            reply(BUDDIES)
        elif kind == "GetAllGroups":
            reply(GROUPS)
        else:
            emit({"id": ident, "ok": False, "error": "ArgumentException: " + kind})
    elif name == "send":
        if not signed_on:
            emit({"id": ident, "ok": False, "error": "InvalidOperationException: not signed on"})
            continue
        sent.append((cmd["buid"], cmd["text"]))
        reply({"queued": True})
        if not no_ack:
            emit({"event": "send_ack", "send_id": ident, "buid": cmd["buid"]})
        if cmd["text"] == "echo":
            action("MessageReceive", data=MESSAGE)
    elif name == "sent":
        reply(sent)
    elif name == "exit":
        reply(True)
        break
    else:
        emit({"id": ident, "ok": False, "error": "ArgumentException: unknown cmd"})
