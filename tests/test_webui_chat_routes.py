import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from peewee import SqliteDatabase

from src.common.database.database_model import BaseModel, Messages
from src.webui import chat_routes


TEST_MODELS = [Messages]


class FakeWebSocket:
    def __init__(
        self,
        *,
        fail_send: bool = False,
        cookies: dict[str, str] | None = None,
        receive_items: list | None = None,
    ) -> None:
        self.accepted = False
        self.closed: tuple[int, str] | None = None
        self.sent: list[dict] = []
        self.fail_send = fail_send
        self.cookies = cookies or {}
        self.receive_items = list(receive_items or [])

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, message: dict) -> None:
        if self.fail_send:
            raise RuntimeError("send failed")
        self.sent.append(message)

    async def close(self, code: int, reason: str) -> None:
        self.closed = (code, reason)

    async def receive_json(self):
        if not self.receive_items:
            raise chat_routes.WebSocketDisconnect(code=1000)
        item = self.receive_items.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


class WebUIChatRoutesTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.test_db = SqliteDatabase(":memory:")
        self.original_dbs = {model: model._meta.database for model in [BaseModel, *TEST_MODELS]}
        self.test_db.bind(TEST_MODELS, bind_refs=False, bind_backrefs=False)
        self.test_db.connect()
        self.test_db.create_tables(TEST_MODELS)
        self.config_patch = patch.object(
            chat_routes,
            "global_config",
            SimpleNamespace(bot=SimpleNamespace(nickname="璃夜", qq_account="bot-qq")),
        )
        self.config_patch.start()

    def tearDown(self) -> None:
        self.config_patch.stop()
        self.test_db.drop_tables(TEST_MODELS)
        self.test_db.close()
        for model, database in self.original_dbs.items():
            model._meta.set_database(database)

    def create_db_message(
        self,
        message_id: str,
        *,
        group_id: str,
        user_id: str,
        user_nickname: str,
        content: str,
        timestamp: float,
    ) -> Messages:
        return Messages.create(
            message_id=message_id,
            time=timestamp,
            chat_id=group_id,
            chat_info_stream_id=group_id,
            chat_info_platform="webui",
            chat_info_user_platform="webui",
            chat_info_user_id=user_id,
            chat_info_user_nickname=user_nickname,
            chat_info_user_cardname=None,
            chat_info_group_platform="webui",
            chat_info_group_id=group_id,
            chat_info_group_name="WebUI Group",
            chat_info_create_time=1.0,
            chat_info_last_active_time=timestamp,
            user_platform="webui",
            user_id=user_id,
            user_nickname=user_nickname,
            user_cardname=None,
            processed_plain_text=content,
            display_message=f"display:{content}",
        )


class ChatHistoryManagerTest(WebUIChatRoutesTestCase):
    async def test_history_manager_returns_oldest_first_and_classifies_webui_and_virtual_bot_messages(self) -> None:
        manager = chat_routes.ChatHistoryManager(max_messages=200)
        self.create_db_message(
            "m1",
            group_id=chat_routes.WEBUI_CHAT_GROUP_ID,
            user_id="webui_user_1",
            user_nickname="Alice",
            content="old",
            timestamp=1.0,
        )
        bot_message = self.create_db_message(
            "m2",
            group_id=chat_routes.WEBUI_CHAT_GROUP_ID,
            user_id="bot-qq",
            user_nickname="璃夜",
            content="middle",
            timestamp=2.0,
        )
        self.create_db_message(
            "m3",
            group_id=chat_routes.WEBUI_CHAT_GROUP_ID,
            user_id="webui_user_2",
            user_nickname="Bob",
            content="new",
            timestamp=3.0,
        )
        self.create_db_message(
            "other",
            group_id="other-group",
            user_id="webui_user_3",
            user_nickname="Other",
            content="ignored",
            timestamp=4.0,
        )

        history = manager.get_history(limit=2)

        self.assertEqual([item["id"] for item in history], ["m2", "m3"])
        self.assertEqual(history[0]["type"], "bot")
        self.assertEqual(history[0]["sender_id"], "bot")
        self.assertEqual(history[1]["type"], "user")

        virtual_group = f"{chat_routes.VIRTUAL_GROUP_ID_PREFIX}demo"
        virtual_bot = manager._message_to_dict(bot_message, virtual_group)
        virtual_user = manager._message_to_dict(
            self.create_db_message(
                "virtual-user",
                group_id=virtual_group,
                user_id="real-user",
                user_nickname="Real User",
                content="hello",
                timestamp=5.0,
            ),
            virtual_group,
        )

        self.assertTrue(virtual_bot["is_bot"])
        self.assertEqual(virtual_bot["sender_name"], "璃夜")
        self.assertFalse(virtual_user["is_bot"])
        self.assertEqual(virtual_user["sender_id"], "real-user")

    async def test_clear_history_deletes_only_target_group_and_route_wraps_result(self) -> None:
        manager = chat_routes.ChatHistoryManager()
        self.create_db_message(
            "default",
            group_id=chat_routes.WEBUI_CHAT_GROUP_ID,
            user_id="webui_user_1",
            user_nickname="Alice",
            content="default",
            timestamp=1.0,
        )
        self.create_db_message(
            "other",
            group_id="other-group",
            user_id="webui_user_2",
            user_nickname="Bob",
            content="other",
            timestamp=2.0,
        )

        deleted = manager.clear_history(chat_routes.WEBUI_CHAT_GROUP_ID)

        self.assertEqual(deleted, 1)
        self.assertEqual(Messages.select().count(), 1)
        self.assertEqual(Messages.get().message_id, "other")

        fake_history = SimpleNamespace(clear_history=Mock(return_value=3))
        with patch.object(chat_routes, "chat_history", fake_history):
            response = await chat_routes.clear_chat_history(group_id="group-x", _auth=True)

        self.assertEqual(response, {"success": True, "message": "已清空 3 条聊天记录"})
        fake_history.clear_history.assert_called_once_with("group-x")


class ChatConnectionManagerTest(unittest.IsolatedAsyncioTestCase):
    async def test_connection_manager_tracks_sessions_sends_and_broadcasts_without_failing_on_send_error(self) -> None:
        manager = chat_routes.ChatConnectionManager()
        first = FakeWebSocket()
        second = FakeWebSocket(fail_send=True)

        await manager.connect(first, "session-1", "user-1")
        await manager.connect(second, "session-2", "user-2")
        await manager.send_message("session-1", {"type": "direct"})
        await manager.broadcast({"type": "broadcast"})
        manager.disconnect("session-1", "user-1")

        self.assertTrue(first.accepted)
        self.assertTrue(second.accepted)
        self.assertEqual(first.sent, [{"type": "direct"}, {"type": "broadcast"}])
        self.assertNotIn("session-1", manager.active_connections)
        self.assertNotIn("user-1", manager.user_sessions)
        self.assertIn("session-2", manager.active_connections)

    async def test_chat_websocket_caps_connections_and_rejects_oversized_messages(self) -> None:
        full_manager = chat_routes.ChatConnectionManager()
        full_manager.active_connections["existing"] = FakeWebSocket()
        rejected = FakeWebSocket()

        with (
            patch.object(chat_routes, "chat_manager", full_manager),
            patch.object(chat_routes, "MAX_CHAT_WS_CONNECTIONS", 1),
            patch.object(chat_routes, "verify_ws_token", return_value=True),
        ):
            await chat_routes.websocket_chat(rejected, token="valid")

        self.assertFalse(rejected.accepted)
        self.assertEqual(rejected.closed, (1013, "连接数过多，请稍后重试"))

        manager = chat_routes.ChatConnectionManager()
        oversized = FakeWebSocket(
            receive_items=[
                {"type": "message", "content": "12345", "user_name": "Alice"},
                chat_routes.WebSocketDisconnect(code=1000),
            ]
        )
        message_process = Mock()

        with (
            patch.object(chat_routes, "chat_manager", manager),
            patch.object(chat_routes, "MAX_CHAT_MESSAGE_CHARS", 4),
            patch.object(chat_routes, "verify_ws_token", return_value=True),
            patch.object(chat_routes.chat_history, "get_history", return_value=[]),
            patch.object(chat_routes.chat_bot, "message_process", message_process),
        ):
            await chat_routes.websocket_chat(oversized, user_id="user", user_name="Alice", token="valid")

        self.assertTrue(oversized.accepted)
        self.assertTrue(
            any(item.get("type") == "error" and "过长" in item.get("content", "") for item in oversized.sent)
        )
        message_process.assert_not_called()


class MessageDataAndRouteWrapperTest(WebUIChatRoutesTestCase):
    async def test_create_message_data_uses_default_webui_identity_and_virtual_identity_overrides(self) -> None:
        with patch.object(chat_routes.time, "time", return_value=123.0):
            standard = chat_routes.create_message_data(
                content="你好",
                user_id="webui_user_1",
                user_name="Alice",
                message_id="message-1",
                is_at_bot=False,
            )

        self.assertEqual(standard["message_info"]["platform"], "webui")
        self.assertEqual(standard["message_info"]["group_info"]["group_id"], chat_routes.WEBUI_CHAT_GROUP_ID)
        self.assertEqual(standard["message_info"]["user_info"]["user_id"], "webui_user_1")
        self.assertFalse(standard["message_info"]["additional_config"]["at_bot"])
        self.assertEqual(standard["message_info"]["time"], 123.0)
        self.assertEqual(standard["processed_plain_text"], "你好")

        virtual_config = chat_routes.VirtualIdentityConfig(
            enabled=True,
            platform="qq",
            person_id="person-1",
            user_id="real-user",
            user_nickname="Real Name",
            group_id="virtual-group",
            group_name="虚拟群",
        )
        with patch.object(chat_routes.time, "time", return_value=456.0):
            virtual = chat_routes.create_message_data(
                content="虚拟消息",
                user_id="webui_user_1",
                user_name="Alice",
                message_id="message-2",
                virtual_config=virtual_config,
            )

        self.assertEqual(virtual["message_info"]["platform"], "qq")
        self.assertEqual(virtual["message_info"]["group_info"]["group_id"], "virtual-group")
        self.assertEqual(virtual["message_info"]["group_info"]["group_name"], "虚拟群")
        self.assertEqual(virtual["message_info"]["user_info"]["user_id"], "real-user")
        self.assertEqual(virtual["message_info"]["user_info"]["user_nickname"], "Real Name")

    async def test_route_wrappers_delegate_to_profile_and_history_helpers(self) -> None:
        fake_history = SimpleNamespace(get_history=Mock(return_value=[{"id": "m1"}]))
        with patch.object(chat_routes, "chat_history", fake_history):
            history = await chat_routes.get_chat_history(limit=20, user_id="ignored", group_id=None, _auth=True)

        self.assertEqual(history, {"success": True, "messages": [{"id": "m1"}], "total": 1})
        fake_history.get_history.assert_called_once_with(20, chat_routes.WEBUI_CHAT_GROUP_ID)

        with patch.object(chat_routes, "get_profile_person_stats", return_value={"platforms": {"qq": 2, "discord": 1}}):
            platforms = await chat_routes.get_available_platforms(_auth=True)
        self.assertEqual(
            platforms,
            {"success": True, "platforms": [{"platform": "qq", "count": 2}, {"platform": "discord", "count": 1}]},
        )

        persons_data = [
            {
                "person_id": "person-1",
                "user_id": "u1",
                "person_name": "Alice",
                "nickname": "Ali",
                "platform": "qq",
                "is_known": True,
                "extra": "not returned",
            }
        ]
        with patch.object(chat_routes, "list_profile_person_dicts", return_value=persons_data) as list_people:
            persons = await chat_routes.get_persons_by_platform(platform="qq", search="Ali", limit=5, _auth=True)

        list_people.assert_called_once_with(search="Ali", platform="qq", is_known=True, limit=5)
        self.assertEqual(persons["total"], 1)
        self.assertNotIn("extra", persons["persons"][0])

    async def test_chat_info_broadcaster_and_websocket_auth_rejection_are_isolated(self) -> None:
        manager = chat_routes.ChatConnectionManager()
        manager.active_connections["session"] = FakeWebSocket()

        with patch.object(chat_routes, "chat_manager", manager):
            info = await chat_routes.get_chat_info(_auth=True)
            broadcaster = chat_routes.get_webui_chat_broadcaster()

        self.assertEqual(info["bot_name"], "璃夜")
        self.assertEqual(info["platform"], chat_routes.WEBUI_CHAT_PLATFORM)
        self.assertEqual(info["active_sessions"], 1)
        self.assertIs(broadcaster[0], manager)
        self.assertEqual(broadcaster[1], chat_routes.WEBUI_CHAT_PLATFORM)

        websocket = FakeWebSocket()
        with (
            patch.object(chat_routes, "verify_ws_token", return_value=False),
            patch.object(
                chat_routes, "get_token_manager", return_value=SimpleNamespace(verify_token=Mock(return_value=False))
            ),
        ):
            await chat_routes.websocket_chat(websocket, token="bad-token")

        self.assertEqual(websocket.closed, (4001, "认证失败，请重新登录"))


if __name__ == "__main__":
    unittest.main()
