"""Only public HTTP media, with bounded downloads and revalidated redirects."""
import ipaddress
import socket
import time
from contextlib import contextmanager
from urllib.parse import urlsplit, urljoin
import httpx

HEADERS = {"User-Agent": "Flowstate/1.0 (public traffic analysis)", "Accept": "*/*", "Digitraffic-User": "Flowstate/public-traffic-analysis"}


def validate_url(url):
    parsed = urlsplit(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Use a public http or https URL without embedded credentials.")
    if parsed.port not in (None, 80, 443):
        raise ValueError("Camera sources must use standard HTTP ports (80 or 443).")
    try:
        addresses = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError("The source hostname could not be resolved.") from exc
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError("Only publicly reachable camera sources are supported.")
    return url


@contextmanager
def open_media(url, timeout=35, accept="*/*"):
    """Open a public source, checking the destination of every redirect."""
    with httpx.Client(timeout=httpx.Timeout(timeout, connect=10), trust_env=False, headers={**HEADERS,"Accept":accept}) as client:
        for _ in range(5):
            validate_url(url)
            # This public image host returns an HTML placeholder unless the request
            # advertises browser/image support. Keep our application identity visible.
            media_headers = {"User-Agent": "Mozilla/5.0 (compatible; Flowstate/1.0; public traffic analysis)",
                             "Accept": "image/jpeg,image/png,*/*"} if urlsplit(url).hostname == "webcams.transport.nsw.gov.au" else {}
            with client.stream("GET", url, headers=media_headers) as response:
                if response.is_redirect:
                    url = urljoin(url, response.headers.get("location", ""))
                    continue
                response.raise_for_status()
                yield response
                return
    raise ValueError("The camera source redirected too many times.")


def download(url, limit=30_000_000, timeout=35, accept="*/*"):
    deadline = time.monotonic() + timeout
    with open_media(url, timeout, accept) as response:
        content = bytearray()
        for chunk in response.iter_bytes():
            if time.monotonic() > deadline:
                raise ValueError("The camera download exceeded its time limit.")
            content.extend(chunk)
            if len(content) > limit:
                raise ValueError("Camera media exceeds the download limit.")
        return bytes(content), {**dict(response.headers), "x-source-url": str(response.url)}
