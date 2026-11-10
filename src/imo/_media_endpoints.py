"""Storage endpoints used by the IMO Web attachment transports."""
from __future__ import annotations

import re
from urllib.parse import urlsplit


# Media links in messages may originate with other users. Use only provider domains.
_MEDIA_DOMAINS = ("imo.im", "imoim.net", "imostatic.com", "bigo.sg", "bigo.tv", "ppx520.com")
_HOST = re.compile(r"[a-z0-9-]+(?:\.[a-z0-9-]+)+")


def _allowed_host(host):
    return bool(host and _HOST.fullmatch(host) and
                any(host == domain or host.endswith("." + domain) for domain in _MEDIA_DOMAINS))


def media_url(value, *, websocket=False):
    if not isinstance(value, str) or not value or any(ord(char) <= 32 or ord(char) == 127 for char in value):
        return None
    if "\\" in value:
        return None
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError:
        return None
    scheme = "wss" if websocket else "https"
    if parts.scheme not in (("wss",) if websocket else ("http", "https")):
        return None
    if not _allowed_host(parts.hostname) or parts.username is not None or port not in (None, 443):
        return None
    if parts.fragment or (websocket and parts.query):
        return None
    return parts._replace(scheme=scheme).geturl()
