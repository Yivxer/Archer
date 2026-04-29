import ipaddress
import socket
import urllib.error
import urllib.request
from urllib.parse import urljoin, urlparse


def validate_public_http_url(url: str) -> str:
    """Return a normalized URL if it is a public http(s) URL, otherwise raise."""
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https"):
        raise ValueError("只允许 http/https URL")
    if not parsed.hostname:
        raise ValueError("URL 缺少 hostname")

    host = parsed.hostname
    try:
        candidates = {ipaddress.ip_address(host)}
    except ValueError:
        try:
            infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        except socket.gaierror as e:
            raise ValueError(f"无法解析 hostname：{e}") from e
        candidates = {ipaddress.ip_address(info[4][0]) for info in infos}

    for ip in candidates:
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            raise ValueError("URL 指向本地或私有网络地址")

    return parsed.geturl()


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def open_public_http_url(
    url: str,
    *,
    headers: dict | None = None,
    timeout: int = 15,
    max_redirects: int = 5,
):
    """Open a public http(s) URL after validating every redirect target."""
    current = validate_public_http_url(url)
    opener = urllib.request.build_opener(NoRedirectHandler)
    request_headers = headers or {}

    for _ in range(max_redirects + 1):
        req = urllib.request.Request(current, headers=request_headers)
        try:
            return opener.open(req, timeout=timeout)
        except urllib.error.HTTPError as e:
            if e.code not in (301, 302, 303, 307, 308):
                raise
            location = e.headers.get("Location")
            if not location:
                raise
            current = validate_public_http_url(urljoin(current, location))

    raise ValueError("重定向次数过多")
