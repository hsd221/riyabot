import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from maim_message import GroupInfo, UserInfo

from src.chat.heart_flow import heartFC_chat, heartflow, heartflow_message_processor
from src.chat.message_receive.chat_stream import ChatStream
from src.common.data_models.database_data_model import DatabaseMessages
from src.common.data_models.info_data_model import ActionPlannerInfo
from src.common.data_models.message_data_model import ReplyContent, ReplyContentType, ReplySetModel
from src.plugin_system.base.component_types import ActionInfo, ComponentType


def make_stream(*, group: bool = True) -> ChatStream:
    return ChatStream(
        stream_id="stream-1",
        platform="qq",
        user_info=UserInfo(platform="qq", user_id="user-1", user_nickname="Alice", user_cardname="Ali"),
        group_info=GroupInfo(platform="qq", group_id="group-1", group_name="Group") if group else None,
    )


def make_db_message(message_id: str = "msg-1", *, text: str = "hello") -> DatabaseMessages:
    return DatabaseMessages(
        message_id=message_id,
        time=10.0,
        chat_id="stream-1",
        processed_plain_text=text,
        user_id="user-1",
        user_nickname="Alice",
        user_platform="qq",
        chat_info_stream_id="stream-1",
        chat_info_platform="qq",
        chat_info_user_id="user-1",
        chat_info_user_nickname="Alice",
        chat_info_user_platform="qq",
    )


def make_action_info(name: str) -> ActionInfo:
    return ActionInfo(name=name, component_type=ComponentType.ACTION, description=f"{name} desc")


def make_hfc() -> heartFC_chat.HeartFChatting:
    chat = heartFC_chat.HeartFChatting.__new__(heartFC_chat.HeartFChatting)
    chat.stream_id = "stream-1"
    chat.chat_stream = make_stream()
    chat.log_prefix = "[stream-1]"
    chat.running = False
    chat._loop_task = None
    chat.history_loop = []
    chat._cycle_counter = 0
    chat._current_cycle_detail = None
    chat.last_read_time = 1.0
    chat.last_active_time = 1.0
    chat.consecutive_no_reply_count = 0
    chat.questioned = False
    chat.action_manager = SimpleNamespace()
    chat.turn_scheduler = SimpleNamespace()
    chat.message_archiver = None
    chat.topic_summarizer = None
    return chat


class HeartflowCoordinatorTest(unittest.IsolatedAsyncioTestCase):
    async def test_get_or_create_heartflow_chat_caches_group_and_private_chat_instances(self) -> None:
        class FakeGroupChat:
            def __init__(self, chat_id: str):
                self.chat_id = chat_id
                self.started = False

            async def start(self):
                self.started = True

        class FakePrivateChat(FakeGroupChat):
            pass

        coordinator = heartflow.Heartflow()
        fake_manager = SimpleNamespace(get_stream=Mock(return_value=make_stream(group=True)))

        with (
            patch.object(heartflow, "get_chat_manager", return_value=fake_manager),
            patch.object(heartflow, "HeartFChatting", FakeGroupChat),
            patch.object(heartflow, "BrainChatting", FakePrivateChat),
        ):
            group_chat = await coordinator.get_or_create_heartflow_chat("group")
            cached = await coordinator.get_or_create_heartflow_chat("group")

        self.assertIs(group_chat, cached)
        self.assertIsInstance(group_chat, FakeGroupChat)
        self.assertTrue(group_chat.started)

        coordinator = heartflow.Heartflow()
        fake_manager = SimpleNamespace(get_stream=Mock(return_value=make_stream(group=False)))
        with (
            patch.object(heartflow, "get_chat_manager", return_value=fake_manager),
            patch.object(heartflow, "HeartFChatting", FakeGroupChat),
            patch.object(heartflow, "BrainChatting", FakePrivateChat),
        ):
            private_chat = await coordinator.get_or_create_heartflow_chat("private")

        self.assertIsInstance(private_chat, FakePrivateChat)

        coordinator = heartflow.Heartflow()
        fake_manager = SimpleNamespace(get_stream=Mock(return_value=None))
        with patch.object(heartflow, "get_chat_manager", return_value=fake_manager):
            self.assertIsNone(await coordinator.get_or_create_heartflow_chat("missing"))


class HeartFCMessageReceiverTest(unittest.IsolatedAsyncioTestCase):
    async def test_process_message_stores_message_updates_flags_logs_picids_and_registers_person(self) -> None:
        receiver = heartflow_message_processor.HeartFCMessageReceiver.__new__(
            heartflow_message_processor.HeartFCMessageReceiver
        )
        receiver.storage = SimpleNamespace(store_message=AsyncMock())
        message = SimpleNamespace(
            is_notify=False,
            processed_plain_text="看图 [picid:img-1] @<Bob:u2>",
            is_mentioned=False,
            is_at=False,
            reply_probability_boost=0.0,
            chat_stream=make_stream(),
            message_info=SimpleNamespace(
                platform="qq",
                user_info=SimpleNamespace(
                    platform="qq",
                    user_id="user-1",
                    user_nickname="Alice",
                    user_cardname="AliCard",
                ),
            ),
        )
        image_record = SimpleNamespace(description="图片描述")

        with (
            patch.object(heartflow_message_processor, "is_mentioned_bot_in_message", return_value=(True, True, 1.0)),
            patch.object(
                heartflow_message_processor.heartflow,
                "get_or_create_heartflow_chat",
                new=AsyncMock(return_value=object()),
            ) as get_chat,
            patch.object(heartflow_message_processor.Images, "get_or_none", return_value=image_record),
            patch.object(
                heartflow_message_processor,
                "replace_user_references",
                return_value="看图 [图片：图片描述] @Bob",
            ),
            patch.object(heartflow_message_processor.Person, "register_person", return_value=object()) as register,
        ):
            await receiver.process_message(message)

        self.assertTrue(message.is_mentioned)
        self.assertTrue(message.is_at)
        self.assertEqual(message.reply_probability_boost, 1.0)
        receiver.storage.store_message.assert_awaited_once_with(message, message.chat_stream)
        get_chat.assert_awaited_once_with("stream-1")
        register.assert_called_once_with(
            platform="qq",
            user_id="user-1",
            nickname="Alice",
            group_id="group-1",
            group_nick_name="AliCard",
        )

        notify = SimpleNamespace(is_notify=True)
        receiver.storage.store_message.reset_mock()
        await receiver.process_message(notify)
        receiver.storage.store_message.assert_not_called()


class HeartFChattingLifecycleTest(unittest.IsolatedAsyncioTestCase):
    async def test_start_cycle_end_cycle_start_and_loop_completion_are_stable(self) -> None:
        chat = make_hfc()
        fake_task = SimpleNamespace(add_done_callback=Mock())

        def fake_create_task(coro):
            coro.close()
            return fake_task

        async def never_run():
            return None

        chat._main_chat_loop = never_run
        with patch.object(heartFC_chat.asyncio, "create_task", side_effect=fake_create_task):
            await chat.start()
            await chat.start()

        self.assertTrue(chat.running)
        self.assertIs(chat._loop_task, fake_task)
        fake_task.add_done_callback.assert_called_once_with(chat._handle_loop_completion)

        with patch.object(heartFC_chat.time, "time", return_value=10.25):
            timers, thinking_id = chat.start_cycle()
            chat.end_cycle(
                {
                    "loop_plan_info": {"ok": True},
                    "loop_action_info": {"action_taken": False},
                },
                {"step": 0.2},
            )

        self.assertEqual(timers, {})
        self.assertEqual(thinking_id, "tid10.25")
        self.assertEqual(len(chat.history_loop), 1)
        self.assertEqual(chat.history_loop[0].timers, {"step": 0.2})

        done = asyncio.Future()
        done.set_result(None)
        chat._handle_loop_completion(done)

        failed = asyncio.Future()
        failed.set_exception(RuntimeError("loop down"))
        chat._handle_loop_completion(failed)

    async def test_loopbody_sleeps_when_scheduler_says_wait_or_observes_with_force_message(self) -> None:
        chat = make_hfc()
        recent = [make_db_message()]
        force = make_db_message("force")
        chat._observe = AsyncMock(return_value=True)
        wait_decision = SimpleNamespace(
            should_update_last_read_time=True,
            should_observe=False,
            sleep_seconds=0.5,
            force_reply_message=None,
        )
        chat.turn_scheduler = SimpleNamespace(decide_group_turn=Mock(return_value=wait_decision))

        with (
            patch.object(heartFC_chat.message_api, "get_messages_by_time_in_chat", return_value=recent),
            patch.object(heartFC_chat.time, "time", return_value=20.0),
            patch.object(heartFC_chat.asyncio, "sleep", new=AsyncMock()) as sleep,
        ):
            self.assertTrue(await chat._loopbody())

        self.assertEqual(chat.last_read_time, 20.0)
        sleep.assert_awaited_once_with(0.5)
        chat._observe.assert_not_awaited()

        observe_decision = SimpleNamespace(
            should_update_last_read_time=False,
            should_observe=True,
            sleep_seconds=0.0,
            force_reply_message=force,
        )
        chat.turn_scheduler = SimpleNamespace(decide_group_turn=Mock(return_value=observe_decision))
        with (
            patch.object(heartFC_chat.message_api, "get_messages_by_time_in_chat", return_value=recent),
            patch.object(heartFC_chat.time, "time", return_value=21.0),
        ):
            self.assertTrue(await chat._loopbody())

        chat._observe.assert_awaited_once_with(recent_messages_list=recent, force_reply_message=force)


class HeartFChattingActionTest(unittest.IsolatedAsyncioTestCase):
    async def test_handle_action_uses_manager_and_reports_factory_or_execute_errors(self) -> None:
        chat = make_hfc()
        handler = SimpleNamespace(execute=AsyncMock(return_value=(True, "done")))
        chat.action_manager = SimpleNamespace(create_action=Mock(return_value=handler))

        self.assertEqual(
            await chat._handle_action("plugin", "why", {"x": 1}, {}, "tid", make_db_message()), (True, "done")
        )
        self.assertEqual(chat.action_manager.create_action.call_args.kwargs["action_name"], "plugin")

        chat.action_manager = SimpleNamespace(create_action=Mock(side_effect=RuntimeError("factory down")))
        self.assertEqual(await chat._handle_action("plugin", "why", {}, {}, "tid"), (False, ""))

        chat.action_manager = SimpleNamespace(
            create_action=Mock(return_value=SimpleNamespace(execute=AsyncMock(side_effect=RuntimeError("run down"))))
        )
        self.assertEqual(await chat._handle_action("plugin", "why", {}, {}, "tid"), (False, ""))

    async def test_send_response_obeys_quote_mode_and_sends_text_parts_only(self) -> None:
        chat = make_hfc()
        reply_set = ReplySetModel(
            reply_data=[
                ReplyContent(content_type=ReplyContentType.TEXT, content="第一句"),
                ReplyContent(content_type=ReplyContentType.EMOJI, content="ignored"),
                ReplyContent(content_type=ReplyContentType.TEXT, content="第二句"),
            ]
        )

        with (
            patch.object(heartFC_chat.global_config, "chat", SimpleNamespace(llm_quote=True)),
            patch.object(heartFC_chat.send_api, "text_to_stream", new=AsyncMock()) as text_to_stream,
        ):
            reply_text = await chat._send_response(
                reply_set,
                make_db_message(),
                selected_expressions=[1],
                quote_message=True,
            )

        self.assertEqual(reply_text, "第一句第二句")
        self.assertEqual(text_to_stream.await_count, 2)
        self.assertTrue(text_to_stream.await_args_list[0].kwargs["set_reply"])
        self.assertFalse(text_to_stream.await_args_list[0].kwargs["typing"])
        self.assertFalse(text_to_stream.await_args_list[1].kwargs["set_reply"])
        self.assertTrue(text_to_stream.await_args_list[1].kwargs["typing"])

        with (
            patch.object(heartFC_chat.global_config, "chat", SimpleNamespace(llm_quote=False)),
            patch.object(heartFC_chat.message_api, "count_new_messages", return_value=3),
            patch.object(heartFC_chat.random, "randint", return_value=3),
            patch.object(heartFC_chat.send_api, "text_to_stream", new=AsyncMock()) as text_to_stream,
        ):
            await chat._send_response(reply_set, make_db_message(), quote_message=None)

        self.assertTrue(text_to_stream.await_args_list[0].kwargs["set_reply"])

    async def test_execute_action_handles_no_reply_reply_plugin_and_failure_paths(self) -> None:
        chat = make_hfc()
        available_actions = {"plugin": make_action_info("plugin")}

        with patch.object(heartFC_chat.database_api, "store_action_info", new=AsyncMock()) as store_action:
            no_reply = await chat._execute_action(
                ActionPlannerInfo(action_type="no_reply", reasoning="silent", action_data={}),
                [],
                "tid",
                available_actions,
                {},
            )

        self.assertEqual(no_reply, {"action_type": "no_reply", "success": True, "result": "选择不回复", "command": ""})
        self.assertEqual(chat.consecutive_no_reply_count, 1)
        store_action.assert_awaited_once()

        llm_response = SimpleNamespace(
            reply_set=ReplySetModel(reply_data=[ReplyContent(content_type=ReplyContentType.TEXT, content="hi")]),
            selected_expressions=[2],
            retrieved_atom_ids=[],
        )
        chat._send_and_store_reply = AsyncMock(return_value=({"loop_action_info": {}}, "hi", {}))
        with (
            patch.object(heartFC_chat.database_api, "store_action_info", new=AsyncMock()),
            patch.object(heartFC_chat, "record_replyer_action_temp"),
            patch.object(
                heartFC_chat.generator_api, "generate_reply", new=AsyncMock(return_value=(True, llm_response))
            ) as generate,
            patch.object(heartFC_chat.global_config, "tool", SimpleNamespace(enable_tool=True)),
        ):
            reply = await chat._execute_action(
                ActionPlannerInfo(
                    action_type="reply",
                    reasoning="reply reason",
                    action_reasoning="planner reason",
                    action_data={
                        "unknown_words": ["  词  ", "", 1],
                        "quote": "yes",
                        "loop_start_time": 123.0,
                    },
                    action_message=make_db_message(),
                ),
                [],
                "tid",
                available_actions,
                {},
            )

        self.assertTrue(reply["success"])
        self.assertEqual(reply["action_type"], "reply")
        self.assertEqual(chat.consecutive_no_reply_count, 0)
        self.assertEqual(generate.await_args.kwargs["reply_reason"], "planner reason")
        self.assertEqual(generate.await_args.kwargs["unknown_words"], ["词"])
        self.assertEqual(generate.await_args.kwargs["reply_time_point"], 123.0)
        self.assertEqual(chat._send_and_store_reply.await_args.kwargs["quote_message"], True)

        with (
            patch.object(heartFC_chat.database_api, "store_action_info", new=AsyncMock()),
            patch.object(heartFC_chat, "record_replyer_action_temp"),
            patch.object(heartFC_chat.generator_api, "generate_reply", new=AsyncMock(return_value=(False, None))),
            patch.object(heartFC_chat.global_config, "tool", SimpleNamespace(enable_tool=True)),
        ):
            failed_reply = await chat._execute_action(
                ActionPlannerInfo(
                    action_type="reply", reasoning="reply", action_data={}, action_message=make_db_message()
                ),
                [],
                "tid",
                available_actions,
                {},
            )

        self.assertFalse(failed_reply["success"])
        self.assertEqual(failed_reply["result"], "回复生成失败")

        chat._handle_action = AsyncMock(return_value=(True, "plugin result"))
        plugin = await chat._execute_action(
            ActionPlannerInfo(
                action_type="plugin", action_reasoning="why", action_data={"x": 1}, action_message=make_db_message()
            ),
            [],
            "tid",
            available_actions,
            {},
        )

        self.assertEqual(plugin, {"action_type": "plugin", "success": True, "result": "plugin result"})


if __name__ == "__main__":
    unittest.main()
