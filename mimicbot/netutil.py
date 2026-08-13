"""HTTPS media URL checks for MimicBot — no downloads.

Validates that a link is https + public host + allowed type (gif/png/jpg/mp4)
so Discord can show the preview. MimicBot never fetches the file onto the host PC.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

_BLOCKED_HOSTS = frozenset(
    {
        "localhost",
        "localhost.localdomain",
        "metadata.google.internal",
        "metadata.google",
        "metadata",
    }
)

# Stickers use Discord sticker ids/names — not URLs.
ALLOWED_MEDIA_EXTS = frozenset({"gif", "png", "jpg", "jpeg", "mp4"})


def _host_is_public(hostname: str) -> bool:
    host = (hostname or "").strip().lower().rstrip(".")
    if not host or host in _BLOCKED_HOSTS:
        return False
    if host.endswith(".localhost") or host.endswith(".local") or host.endswith(".internal"):
        return False

    try:
        ip = ipaddress.ip_address(host)
        return not (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        )
    except ValueError:
        pass

    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False

    if not infos:
        return False

    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            return False
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            return False
    return True


def assert_public_https_url(url: str) -> str:
    """Validate https URL whose host resolves only to public IPs. Returns cleaned URL."""
    text = (url or "").strip()
    if text.startswith("http://"):
        raise ValueError("url must be https (http is not allowed)")
    if not text.startswith("https://"):
        raise ValueError("url must be https")
    parsed = urlparse(text)
    if parsed.scheme != "https":
        raise ValueError("url must be https")
    if parsed.username or parsed.password:
        raise ValueError("url must not include credentials")
    host = parsed.hostname
    if not host or not _host_is_public(host):
        raise ValueError("url host must be a public internet address (no localhost/private/LAN)")
    return text


assert_public_http_url = assert_public_https_url  # back-compat alias


def _ext_from_url(url: str) -> str | None:
    path = urlparse(url).path or ""
    name = path.rsplit("/", 1)[-1].split("?")[0].strip().lower()
    if "." not in name:
        return None
    ext = name.rsplit(".", 1)[-1]
    if ext == "jpeg":
        return "jpg"
    return ext if ext in ALLOWED_MEDIA_EXTS else None


def assert_media_url(
    url: str,
    *,
    allowed: frozenset[str] = ALLOWED_MEDIA_EXTS,
) -> tuple[str, str]:
    """
    Validate a media URL for Discord link/embed posting (no download).
    Returns (cleaned_https_url, ext) where ext is gif|png|jpg|mp4.
    """
    cleaned = assert_public_https_url(url)
    ext = _ext_from_url(cleaned)
    if ext == "jpeg":
        ext = "jpg"
    if not ext or ext not in allowed:
        allowed_txt = ", ".join(sorted({e for e in allowed if e != "jpeg"}))
        raise ValueError(
            f"media url must be https and end with .{'/ .'.join(sorted({e for e in allowed if e != 'jpeg'}))} "
            f"(got {ext or 'unknown'})"
        )
    return cleaned, ext


def is_image_ext(ext: str) -> bool:
    return ext in {"gif", "png", "jpg", "jpeg"}
