from __future__ import annotations

import json
import unittest

from src.webui.request_limits import RequestBodyLimitMiddleware, WEBUI_PATH_BODY_LIMITS


class RequestBodyLimitMiddlewareTest(unittest.IsolatedAsyncioTestCase):
    def test_chat_history_upload_has_an_explicit_large_body_limit(self) -> None:
        self.assertEqual(WEBUI_PATH_BODY_LIMITS["/api/webui/chat-history-imports"], 101 * 1024 * 1024)

    async def _request(
        self,
        *,
        chunks: list[bytes],
        limit: int = 4,
        headers: list[tuple[bytes, bytes]] | None = None,
        path: str = "/api/test",
        path_limits: dict[str, int] | None = None,
    ) -> tuple[list[dict], dict[str, bool]]:
        state = {"called": False, "completed": False}

        async def app(scope, receive, send):
            state["called"] = True
            while True:
                message = await receive()
                if not message.get("more_body", False):
                    break
            state["completed"] = True
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        messages = [
            {
                "type": "http.request",
                "body": chunk,
                "more_body": index < len(chunks) - 1,
            }
            for index, chunk in enumerate(chunks)
        ]
        if not messages:
            messages = [{"type": "http.request", "body": b"", "more_body": False}]

        async def receive():
            return messages.pop(0)

        sent: list[dict] = []

        async def send(message):
            sent.append(message)

        middleware = RequestBodyLimitMiddleware(app, default_limit=limit, path_limits=path_limits)
        await middleware(
            {
                "type": "http",
                "method": "POST",
                "path": path,
                "headers": headers or [],
            },
            receive,
            send,
        )
        return sent, state

    async def test_rejects_declared_oversized_body_before_calling_application(self) -> None:
        sent, state = await self._request(chunks=[b"ignored"], headers=[(b"content-length", b"5")])

        self.assertFalse(state["called"])
        self.assertEqual(sent[0]["status"], 413)

    async def test_rejects_chunked_body_that_exceeds_limit(self) -> None:
        sent, state = await self._request(chunks=[b"abc", b"de"])

        self.assertTrue(state["called"])
        self.assertFalse(state["completed"])
        self.assertEqual(sent[0]["status"], 413)
        self.assertEqual(json.loads(sent[1]["body"]), {"detail": "请求体过大"})

    async def test_allows_exact_limit_and_path_specific_override(self) -> None:
        exact, exact_state = await self._request(chunks=[b"abcd"], headers=[(b"content-length", b"4")])
        overridden, override_state = await self._request(
            chunks=[b"abcde"],
            headers=[(b"content-length", b"5")],
            path="/upload",
            path_limits={"/upload": 5},
        )

        self.assertTrue(exact_state["completed"])
        self.assertEqual(exact[0]["status"], 200)
        self.assertTrue(override_state["completed"])
        self.assertEqual(overridden[0]["status"], 200)

    async def test_rejects_invalid_or_conflicting_content_length(self) -> None:
        invalid, invalid_state = await self._request(chunks=[b""], headers=[(b"content-length", b"not-a-number")])
        conflicting, conflicting_state = await self._request(
            chunks=[b""],
            headers=[(b"content-length", b"1"), (b"content-length", b"2")],
        )

        self.assertFalse(invalid_state["called"])
        self.assertEqual(invalid[0]["status"], 400)
        self.assertFalse(conflicting_state["called"])
        self.assertEqual(conflicting[0]["status"], 400)


if __name__ == "__main__":
    unittest.main()
