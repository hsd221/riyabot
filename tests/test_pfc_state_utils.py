import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from maim_message import UserInfo

from src.chat.brain_chat.PFC import message_sender
from src.chat.brain_chat.PFC.chat_observer import ChatObserver
from src.chat.brain_chat.PFC import pfc_utils
from src.chat.brain_chat.PFC.chat_states import (
    ChatState,
    ChatStateManager,
    Notification,
    NotificationManager,
    NotificationType,
    StateNotification,
    create_active_chat_notification,
    create_cold_chat_notification,
    create_new_message_notification,
)
from src.chat.brain_chat.PFC.conversation_info import ConversationInfo
from src.chat.brain_chat.PFC.message_storage import MongoDBMessageStorage, _message_to_pfc_dict
from src.chat.brain_chat.PFC.observation_info import ObservationInfo, ObservationInfoHandler
from src.chat.brain_chat.PFC.waiter import Waiter
from src.chat.message_receive.chat_stream import ChatStream
from src.common.data_models.database_data_model import DatabaseMessages
from maim_message import GroupInfo, Seg


class FakeNotificationHandler:
    def __init__(self) -> None:
        self.notifications = []

    async def handle_notification(self, notification: Notification) -> None:
        self.notifications.append(notification)


def make_database_message(message_id: str = "msg-1", *, group: bool = True) -> DatabaseMessages:
    return DatabaseMessages(
        message_id=message_id,
        time=12.5,
        chat_id="stream-1",
        processed_plain_text="hello",
        user_id="user-1",
        user_nickname="Alice",
        user_cardname="Ali",
        user_platform="qq",
        chat_info_group_id="group-1" if group else None,
        chat_info_group_name="Group" if group else None,
        chat_info_group_platform="qq" if group else None,
        chat_info_user_id="user-1",
        chat_info_user_nickname="Alice",
        chat_info_user_cardname="Ali",
        chat_info_user_platform="qq",
        chat_info_stream_id="stream-1",
        chat_info_platform="qq",
        chat_info_create_time=1.0,
        chat_info_last_active_time=2.0,
    )


class PFCJsonUtilsTest(unittest.TestCase):
    def test_get_items_from_json_extracts_objects_with_defaults_types_and_embedded_json(self) -> None:
        ok, result = pfc_utils.get_items_from_json(
            'prefix {"goal": "聊天", "reasoning": "继续", "score": 2} suffix',
            "Alice",
            "goal",
            "reasoning",
            "score",
            default_values={"score": 0},
            required_types={"goal": str, "score": int},
        )

        self.assertTrue(ok)
        self.assertEqual(result, {"score": 2, "goal": "聊天", "reasoning": "继续"})

        missing_ok, missing = pfc_utils.get_items_from_json(
            "{}",
            "Alice",
            "goal",
            default_values={"goal": "默认"},
        )
        self.assertTrue(missing_ok)
        self.assertEqual(missing, {"goal": "默认"})

    def test_get_items_from_json_filters_arrays_and_reports_invalid_content(self) -> None:
        ok, result = pfc_utils.get_items_from_json(
            """
            [
              {"goal": "有效", "reasoning": "ok", "score": 1},
              {"goal": "", "reasoning": "empty", "score": 2},
              {"goal": "bad type", "reasoning": "bad", "score": "high"},
              "not-object"
            ]
            """,
            "Alice",
            "goal",
            "reasoning",
            required_types={"score": int},
        )

        self.assertTrue(ok)
        self.assertEqual(result, [{"goal": "有效", "reasoning": "ok", "score": 1}])

        wrong_type_ok, wrong_type = pfc_utils.get_items_from_json(
            '{"goal": "有效", "score": "high"}',
            "Alice",
            "goal",
            "score",
            default_values={"fallback": True},
            required_types={"score": int},
        )
        empty_ok, empty = pfc_utils.get_items_from_json('{"goal": "   "}', "Alice", "goal")
        invalid_ok, invalid = pfc_utils.get_items_from_json("not json", "Alice", "goal", default_values={"x": 1})

        self.assertFalse(wrong_type_ok)
        self.assertEqual(wrong_type, {"fallback": True, "goal": "有效", "score": "high"})
        self.assertFalse(empty_ok)
        self.assertEqual(empty, {"goal": "   "})
        self.assertFalse(invalid_ok)
        self.assertEqual(invalid, {"x": 1})


class PFCChatStateTest(unittest.IsolatedAsyncioTestCase):
    async def test_notification_manager_dispatches_tracks_states_filters_history_and_unregisters(self) -> None:
        manager = NotificationManager()
        handler = FakeNotificationHandler()
        manager.register_handler("pfc", NotificationType.COLD_CHAT, handler)

        active = StateNotification(
            type=NotificationType.COLD_CHAT,
            timestamp=1.0,
            sender="observer",
            target="pfc",
            data={"is_cold": True},
            is_active=True,
        )
        inactive = StateNotification(
            type=NotificationType.COLD_CHAT,
            timestamp=2.0,
            sender="observer",
            target="pfc",
            data={"is_cold": False},
            is_active=False,
        )
        ignored_target = Notification(
            type=NotificationType.NEW_MESSAGE,
            timestamp=3.0,
            sender="observer",
            target="other",
            data={"message_id": "msg-1"},
        )

        await manager.send_notification(active)
        await manager.send_notification(ignored_target)

        self.assertEqual(handler.notifications, [active])
        self.assertTrue(manager.is_state_active(NotificationType.COLD_CHAT))
        self.assertEqual(manager.get_active_states(), {NotificationType.COLD_CHAT})
        self.assertEqual(manager.get_notification_history(sender="observer", target="pfc"), [active])
        self.assertEqual(manager.get_notification_history(limit=1), [ignored_target])
        self.assertIn("NotificationManager for pfc", str(manager))

        await manager.send_notification(inactive)
        self.assertFalse(manager.is_state_active(NotificationType.COLD_CHAT))
        self.assertEqual(handler.notifications, [active, inactive])

        manager.unregister_handler("pfc", NotificationType.COLD_CHAT, handler)
        await manager.send_notification(active)
        self.assertEqual(handler.notifications, [active, inactive])

    def test_notification_factories_and_state_manager_snapshot_history(self) -> None:
        message = {
            "message_id": "msg-1",
            "processed_plain_text": "hello",
            "detailed_plain_text": "[1] Alice: hello",
            "user_info": {"user_id": "user-1"},
            "time": 10.0,
            "ignored": "value",
        }

        new_message = create_new_message_notification("observer", "observation_info", message)
        cold = create_cold_chat_notification("observer", "pfc", True)
        active = create_active_chat_notification("observer", "pfc", False)

        self.assertEqual(new_message.to_dict()["type"], "NEW_MESSAGE")
        self.assertEqual(new_message.data["message_id"], "msg-1")
        self.assertNotIn("ignored", new_message.data)
        self.assertTrue(cold.is_active)
        self.assertEqual(cold.data, {"is_cold": True})
        self.assertFalse(active.is_active)
        self.assertEqual(active.data, {"is_active": False})

        manager = ChatStateManager()
        manager.update_state(ChatState.NEW_MESSAGE, last_message_time=100.0, last_speaker="Alice", ignored="x")
        manager.update_state(ChatState.SILENT, cold_duration=30.0)

        history = manager.get_state_history()
        self.assertEqual(manager.get_current_state_info().state, ChatState.SILENT)
        self.assertEqual(history[0].state, ChatState.NEW_MESSAGE)
        self.assertEqual(history[0].last_speaker, "Alice")
        self.assertEqual(history[0].cold_duration, 0.0)
        self.assertEqual(history[1].state, ChatState.SILENT)
        self.assertFalse(hasattr(manager.get_current_state_info(), "ignored"))

        fake_now = SimpleNamespace(now=Mock(return_value=SimpleNamespace(timestamp=Mock(return_value=165.0))))
        with patch("src.chat.brain_chat.PFC.chat_states.datetime", fake_now):
            self.assertTrue(manager.is_cold_chat(threshold=60.0))
            self.assertFalse(manager.is_active_chat(threshold=5.0))


class PFCMessageStorageAdapterTest(unittest.IsolatedAsyncioTestCase):
    def test_message_to_pfc_dict_rebuilds_nested_user_and_chat_info(self) -> None:
        converted = _message_to_pfc_dict(make_database_message())

        self.assertEqual(converted["message_id"], "msg-1")
        self.assertEqual(converted["user_info"]["user_nickname"], "Alice")
        self.assertEqual(converted["chat_info"]["stream_id"], "stream-1")
        self.assertEqual(converted["chat_info"]["user_info"]["user_id"], "user-1")
        self.assertEqual(converted["chat_info"]["group_info"]["group_id"], "group-1")

        private_converted = _message_to_pfc_dict(make_database_message(group=False))
        self.assertIsNone(private_converted["chat_info"]["group_info"])

    async def test_mongodb_message_storage_delegates_to_repository_with_pfc_shapes(self) -> None:
        storage = MongoDBMessageStorage()
        messages = [make_database_message("msg-1"), make_database_message("msg-2")]

        with (
            patch("src.chat.brain_chat.PFC.message_storage.find_messages", return_value=messages) as find_messages,
            patch("src.chat.brain_chat.PFC.message_storage.count_messages", return_value=1) as count_messages,
        ):
            after = await storage.get_messages_after("stream-1", 10.0)
            before = await storage.get_messages_before("stream-1", 20.0, limit=3)
            has_new = await storage.has_new_messages("stream-1", 15.0)

        self.assertEqual([item["message_id"] for item in after], ["msg-1", "msg-2"])
        self.assertEqual(before[0]["chat_info"]["stream_id"], "stream-1")
        self.assertTrue(has_new)
        self.assertEqual(
            find_messages.call_args_list[0].args,
            ({"chat_id": "stream-1", "time": {"$gt": 10.0}},),
        )
        self.assertEqual(find_messages.call_args_list[0].kwargs, {"sort": [("time", 1)]})
        self.assertEqual(
            find_messages.call_args_list[1].args,
            ({"chat_id": "stream-1", "time": {"$lt": 20.0}},),
        )
        self.assertEqual(find_messages.call_args_list[1].kwargs, {"limit": 3, "limit_mode": "latest"})
        count_messages.assert_called_once_with({"chat_id": "stream-1", "time": {"$gt": 15.0}})


class ObservationInfoTest(unittest.IsolatedAsyncioTestCase):
    async def test_update_from_message_tracks_latest_sender_counts_and_durations(self) -> None:
        info = ObservationInfo("Alice")
        info.bot_id = "bot"

        await info.update_from_message(
            {"message_id": "msg-1", "processed_plain_text": "hello", "time": 10.0},
            UserInfo(platform="qq", user_id="user-1", user_nickname="Alice"),
        )
        await info.update_from_message(
            {"message_id": "old", "processed_plain_text": "old", "time": 5.0},
            UserInfo(platform="qq", user_id="user-2", user_nickname="Bob"),
        )
        await info.update_from_message(
            {"message_id": "bot-msg", "processed_plain_text": "bot", "time": 12.0},
            UserInfo(platform="qq", user_id="bot", user_nickname="Mai"),
        )

        self.assertEqual(info.last_message_id, "bot-msg")
        self.assertEqual(info.last_message_sender, "bot")
        self.assertEqual(info.last_user_speak_time, 10.0)
        self.assertEqual(info.last_bot_speak_time, 12.0)
        self.assertEqual(info.active_users, {"user-1"})
        self.assertEqual(info.new_messages_count, 2)
        self.assertTrue(info.changed)

        with patch("src.chat.brain_chat.PFC.observation_info.time.time", return_value=20.0):
            self.assertEqual(info.get_active_duration(), 8.0)
            self.assertEqual(info.get_user_response_time(), 10.0)
            self.assertEqual(info.get_bot_response_time(), 8.0)

    async def test_cold_status_clear_history_and_bind_unbind_observer(self) -> None:
        info = ObservationInfo("Alice")
        await info.update_cold_chat_status(True, 100.0)
        self.assertTrue(info.is_cold_chat)
        self.assertEqual(info.cold_chat_start_time, 100.0)

        await info.update_cold_chat_status(True, 130.0)
        self.assertEqual(info.cold_chat_duration, 30.0)

        await info.update_cold_chat_status(False, 160.0)
        self.assertFalse(info.is_cold_chat)
        self.assertEqual(info.cold_chat_duration, 60.0)
        self.assertIsNone(info.cold_chat_start_time)

        info.chat_history = [{"message_id": f"old-{index}", "time": index} for index in range(90)]
        info.unprocessed_messages = [{"message_id": f"new-{index}", "time": index} for index in range(20)]
        info.new_messages_count = 20
        with patch("src.chat.brain_chat.PFC.observation_info.format_pfc_chat_history", return_value="formatted"):
            await info.clear_unprocessed_messages()

        self.assertEqual(len(info.chat_history), 100)
        self.assertEqual(info.chat_history[0]["message_id"], "old-10")
        self.assertEqual(info.chat_history_count, 100)
        self.assertEqual(info.chat_history_str, "formatted")
        self.assertEqual(info.unprocessed_messages, [])
        self.assertEqual(info.new_messages_count, 0)

        observer = SimpleNamespace(notification_manager=NotificationManager())
        info.bind_to_chat_observer(observer)
        self.assertIs(info.chat_observer, observer)
        self.assertIn("observation_info", observer.notification_manager._handlers)
        info.bind_to_chat_observer(observer)
        info.unbind_from_chat_observer()
        self.assertIsNone(info.chat_observer)
        self.assertEqual(observer.notification_manager._handlers, {})

    async def test_observation_handler_updates_info_for_notifications_and_ignores_bad_user_info(self) -> None:
        info = ObservationInfo("Alice")
        handler = ObservationInfoHandler(info, "Alice")

        await handler.handle_notification(
            Notification(
                type=NotificationType.NEW_MESSAGE,
                timestamp=1.0,
                sender="observer",
                target="observation_info",
                data={
                    "message_id": "msg-1",
                    "processed_plain_text": "hello",
                    "detailed_plain_text": "detail",
                    "user_info": {"platform": "qq", "user_id": "user-1", "user_nickname": "Alice"},
                    "time": 10.0,
                },
            )
        )
        await handler.handle_notification(
            Notification(
                type=NotificationType.NEW_MESSAGE,
                timestamp=2.0,
                sender="observer",
                target="observation_info",
                data={"message_id": "bad", "user_info": "invalid", "time": 11.0},
            )
        )

        self.assertEqual(info.last_message_id, "msg-1")
        self.assertEqual(info.new_messages_count, 1)

        with patch("src.chat.brain_chat.PFC.observation_info.time.time", return_value=50.0):
            await handler.handle_notification(
                StateNotification(
                    type=NotificationType.COLD_CHAT,
                    timestamp=3.0,
                    sender="observer",
                    target="observation_info",
                    data={"is_cold": True},
                    is_active=True,
                )
            )
            await handler.handle_notification(
                StateNotification(
                    type=NotificationType.ACTIVE_CHAT,
                    timestamp=4.0,
                    sender="observer",
                    target="observation_info",
                    data={"is_active": True},
                    is_active=True,
                )
            )
            await handler.handle_notification(
                Notification(
                    type=NotificationType.BOT_SPEAKING,
                    timestamp=5.0,
                    sender="observer",
                    target="observation_info",
                    data={},
                )
            )

        self.assertFalse(info.is_cold_chat)
        self.assertFalse(hasattr(info, "is_cold"))
        self.assertEqual(info.last_bot_speak_time, 50.0)

        info.unprocessed_messages = [{"message_id": "keep"}, {"message_id": "delete"}]
        await handler.handle_notification(
            Notification(
                type=NotificationType.MESSAGE_DELETED,
                timestamp=6.0,
                sender="observer",
                target="observation_info",
                data={"message_id": "delete"},
            )
        )
        await handler.handle_notification(
            Notification(
                type=NotificationType.USER_JOINED,
                timestamp=7.0,
                sender="observer",
                target="observation_info",
                data={"user_id": 42},
            )
        )
        await handler.handle_notification(
            Notification(
                type=NotificationType.USER_LEFT,
                timestamp=8.0,
                sender="observer",
                target="observation_info",
                data={"user_id": 42},
            )
        )

        self.assertEqual(info.unprocessed_messages, [{"message_id": "keep"}])
        self.assertNotIn("42", info.active_users)


class PFCWaiterTest(unittest.IsolatedAsyncioTestCase):
    async def test_wait_returns_when_new_message_arrives_or_timeout_adds_goal(self) -> None:
        waiter = Waiter.__new__(Waiter)
        waiter.private_name = "Alice"
        waiter.chat_observer = SimpleNamespace(new_message_after=Mock(return_value=True))

        with patch("src.chat.brain_chat.PFC.waiter.time", SimpleNamespace(time=Mock(return_value=100.0))):
            self.assertFalse(await waiter.wait(ConversationInfo()))

        waiter.chat_observer = SimpleNamespace(new_message_after=Mock(return_value=False))
        conversation_info = ConversationInfo()
        with (
            patch("src.chat.brain_chat.PFC.waiter.time", SimpleNamespace(time=Mock(side_effect=[100.0, 401.0]))),
            patch("src.chat.brain_chat.PFC.waiter.asyncio.sleep", new=AsyncMock()) as sleep,
        ):
            self.assertTrue(await waiter.wait(conversation_info))

        self.assertIn("等待了5.0分钟", conversation_info.goal_list[0]["goal"])
        sleep.assert_not_awaited()

    async def test_wait_listening_timeout_adds_listening_specific_goal(self) -> None:
        waiter = Waiter.__new__(Waiter)
        waiter.private_name = "Alice"
        waiter.chat_observer = SimpleNamespace(new_message_after=Mock(return_value=False))
        conversation_info = ConversationInfo()

        with (
            patch("src.chat.brain_chat.PFC.waiter.time", SimpleNamespace(time=Mock(side_effect=[100.0, 401.0]))),
            patch("src.chat.brain_chat.PFC.waiter.asyncio.sleep", new=AsyncMock()),
        ):
            self.assertTrue(await waiter.wait_listening(conversation_info))

        self.assertIn("话说一半突然消失", conversation_info.goal_list[0]["goal"])


class ChatObserverTest(unittest.IsolatedAsyncioTestCase):
    def tearDown(self) -> None:
        ChatObserver._instances.clear()

    async def test_singleton_check_fetch_and_cold_chat_notification_paths(self) -> None:
        ChatObserver._instances.clear()
        observer = ChatObserver.get_instance("stream-1", "Alice")

        self.assertIs(ChatObserver.get_instance("stream-1", "Alice"), observer)
        with self.assertRaises(RuntimeError):
            ChatObserver("stream-1", "Alice")

        observer.message_storage = SimpleNamespace(has_new_messages=AsyncMock(return_value=True))
        observer.last_check_time = 10.0
        with patch("src.chat.brain_chat.PFC.chat_observer.time", SimpleNamespace(time=Mock(return_value=20.0))):
            self.assertTrue(await observer.check())
        self.assertEqual(observer.last_check_time, 20.0)
        observer.message_storage.has_new_messages.assert_awaited_once_with("stream-1", 10.0)

        messages = [{"message_id": "msg-1", "time": 21.0}, {"message_id": "msg-2", "time": 22.0}]
        observer.message_storage = SimpleNamespace(
            get_messages_after=AsyncMock(return_value=messages),
            get_messages_before=AsyncMock(return_value=messages[:1]),
        )
        observer.last_message_time = 20.0

        self.assertEqual(await observer._fetch_new_messages(), messages)
        self.assertEqual(observer.last_message_read, messages[-1])
        self.assertEqual(observer.last_message_time, 22.0)
        self.assertEqual(await observer._fetch_new_messages_before(30.0), messages[:1])
        self.assertEqual(observer.last_message_read, "msg-1")

        handler = FakeNotificationHandler()
        observer.notification_manager.register_handler("pfc", NotificationType.COLD_CHAT, handler)
        observer.last_cold_chat_check = 0.0
        observer.last_message_time = 100.0
        observer.cold_chat_threshold = 50.0
        observer.is_cold_chat_state = False
        with patch("src.chat.brain_chat.PFC.chat_observer.time", SimpleNamespace(time=Mock(return_value=200.0))):
            await observer._check_cold_chat()

        self.assertTrue(observer.is_cold_chat_state)
        self.assertEqual(handler.notifications[0].type, NotificationType.COLD_CHAT)
        self.assertEqual(handler.notifications[0].data, {"is_cold": True})

    async def test_add_message_to_history_caches_notifies_and_history_filters_cache(self) -> None:
        observer = ChatObserver.get_instance("stream-2", "Alice")
        observer.last_message_time = 1.0
        observer.message_cache = [
            {
                "message_id": "old",
                "time": 1.0,
                "processed_plain_text": "old",
                "user_info": {"platform": "qq", "user_id": "user-1", "user_nickname": "Alice"},
            }
        ]
        handler = FakeNotificationHandler()
        observer.notification_manager.register_handler("observation_info", NotificationType.NEW_MESSAGE, handler)

        message = {
            "message_id": "msg-1",
            "time": 10.0,
            "processed_plain_text": "hello",
            "detailed_plain_text": "detail",
            "user_info": {"platform": "qq", "user_id": "user-2", "user_nickname": "Bob"},
        }
        with patch.object(observer, "_check_cold_chat", new=AsyncMock()) as check_cold:
            await observer._add_message_to_history(message)

        self.assertEqual(observer.message_cache[-1], message)
        self.assertEqual(handler.notifications[0].data["message_id"], "msg-1")
        check_cold.assert_awaited_once()
        self.assertTrue(observer.new_message_after(5.0))
        self.assertFalse(observer.new_message_after(20.0))
        self.assertEqual(observer.get_cached_messages(limit=1), [message])
        self.assertEqual(observer.get_last_message(), message)
        self.assertEqual(observer.get_message_history(start_time=5.0), [message])
        self.assertEqual(observer.get_message_history(user_id="user-1"), [observer.message_cache[0]])
        self.assertEqual(observer.get_message_history(end_time=5.0, limit=1), [observer.message_cache[0]])

        observer.message_cache = []
        self.assertIsNone(observer.get_last_message())

    async def test_wait_for_update_start_stop_and_time_info_helpers(self) -> None:
        observer = ChatObserver.get_instance("stream-3", "Alice")
        observer._update_complete.set()
        self.assertTrue(await observer.wait_for_update(timeout=0.01))

        observer._update_complete.clear()
        self.assertFalse(await observer.wait_for_update(timeout=0.001))

        observer._update_loop = AsyncMock()
        observer.start()
        self.assertTrue(observer._running)
        self.assertIsNotNone(observer._task)
        observer.stop()
        self.assertFalse(observer._running)
        self.assertTrue(observer._update_event.is_set())
        self.assertTrue(observer._update_complete.is_set())

        with patch("src.chat.brain_chat.PFC.chat_observer.time", SimpleNamespace(time=Mock(return_value=100.0))):
            observer.update_check_time()
            observer.update_bot_speak_time(90.0)
            observer.update_user_speak_time(80.0)
            time_info = observer.get_time_info()

        self.assertEqual(observer.last_check_time, 100.0)
        self.assertIn("距离你上次发言已经过去了10秒", time_info)
        self.assertIn("距离对方上次发言已经过去了20秒", time_info)
        self.assertEqual(str(observer), "ChatObserver for stream-3")


class DirectMessageSenderTest(unittest.IsolatedAsyncioTestCase):
    def make_stream(self) -> ChatStream:
        return ChatStream(
            stream_id="stream-1",
            platform="qq",
            user_info=UserInfo(platform="qq", user_id="user-1", user_nickname="Alice"),
            group_info=GroupInfo(platform="qq", group_id="group-1", group_name="Group"),
        )

    async def test_direct_message_sender_builds_processes_sends_and_stores_message(self) -> None:
        sender = message_sender.DirectMessageSender("Alice")
        sender.storage = SimpleNamespace(store_message=AsyncMock())
        fake_config = SimpleNamespace(BOT_QQ="bot", BOT_NICKNAME="Mai")

        with (
            patch.object(message_sender, "global_config", fake_config),
            patch("src.chat.brain_chat.PFC.message_sender.time", SimpleNamespace(time=Mock(return_value=123.45))),
            patch(
                "src.chat.message_receive.uni_message_sender._send_message", new=AsyncMock(return_value=True)
            ) as send,
        ):
            await sender.send_message(self.make_stream(), "你好")

        sent_message = send.await_args.args[0]
        self.assertEqual(sent_message.message_info.message_id, "dm123.45")
        self.assertEqual(sent_message.message_info.user_info.user_id, "bot")
        self.assertEqual(sent_message.message_segment, Seg(type="seglist", data=[Seg(type="text", data="你好")]))
        self.assertEqual(sent_message.processed_plain_text, "你好")
        send.assert_awaited_once_with(sent_message, show_log=True)
        sender.storage.store_message.assert_awaited_once_with(sent_message, sent_message.chat_stream)

    async def test_direct_message_sender_raises_when_send_fails_and_skips_storage(self) -> None:
        sender = message_sender.DirectMessageSender("Alice")
        sender.storage = SimpleNamespace(store_message=AsyncMock())
        fake_config = SimpleNamespace(BOT_QQ="bot", BOT_NICKNAME="Mai")

        with (
            patch.object(message_sender, "global_config", fake_config),
            patch("src.chat.brain_chat.PFC.message_sender.time", SimpleNamespace(time=Mock(return_value=1.0))),
            patch("src.chat.message_receive.uni_message_sender._send_message", new=AsyncMock(return_value=False)),
            self.assertRaises(RuntimeError),
        ):
            await sender.send_message(self.make_stream(), "你好")

        sender.storage.store_message.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
