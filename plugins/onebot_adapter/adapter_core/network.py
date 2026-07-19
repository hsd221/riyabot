"""OneBot 适配器的受限媒体下载工具。"""

from __future__ import annotations

import ipaddress
import os
import socket
import ssl

from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

import urllib3


MAX_MEDIA_URL_LENGTH = 4096
MAX_MEDIA_BYTES = 20 * 1024 * 1024
MAX_MEDIA_REDIRECTS = 3
_READ_CHUNK_BYTES = 64 * 1024
_TRUE_VALUES = {"1", "true", "yes"}
_REDIRECT_STATUSES = {301, 302, 303, 307, 308}
_DEFAULT_PORTS = {"http": 80, "https": 443}
_SAFE_CONTENT_TYPES = {"application/octet-stream", "binary/octet-stream"}
# Clash 等代理会将公网域名映射到 RFC 2544 网段，只允许受信任媒体域通过该路径。
_PROXY_FAKE_IP_NETWORK = ipaddress.ip_network("198.18.0.0/15")
_TRUSTED_FAKE_IP_HOST_SUFFIXES = ("qpic.cn", "qq.com", "qq.com.cn", "qq.ugcimg.cn")


class MediaDownloadError(ValueError):
    """媒体 URL 或下载响应不满足安全约束。"""


@dataclass(frozen=True)
class MediaTarget:
    """经过校验并固定到单一 IP 的媒体请求目标。"""

    url: str
    scheme: str
    hostname: str
    ip_address: ipaddress.IPv4Address | ipaddress.IPv6Address
    port: int
    request_target: str
    host_header: str


def _env_enabled(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in _TRUE_VALUES


def _is_address_allowed(
    address: ipaddress.IPv4Address | ipaddress.IPv6Address,
    *,
    scheme: str,
    hostname: str,
    allow_private: bool,
) -> bool:
    if address.is_unspecified or address.is_multicast or address.is_reserved or address.is_link_local:
        return False
    if address.is_global:
        return True
    if isinstance(address, ipaddress.IPv4Address) and address in _PROXY_FAKE_IP_NETWORK:
        return scheme == "https" and any(
            hostname == suffix or hostname.endswith(f".{suffix}") for suffix in _TRUSTED_FAKE_IP_HOST_SUFFIXES
        )
    return allow_private and (address.is_private or address.is_loopback)


def _normalize_hostname(hostname: str) -> str:
    if not hostname or "%" in hostname:
        raise MediaDownloadError("媒体 URL 主机无效")

    try:
        return str(ipaddress.ip_address(hostname))
    except ValueError:
        try:
            normalized = hostname.encode("idna").decode("ascii").lower().rstrip(".")
        except UnicodeError as exc:
            raise MediaDownloadError("媒体 URL 主机无效") from exc
        if not normalized or len(normalized) > 253:
            raise MediaDownloadError("媒体 URL 主机无效") from None
        return normalized


def _resolve_addresses(hostname: str, port: int) -> set[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    try:
        literal_address = ipaddress.ip_address(hostname)
    except ValueError:
        try:
            answers = socket.getaddrinfo(
                hostname,
                port,
                family=socket.AF_UNSPEC,
                type=socket.SOCK_STREAM,
                proto=socket.IPPROTO_TCP,
            )
        except (OSError, socket.gaierror) as exc:
            raise MediaDownloadError("媒体 URL 主机解析失败") from exc

        addresses: set[ipaddress.IPv4Address | ipaddress.IPv6Address] = set()
        for family, _socket_type, _protocol, _canonical_name, socket_address in answers:
            if family not in {socket.AF_INET, socket.AF_INET6}:
                continue
            try:
                addresses.add(ipaddress.ip_address(socket_address[0]))
            except ValueError:
                continue
        if not addresses:
            raise MediaDownloadError("媒体 URL 主机解析失败") from None
        return addresses
    else:
        return {literal_address}


def resolve_media_target(url: str) -> MediaTarget:
    """校验媒体 URL、解析全部地址并固定一个安全目标 IP。"""
    if not isinstance(url, str) or not url or len(url) > MAX_MEDIA_URL_LENGTH:
        raise MediaDownloadError("媒体 URL 无效")
    if "\\" in url or any(ord(character) < 32 or ord(character) == 127 for character in url):
        raise MediaDownloadError("媒体 URL 无效")

    try:
        parsed = urlsplit(url)
        port = parsed.port
        raw_hostname = parsed.hostname
    except ValueError as exc:
        raise MediaDownloadError("媒体 URL 无效") from exc

    scheme = parsed.scheme.lower()
    if scheme not in _DEFAULT_PORTS or not parsed.netloc or raw_hostname is None:
        raise MediaDownloadError("媒体 URL 仅允许 HTTP 或 HTTPS")
    if parsed.username is not None or parsed.password is not None:
        raise MediaDownloadError("媒体 URL 不允许携带凭据")
    if parsed.fragment:
        raise MediaDownloadError("媒体 URL 不允许片段标识")

    hostname = _normalize_hostname(raw_hostname)
    default_port = _DEFAULT_PORTS[scheme]
    port = default_port if port is None else port
    if port < 1:
        raise MediaDownloadError("媒体 URL 端口无效")
    if port != default_port and not _env_enabled("MAIBOT_ALLOW_NONSTANDARD_MEDIA_PORTS"):
        raise MediaDownloadError("媒体 URL 使用了未允许的端口")

    addresses = _resolve_addresses(hostname, port)
    allow_private = _env_enabled("MAIBOT_ALLOW_PRIVATE_MEDIA_URLS")
    if any(
        not _is_address_allowed(address, scheme=scheme, hostname=hostname, allow_private=allow_private)
        for address in addresses
    ):
        raise MediaDownloadError("媒体 URL 指向未允许的网络地址")

    pinned_address = sorted(addresses, key=lambda address: (address.version, int(address)))[0]
    try:
        hostname_address = ipaddress.ip_address(hostname)
    except ValueError:
        display_hostname = hostname
    else:
        display_hostname = f"[{hostname}]" if isinstance(hostname_address, ipaddress.IPv6Address) else hostname
    host_header = display_hostname if port == default_port else f"{display_hostname}:{port}"
    path = parsed.path or "/"
    request_target = urlunsplit(("", "", path, parsed.query, ""))
    normalized_url = urlunsplit((scheme, host_header, path, parsed.query, ""))

    return MediaTarget(
        url=normalized_url,
        scheme=scheme,
        hostname=hostname,
        ip_address=pinned_address,
        port=port,
        request_target=request_target,
        host_header=host_header,
    )


def _open_pinned_response(target: MediaTarget) -> tuple[Any, Any]:
    """直连预解析 IP，同时保留原始 Host 与 HTTPS 主机名校验。"""
    timeout = urllib3.Timeout(connect=5.0, read=10.0)
    common_pool_options = {
        "host": str(target.ip_address),
        "port": target.port,
        "timeout": timeout,
        "maxsize": 1,
        "block": True,
        "retries": False,
    }

    if target.scheme == "https":
        ssl_context = ssl.create_default_context()
        ssl_context.minimum_version = ssl.TLSVersion.TLSv1_2
        pool = urllib3.HTTPSConnectionPool(
            **common_pool_options,
            assert_hostname=target.hostname,
            server_hostname=target.hostname,
            ssl_context=ssl_context,
        )
    else:
        pool = urllib3.HTTPConnectionPool(**common_pool_options)

    try:
        response = pool.urlopen(
            "GET",
            target.request_target,
            headers={
                "Host": target.host_header,
                "Accept": "image/*,application/octet-stream;q=0.5",
                "Accept-Encoding": "identity",
                "User-Agent": "RiyaBot-OneBotAdapter/1",
            },
            redirect=False,
            preload_content=False,
            retries=False,
            timeout=timeout,
        )
    except Exception:
        pool.close()
        raise
    return pool, response


def _validate_response_headers(response: Any, max_bytes: int) -> None:
    content_length = response.headers.get("Content-Length")
    if content_length is not None:
        try:
            declared_length = int(content_length)
        except (TypeError, ValueError) as exc:
            raise MediaDownloadError("媒体响应长度无效") from exc
        if declared_length < 0 or declared_length > max_bytes:
            raise MediaDownloadError("媒体响应过大")

    content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
    if content_type and not content_type.startswith("image/") and content_type not in _SAFE_CONTENT_TYPES:
        raise MediaDownloadError("媒体响应类型无效")


def _read_limited_response(response: Any, max_bytes: int) -> bytes:
    _validate_response_headers(response, max_bytes)
    chunks: list[bytes] = []
    total_bytes = 0
    while True:
        chunk = response.read(min(_READ_CHUNK_BYTES, max_bytes - total_bytes + 1))
        if not chunk:
            break
        total_bytes += len(chunk)
        if total_bytes > max_bytes:
            raise MediaDownloadError("媒体响应过大")
        chunks.append(bytes(chunk))
    return b"".join(chunks)


def _download_media(url: str, *, max_bytes: int, max_redirects: int, https_only: bool) -> bytes:
    if max_bytes <= 0 or max_redirects < 0:
        raise MediaDownloadError("媒体下载限制无效")

    current_url = url
    redirect_count = 0
    while True:
        target = resolve_media_target(current_url)
        if https_only and target.scheme != "https":
            raise MediaDownloadError("媒体 URL 仅允许 HTTPS")
        pool, response = _open_pinned_response(target)
        try:
            status = int(response.status)
            if status in _REDIRECT_STATUSES:
                if redirect_count >= max_redirects:
                    raise MediaDownloadError("媒体重定向次数过多")
                location = response.headers.get("Location")
                if not isinstance(location, str) or not location:
                    raise MediaDownloadError("媒体重定向地址无效")
                current_url = urljoin(target.url, location)
                redirect_count += 1
                continue
            if status != 200:
                raise MediaDownloadError(f"媒体服务返回异常状态: {status}")
            return _read_limited_response(response, max_bytes)
        finally:
            try:
                response.close()
            finally:
                pool.close()


def download_media(
    url: str,
    *,
    max_bytes: int = MAX_MEDIA_BYTES,
    max_redirects: int = MAX_MEDIA_REDIRECTS,
    https_only: bool = False,
) -> bytes:
    """下载受限媒体；https_only 会同时阻止重定向降级，异常中不包含 URL。"""
    try:
        return _download_media(url, max_bytes=max_bytes, max_redirects=max_redirects, https_only=https_only)
    except MediaDownloadError:
        raise
    except Exception as exc:
        raise MediaDownloadError("媒体下载失败") from exc
