import ipaddress
import ssl
import socket
import unittest
from unittest.mock import Mock, patch

from plugins.onebot_adapter.adapter_core import network


class FakeResponse:
    def __init__(self, *, status: int = 200, headers: dict[str, str] | None = None, chunks: list[bytes] | None = None):
        self.status = status
        self.headers = headers or {}
        self._chunks = list(chunks or [])
        self.closed = False

    def read(self, _amount: int) -> bytes:
        return self._chunks.pop(0) if self._chunks else b""

    def close(self) -> None:
        self.closed = True


class OneBotAdapterNetworkTest(unittest.TestCase):
    def test_resolve_media_target_pins_public_dns_and_rejects_unsafe_urls(self) -> None:
        public_answer = [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", 443))]

        with (
            patch.object(network.socket, "getaddrinfo", return_value=public_answer),
            patch.dict(network.os.environ, {}, clear=True),
        ):
            target = network.resolve_media_target("https://example.com/assets/a.png?size=2")

        self.assertEqual(target.hostname, "example.com")
        self.assertEqual(target.ip_address, ipaddress.ip_address("93.184.216.34"))
        self.assertEqual(target.port, 443)
        self.assertEqual(target.request_target, "/assets/a.png?size=2")
        self.assertEqual(target.host_header, "example.com")

        for unsafe_url in (
            "ftp://example.com/a.png",
            "https://user:secret@example.com/a.png",
            "https://example.com:8443/a.png",
            "https://example.com/a.png#fragment",
        ):
            with self.subTest(url=unsafe_url), patch.dict(network.os.environ, {}, clear=True):
                with self.assertRaises(network.MediaDownloadError):
                    network.resolve_media_target(unsafe_url)

    def test_resolve_media_target_rejects_mixed_or_link_local_dns_answers(self) -> None:
        mixed_answers = [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("127.0.0.1", 443)),
        ]
        link_local_answer = [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("169.254.169.254", 443))]

        with (
            patch.object(network.socket, "getaddrinfo", return_value=mixed_answers),
            patch.dict(network.os.environ, {}, clear=True),
        ):
            with self.assertRaises(network.MediaDownloadError):
                network.resolve_media_target("https://example.com/image.png")

        with (
            patch.object(network.socket, "getaddrinfo", return_value=link_local_answer),
            patch.dict(network.os.environ, {"MAIBOT_ALLOW_PRIVATE_MEDIA_URLS": "1"}, clear=True),
        ):
            with self.assertRaises(network.MediaDownloadError):
                network.resolve_media_target("https://metadata.invalid/image.png")

    def test_private_and_nonstandard_media_targets_require_explicit_opt_in(self) -> None:
        private_answer = [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("127.0.0.1", 8443))]

        with (
            patch.object(network.socket, "getaddrinfo", return_value=private_answer),
            patch.dict(
                network.os.environ,
                {
                    "MAIBOT_ALLOW_PRIVATE_MEDIA_URLS": "1",
                    "MAIBOT_ALLOW_NONSTANDARD_MEDIA_PORTS": "1",
                },
                clear=True,
            ),
        ):
            target = network.resolve_media_target("https://localhost:8443/image.png")

        self.assertEqual(target.ip_address, ipaddress.ip_address("127.0.0.1"))
        self.assertEqual(target.host_header, "localhost:8443")

    def test_dns_hostname_keeps_valid_host_header_when_pinned_to_ipv6_and_rejects_port_zero(self) -> None:
        ipv6_answer = [
            (
                socket.AF_INET6,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                ("2606:2800:220:1:248:1893:25c8:1946", 443, 0, 0),
            )
        ]

        with (
            patch.object(network.socket, "getaddrinfo", return_value=ipv6_answer),
            patch.dict(network.os.environ, {}, clear=True),
        ):
            target = network.resolve_media_target("https://example.com/image.png")
            with self.assertRaises(network.MediaDownloadError):
                network.resolve_media_target("https://example.com:0/image.png")

        self.assertEqual(target.host_header, "example.com")
        self.assertEqual(target.url, "https://example.com/image.png")

    def test_https_request_connects_to_pinned_ip_with_original_hostname_verification(self) -> None:
        target = network.MediaTarget(
            url="https://example.com/image.png",
            scheme="https",
            hostname="example.com",
            ip_address=ipaddress.ip_address("93.184.216.34"),
            port=443,
            request_target="/image.png",
            host_header="example.com",
        )
        pool = Mock()
        response = FakeResponse()
        pool.urlopen.return_value = response

        with patch.object(network.urllib3, "HTTPSConnectionPool", return_value=pool) as pool_class:
            returned_pool, returned_response = network._open_pinned_response(target)

        self.assertIs(returned_pool, pool)
        self.assertIs(returned_response, response)
        _, kwargs = pool_class.call_args
        self.assertEqual(kwargs["host"], "93.184.216.34")
        self.assertEqual(kwargs["assert_hostname"], "example.com")
        self.assertEqual(kwargs["server_hostname"], "example.com")
        self.assertGreaterEqual(kwargs["ssl_context"].minimum_version, ssl.TLSVersion.TLSv1_2)
        request_args, request_kwargs = pool.urlopen.call_args
        self.assertEqual(request_args[:2], ("GET", "/image.png"))
        self.assertEqual(request_kwargs["headers"]["Host"], "example.com")
        self.assertFalse(request_kwargs["redirect"])
        self.assertFalse(request_kwargs["preload_content"])

    def test_download_media_enforces_body_limit_and_revalidates_redirects(self) -> None:
        target = network.MediaTarget(
            url="https://example.com/image.png",
            scheme="https",
            hostname="example.com",
            ip_address=ipaddress.ip_address("93.184.216.34"),
            port=443,
            request_target="/image.png",
            host_header="example.com",
        )
        oversized_response = FakeResponse(
            headers={"Content-Type": "image/png"},
            chunks=[b"1234", b"5678"],
        )
        oversized_pool = Mock()

        with (
            patch.object(network, "resolve_media_target", return_value=target),
            patch.object(network, "_open_pinned_response", return_value=(oversized_pool, oversized_response)),
        ):
            with self.assertRaises(network.MediaDownloadError):
                network.download_media(target.url, max_bytes=7)

        self.assertTrue(oversized_response.closed)
        oversized_pool.close.assert_called_once_with()

        redirect_response = FakeResponse(status=302, headers={"Location": "http://127.0.0.1/private"})
        redirect_pool = Mock()
        with (
            patch.object(
                network,
                "resolve_media_target",
                side_effect=[target, network.MediaDownloadError("blocked redirect")],
            ) as resolve_target,
            patch.object(network, "_open_pinned_response", return_value=(redirect_pool, redirect_response)) as open_url,
        ):
            with self.assertRaises(network.MediaDownloadError):
                network.download_media(target.url)

        self.assertEqual(resolve_target.call_count, 2)
        open_url.assert_called_once_with(target)
        self.assertTrue(redirect_response.closed)
        redirect_pool.close.assert_called_once_with()

    def test_download_media_https_only_rejects_redirect_downgrade(self) -> None:
        https_target = network.MediaTarget(
            url="https://example.com/image.png",
            scheme="https",
            hostname="example.com",
            ip_address=ipaddress.ip_address("93.184.216.34"),
            port=443,
            request_target="/image.png",
            host_header="example.com",
        )
        http_target = network.MediaTarget(
            url="http://example.com/image.png",
            scheme="http",
            hostname="example.com",
            ip_address=ipaddress.ip_address("93.184.216.34"),
            port=80,
            request_target="/image.png",
            host_header="example.com",
        )
        redirect_response = FakeResponse(status=302, headers={"Location": http_target.url})
        redirected_response = FakeResponse(headers={"Content-Type": "image/png"}, chunks=[b"image"])
        redirect_pool = Mock()
        redirected_pool = Mock()

        with (
            patch.object(network, "resolve_media_target", side_effect=[https_target, http_target]),
            patch.object(
                network,
                "_open_pinned_response",
                side_effect=[(redirect_pool, redirect_response), (redirected_pool, redirected_response)],
            ) as open_url,
        ):
            with self.assertRaises(network.MediaDownloadError):
                network.download_media(https_target.url, https_only=True)

        open_url.assert_called_once_with(https_target)
        self.assertTrue(redirect_response.closed)
        redirect_pool.close.assert_called_once_with()
        self.assertFalse(redirected_response.closed)
        redirected_pool.close.assert_not_called()


if __name__ == "__main__":
    unittest.main()
