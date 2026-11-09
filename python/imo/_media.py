"""Extract attachment metadata and stream IMO Web downloads to disk."""
from __future__ import annotations

import base64
from collections.abc import Mapping
from contextlib import closing
from dataclasses import dataclass, field
from http.client import HTTPException
import json
import os
from pathlib import Path
import re
from tempfile import NamedTemporaryFile
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from ._media_endpoints import media_url
from ._nerv import IMODownloadError, IMOAttachmentTooLarge, IMOAttachmentUnavailable, nerv_chunks
from ._web_transport import _ORIGIN


_KINDS = {
    "bigo_uploaded": "file", "file_uploaded": "file", "file": "file",
    "photo_uploaded": "photo", "photo_uploaded_2": "photo", "photo": "photo", "image": "photo",
    "video_uploaded": "video", "video_uploaded_2": "video", "video": "video",
    "audio_uploaded": "audio", "audio_uploaded_2": "audio", "audio": "audio", "voice": "audio",
    "gif": "gif",
}
_RESERVED = re.compile(r"(?:CON|PRN|AUX|NUL|(?:COM|LPT)[1-9\u00b9\u00b2\u00b3])(?:\.|$)", re.I)
_INVALID_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')
_EXT = re.compile(r"[A-Za-z0-9]{1,12}")
_OBJECT_ID = re.compile(r"[A-Za-z0-9_./=+-]{1,1024}")
_PIXEL_CHUNK = 12 * 1024


@dataclass(frozen=True)
class Attachment:
    """Downloadable file or media referenced by a single IMO message."""

    kind: str
    filename: str
    size: int | None
    _sources: tuple[tuple[str, str], ...] = field(repr=False)


def _first_text(*values):
    return next((value for value in values if isinstance(value, str) and value.strip()), "")


def _size(value):
    if type(value) is int and value >= 0:
        return value
    if isinstance(value, str) and len(value) <= 20 and value.isascii() and value.isdecimal():
        return int(value)
    return None


def _object_id(value):
    for prefix in ("imo/", "ngc/"):
        if value.startswith(prefix):
            value = value[len(prefix):]
            break
    if value.endswith("100x100"):
        value = value[:-len("100x100")]
    return value if _OBJECT_ID.fullmatch(value) else None


def _nerv_reference(value):
    if not value or len(value.encode("utf-8", "replace")) > 65535 or any(ord(c) <= 32 for c in value):
        return False
    if ":" in value.split("?", 1)[0] or value.startswith("//"):
        return media_url(value) is not None
    return True


def _attachment(obj, defaults, kind):
    bigo = _first_text(defaults.get("url") if kind == "file" else defaults.get("bigo_url"),
                       obj.get("bigo_url"), obj.get("url"), defaults.get("bigo_url"))
    legacy = _first_text(obj.get(kind), defaults.get(kind))
    pixel = _object_id(_first_text(obj.get("object_id"), defaults.get("object_id"),
                                   legacy if kind in ("photo", "video", "audio") else ""))
    http = media_url(_first_text(obj.get("http_url"), defaults.get("http_url"), legacy
                                 if kind in ("photo", "video", "audio", "gif") else "")) or media_url(bigo)
    sources = tuple((backend, ref) for backend, ref in (
        ("nerv", bigo if _nerv_reference(bigo) else None), ("pixel", pixel), ("https", http)
    ) if ref)
    if not sources:
        return None
    filename = _first_text(defaults.get("file_name"), obj.get("filename"), obj.get("file_name"))
    ext = _first_text(obj.get("ext"), defaults.get("ext"))
    if not filename:
        # A storage name is often opaque. Use it only to infer a file extension.
        try:
            path = urlsplit(bigo or http or "").path
            suffix = Path(unquote(path)).suffix.lstrip(".")
        except ValueError:
            suffix = ""
        if not _EXT.fullmatch(ext):
            ext = suffix if _EXT.fullmatch(suffix) else ("gif" if kind == "gif" else "bin")
        filename = f"{kind}.{ext.lower()}"
    size = next((size for size in map(_size, (obj.get("filesize"), obj.get("file_size"),
                                             defaults.get("file_size"))) if size is not None), None)
    return Attachment(kind, _safe_name(filename), size, sources)


def extract_attachments(message: Mapping) -> list[Attachment]:
    """Read originals from a history row, incoming message, or an imdata mapping."""
    if not isinstance(message, Mapping):
        raise TypeError("message must be a mapping")
    imdata = message.get("imdata", message)
    if isinstance(imdata, str):
        try:
            imdata = json.loads(imdata)
        except ValueError:
            return []
    if not isinstance(imdata, Mapping):
        return []
    root_type = _first_text(imdata.get("type"), imdata.get("object_type"))
    root_kind = _KINDS.get(root_type)
    if root_type and not root_kind and root_type != "im":
        return []
    objects = imdata.get("objects")
    objects = [obj for obj in objects if isinstance(obj, Mapping)] if isinstance(objects, list) else []
    if not objects:
        objects = [imdata]
    defaults = imdata if len(objects) == 1 and root_kind else {}
    attachments = []
    seen = set()
    for obj in objects:
        object_type = _first_text(obj.get("object_type"), obj.get("type"))
        kind = _KINDS.get(object_type) if object_type else root_kind
        if not kind:
            continue
        attachment = _attachment(obj, defaults, root_kind or kind)
        if attachment is not None and attachment._sources not in seen:
            seen.add(attachment._sources)
            attachments.append(attachment)
    return attachments


class _MediaRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = media_url(newurl)
        if not target:
            raise IMODownloadError("Attachment redirect left the IMO media domains")
        return super().redirect_request(req, fp, code, msg, headers, target)


def _https_chunks(url, timeout, max_bytes):
    url = media_url(url)
    if not url:
        raise IMODownloadError("Attachment URL is outside the IMO media domains")
    try:
        request = Request(url, headers={"Origin": _ORIGIN, "Accept-Encoding": "identity"})
        with build_opener(_MediaRedirects()).open(request, timeout=timeout) as response:
            if response.status != 200:
                raise IMODownloadError(f"Unexpected attachment HTTP status {response.status}")
            length = _size(response.headers.get("Content-Length"))
            if length is not None and length > max_bytes:
                raise IMOAttachmentTooLarge("Attachment exceeds max_bytes")
            received = 0
            while True:
                data = response.read(64 * 1024)
                if not data:
                    break
                received += len(data)
                if received > max_bytes:
                    raise IMOAttachmentTooLarge("Attachment exceeds max_bytes")
                yield data
            if length is not None and received != length:
                raise IMODownloadError("Incomplete HTTP attachment")
    except HTTPError as error:
        error.close()
        if error.code in (404, 410):
            raise IMOAttachmentUnavailable("HTTP attachment has expired or is unavailable") from None
        raise IMODownloadError(f"Attachment HTTP request failed ({error.code})") from None
    except (URLError, HTTPException, OSError, ValueError):
        raise IMODownloadError("Attachment HTTP connection failed") from None


def _pixel_chunks(request, ssid, object_id, max_bytes):
    start, size = 0, None
    while size is None or start < size:
        end = start + _PIXEL_CHUNK
        reply = request("pixeldownload", "get_photo", {
            "ssid": ssid, "object_id": object_id, "transform": {}, "ranges": [start, end],
        })
        if not isinstance(reply, dict):
            raise IMODownloadError("Invalid Pixel download response")
        if reply.get("result") == "fail":
            if reply.get("reason") in ("not_found", "not_exists"):
                raise IMOAttachmentUnavailable("Pixel attachment has expired or is unavailable")
            raise IMODownloadError("Pixel refused the attachment request")
        current_size = _size(reply.get("total"))
        if size is None:
            size = current_size
            if size is None:
                raise IMODownloadError("Pixel did not report an attachment size")
            if size > max_bytes:
                raise IMOAttachmentTooLarge("Attachment exceeds max_bytes")
        elif current_size not in (None, size):
            raise IMODownloadError("Pixel attachment size changed during download")
        try:
            encoded = reply["base64"]
            if not isinstance(encoded, str) or len(encoded) > 4 * ((_PIXEL_CHUNK + 2) // 3):
                raise ValueError
            data = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError, KeyError):
            raise IMODownloadError("Invalid Pixel attachment data") from None
        if len(data) != min(end, size) - start:
            raise IMODownloadError("Pixel returned an incomplete attachment range")
        yield data
        start = end


def _safe_name(filename):
    filename = _INVALID_NAME.sub("_", filename).strip(" .")
    if not filename:
        return "attachment.bin"
    if _RESERVED.match(filename):
        filename = "_" + filename
    stem, extension = os.path.splitext(filename)
    if len(extension.encode("utf-8", "replace")) > 24:
        stem, extension = filename, ""
    stem = stem.encode("utf-8", "replace")[:160].decode("utf-8", "ignore")
    return stem + extension


def _publish_download(temporary, directory, name):
    stem, ext = os.path.splitext(name)
    sequence = 0
    while True:
        candidate = directory / (name if sequence == 0 else f"{stem} ({sequence}){ext}")
        try:
            if os.name == "nt":
                os.rename(temporary, candidate)
            else:
                os.link(temporary, candidate)
            return candidate
        except FileExistsError:
            sequence += 1


def save_attachment(attachment, directory, *, request, ssid, uid, country, timeout, max_bytes):
    if not isinstance(attachment, Attachment):
        raise TypeError("attachment must come from extract_attachments")
    if type(max_bytes) is not int or max_bytes < 0:
        raise ValueError("max_bytes must be a nonnegative integer")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with NamedTemporaryFile(mode="w+b", dir=directory, prefix=".imo-", suffix=".part", delete=False) as file:
            temporary = file.name
            failures = []
            for backend, ref in attachment._sources:
                if backend == "nerv":
                    chunks = nerv_chunks(request, uid, country, ref, timeout, max_bytes)
                elif backend == "pixel":
                    chunks = _pixel_chunks(request, ssid, ref, max_bytes)
                else:
                    chunks = _https_chunks(ref, timeout, max_bytes)
                try:
                    with closing(chunks):
                        for data in chunks:
                            file.write(data)
                except IMOAttachmentTooLarge:
                    raise
                except IMODownloadError as error:
                    failures.append(error)
                    file.seek(0)
                    file.truncate()
                else:
                    break
            else:
                if len(failures) == 1 or (failures and all(isinstance(err, IMOAttachmentUnavailable)
                                                          for err in failures)):
                    raise failures[-1]
                details = ", ".join(str(error) for error in failures)
                raise IMODownloadError(f"Unable to download the attachment ({details})" if details
                                       else "Attachment has no supported download source")
        return _publish_download(temporary, directory, _safe_name(attachment.filename))
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)
