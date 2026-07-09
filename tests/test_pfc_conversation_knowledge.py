import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from maim_message import GroupInfo, UserInfo

from src.chat.brain_chat.PFC import conversation, pfc_KnowledgeFetcher, pfc_manager
from src.chat.brain_chat.PFC.conversation import Conversation
from src.chat.brain_chat.PFC.conversation_info import ConversationInfo
from src.chat.brain_chat.PFC.observation_info import ObservationInfo
from src.chat.brain_chat.PFC.pfc_types import ConversationState
from src.chat.message_receive.chat_stream import ChatStream


def make_stream() -> ChatStream:
    return ChatStream(
        stream_id="stream-1",
        platform="qq",
        user_info=UserInfo(platform="qq", user_id="user-1", user_nickname="Alice", user_cardname="Ali"),
        group_info=GroupInfo(platform="qq", group_id="group-1", group_name="Group"),
        data={"create_time": 1.0, "last_active_time": 2.0},
    )


def make_conversation() -> Conversation:
    conv = Conversation.__new__(Conversation)
    conv.stream_id = "stream-1"
    conv.private_name = "Alice"
    conv.state = ConversationState.INIT
    conv.should_continue = True
    conv.ignore_until_timestamp = None
    conv.generated_reply = ""
    conv.chat_stream = make_stream()
    conv.conversation_info = ConversationInfo()
    conv.observation_info = ObservationInfo("Alice")
    return conv


class PFCKnowledgeFormattingTest(unittest.IsolatedAsyncioTestCase):
    def test_evidence_text_helpers_escape_compact_trust_and_format_blocks(self) -> None:
        self.assertEqual(pfc_KnowledgeFetcher._escape_evidence_text("<tag>&"), "&lt;tag&gt;&amp;")
        self.assertEqual(pfc_KnowledgeFetcher._compact_evidence_text(" a\n b  c ", 20), "a b c")
        self.assertEqual(pfc_KnowledgeFetcher._compact_evidence_text("abcdef", 4), "abc…")

        trusted = '<CONTEXT_EVIDENCE priority="low" source="memory">\ntext\n</CONTEXT_EVIDENCE>'
        self.assertTrue(pfc_KnowledgeFetcher._is_trusted_memory_evidence(trusted, "memory"))
        self.assertFalse(pfc_KnowledgeFetcher._is_trusted_memory_evidence(trusted + trusted, "memory"))
        self.assertFalse(pfc_KnowledgeFetcher._is_trusted_memory_evidence(trusted, "pfc"))

        block = pfc_KnowledgeFetcher._format_pfc_knowledge_block(
            " <query> ",
            "source&x",
            "knowledge <unsafe>",
            max_chars=1000,
        )

        self.assertIn('source="pfc_knowledge"', block)
        self.assertIn("检索问题：&lt;query&gt;", block)
        self.assertIn("来源：source&amp;x", block)
        self.assertIn("knowledge &lt;unsafe&gt;", block)

        tiny = pfc_KnowledgeFetcher._format_pfc_knowledge_block("q", "s", "k", max_chars=10)
        self.assertEqual(tiny, "")

    def test_format_knowledge_evidence_collects_only_fully_injected_trusted_atom_ids(self) -> None:
        trusted = '<CONTEXT_EVIDENCE priority="low" source="memory">\n记忆证据\n</CONTEXT_EVIDENCE>'
        text, atom_ids = pfc_KnowledgeFetcher._format_knowledge_evidence_with_ids(
            [
                "ignored",
                {"knowledge": "", "atom_ids": ["empty"]},
                {"knowledge": "LPMM 知识库已移除", "atom_ids": ["old"]},
                {"query": "普通知识", "source": "wiki", "knowledge": "普通 <知识>"},
                {"query": "记忆", "source": "memory", "knowledge": trusted, "atom_ids": ["a", "b", "a", ""]},
            ],
            max_chars=3000,
        )

        self.assertIn("普通 &lt;知识&gt;", text)
        self.assertIn("记忆证据", text)
        self.assertEqual(atom_ids, ["a", "b"])
        self.assertEqual(
            pfc_KnowledgeFetcher.collect_knowledge_atom_ids(
                [{"query": "记忆", "source": "memory", "knowledge": trusted, "atom_ids": ["a"]}]
            ),
            ["a"],
        )
        self.assertEqual(pfc_KnowledgeFetcher.format_knowledge_evidence([]), "")

        long_text, long_atom_ids = pfc_KnowledgeFetcher._format_knowledge_evidence_with_ids(
            [{"query": "记忆", "source": "memory", "knowledge": trusted * 20, "atom_ids": ["too-long"]}],
            max_chars=500,
        )
        self.assertIn("pfc_knowledge", long_text)
        self.assertEqual(long_atom_ids, [])

    def test_chat_history_fallback_and_latest_text_support_dicts_and_objects(self) -> None:
        object_message = SimpleNamespace(
            user_info=SimpleNamespace(user_nickname="Bob", user_id="user-2"),
            processed_plain_text="对象消息",
            display_message="",
            detailed_plain_text="",
        )
        history = [
            {"user_info": {"user_nickname": "Alice"}, "processed_plain_text": "字典消息"},
            {"user_info": "bad", "display_message": "显示消息"},
            object_message,
        ]

        self.assertEqual(
            pfc_KnowledgeFetcher._format_dict_messages(history),
            "Alice: 字典消息\n对方: 显示消息\nBob: 对象消息",
        )
        with patch.object(pfc_KnowledgeFetcher, "build_readable_messages", side_effect=RuntimeError("bad data")):
            self.assertEqual(
                pfc_KnowledgeFetcher.format_pfc_chat_history(history),
                "Alice: 字典消息\n对方: 显示消息\nBob: 对象消息",
            )
        self.assertEqual(pfc_KnowledgeFetcher._latest_user_text(history), "对象消息")
        self.assertEqual(pfc_KnowledgeFetcher._latest_user_text([]), "")

    async def test_knowledge_fetcher_fetch_handles_empty_missing_error_and_success_paths(self) -> None:
        fetcher = pfc_KnowledgeFetcher.KnowledgeFetcher("stream-1", "Alice")
        self.assertEqual(await fetcher.fetch("", []), ("", ""))
        self.assertEqual(fetcher.last_retrieved_atom_ids, [])

        fake_manager = SimpleNamespace(get_stream=Mock(return_value=None))
        with patch.object(pfc_KnowledgeFetcher, "get_chat_manager", return_value=fake_manager):
            self.assertEqual(await fetcher.fetch("query", []), ("", ""))

        stream = make_stream()
        fake_manager = SimpleNamespace(get_stream=Mock(return_value=stream))
        with (
            patch.object(pfc_KnowledgeFetcher, "get_chat_manager", return_value=fake_manager),
            patch.object(
                pfc_KnowledgeFetcher,
                "build_memory_retrieval_prompt",
                new=AsyncMock(side_effect=RuntimeError("memory down")),
            ),
        ):
            self.assertEqual(await fetcher.fetch("query", [{"processed_plain_text": "latest"}]), ("", ""))

        with (
            patch.object(pfc_KnowledgeFetcher, "get_chat_manager", return_value=fake_manager),
            patch.object(
                pfc_KnowledgeFetcher,
                "build_memory_retrieval_prompt",
                new=AsyncMock(return_value=("evidence", ["atom-1"])),
            ) as build_prompt,
        ):
            self.assertEqual(
                await fetcher.fetch("query", [{"processed_plain_text": "latest", "user_info": {"user_id": "u"}}]),
                ("evidence", "memory"),
            )

        self.assertEqual(fetcher.last_retrieved_atom_ids, ["atom-1"])
        kwargs = build_prompt.await_args.kwargs
        self.assertEqual(kwargs["question"], "query")
        self.assertEqual(kwargs["target"], "latest")
        self.assertEqual(kwargs["user_id"], "user-1")


class ConversationHelpersTest(unittest.IsolatedAsyncioTestCase):
    def test_message_value_and_user_info_helpers_handle_dicts_and_objects(self) -> None:
        user_info = SimpleNamespace(platform="qq", user_id="u1", user_nickname="Alice", user_cardname="Ali")
        message_obj = SimpleNamespace(user_info=user_info, time=12.0)

        self.assertEqual(conversation._message_value({"time": 10.0}, "time"), 10.0)
        self.assertEqual(conversation._message_value(message_obj, "time"), 12.0)
        self.assertEqual(conversation._message_value(object(), "missing", "fallback"), "fallback")
        self.assertEqual(conversation._message_user_info_dict({"user_info": {"user_id": "u1"}}), {"user_id": "u1"})
        self.assertEqual(conversation._message_user_info_dict({"user_info": "bad"}), {})
        self.assertEqual(
            conversation._message_user_info_dict(message_obj),
            {"platform": "qq", "user_id": "u1", "user_nickname": "Alice", "user_cardname": "Ali"},
        )

    def test_convert_to_message_uses_chat_info_instance_stream_or_manager_fallback(self) -> None:
        conv = make_conversation()
        msg_dict = {
            "message_id": "msg-1",
            "time": 12.5,
            "processed_plain_text": "hello",
            "user_info": {"platform": "qq", "user_id": "user-2", "user_nickname": "Bob"},
            "chat_info": make_stream().to_dict(),
        }

        message = conv._convert_to_message(msg_dict)

        self.assertEqual(message.message_info.message_id, "msg-1")
        self.assertEqual(message.message_info.time, 12.5)
        self.assertEqual(message.message_info.user_info.user_id, "user-2")
        self.assertEqual(message.chat_stream.stream_id, "stream-1")
        self.assertEqual(message.processed_plain_text, "hello")
        self.assertEqual(message.message_components.components[0].text, "hello")

        conv.chat_stream = make_stream()
        no_chat_info = {**msg_dict, "message_id": "msg-2", "chat_info": None}
        self.assertEqual(conv._convert_to_message(no_chat_info).chat_stream.stream_id, "stream-1")

        conv.chat_stream = None
        fake_manager = SimpleNamespace(get_stream=Mock(return_value=make_stream()))
        with patch.object(conversation, "get_chat_manager", return_value=fake_manager):
            self.assertEqual(conv._convert_to_message(no_chat_info).chat_stream.stream_id, "stream-1")

        fake_manager = SimpleNamespace(get_stream=Mock(return_value=None))
        with patch.object(conversation, "get_chat_manager", return_value=fake_manager), self.assertRaises(ValueError):
            conv._convert_to_message(no_chat_info)

    def test_check_new_messages_after_planning_resets_last_successful_reply_when_needed(self) -> None:
        conv = make_conversation()
        delattr(conv, "observation_info")
        self.assertFalse(conv._check_new_messages_after_planning())

        conv.observation_info = SimpleNamespace(new_messages_count=2)
        conv.conversation_info.last_successful_reply_action = "direct_reply"
        self.assertFalse(conv._check_new_messages_after_planning())
        self.assertEqual(conv.conversation_info.last_successful_reply_action, "direct_reply")

        conv.observation_info.new_messages_count = 3
        self.assertTrue(conv._check_new_messages_after_planning())
        self.assertIsNone(conv.conversation_info.last_successful_reply_action)

    async def test_send_reply_validates_state_sends_and_reinforces_memories(self) -> None:
        conv = make_conversation()

        self.assertFalse(await conv._send_reply())

        conv.generated_reply = "hello"
        conv.direct_sender = None
        self.assertFalse(await conv._send_reply())

        conv.direct_sender = SimpleNamespace(send_message=AsyncMock())
        conv.chat_stream = None
        self.assertFalse(await conv._send_reply())

        conv.chat_stream = make_stream()
        conv._reinforce_retrieved_memories = AsyncMock()
        self.assertTrue(await conv._send_reply())
        conv.direct_sender.send_message.assert_awaited_once_with(chat_stream=conv.chat_stream, content="hello")
        conv._reinforce_retrieved_memories.assert_awaited_once_with("hello")
        self.assertEqual(conv.state, ConversationState.ANALYZING)

        conv.direct_sender = SimpleNamespace(send_message=AsyncMock(side_effect=RuntimeError("send failed")))
        self.assertFalse(await conv._send_reply())
        self.assertEqual(conv.state, ConversationState.ANALYZING)

    async def test_handle_action_covers_simple_wait_fetch_end_and_ignore_branches(self) -> None:
        conv = make_conversation()
        conv.waiter = SimpleNamespace(wait=AsyncMock(return_value=False), wait_listening=AsyncMock(return_value=False))
        conv.knowledge_fetcher = SimpleNamespace(
            fetch=AsyncMock(return_value=("knowledge text", "memory")),
            last_retrieved_atom_ids=["atom-1"],
        )
        observation = ObservationInfo("Alice")
        observation.chat_history = [{"message_id": "m1"}]
        info = conv.conversation_info

        await conv._handle_action("fetch_knowledge", "query", observation, info)
        self.assertEqual(
            info.knowledge_list,
            [{"query": "query", "knowledge": "knowledge text", "source": "memory", "atom_ids": ["atom-1"]}],
        )
        self.assertEqual(info.done_action[-1]["status"], "done")
        self.assertIsNone(info.last_successful_reply_action)

        await conv._handle_action("listening", "listen", observation, info)
        conv.waiter.wait_listening.assert_awaited_once_with(info)
        self.assertEqual(conv.state, ConversationState.LISTENING)

        await conv._handle_action("wait", "wait", observation, info)
        conv.waiter.wait.assert_awaited_once_with(info)
        self.assertEqual(conv.state, ConversationState.WAITING)

        await conv._handle_action("end_conversation", "done", observation, info)
        self.assertFalse(conv.should_continue)
        self.assertEqual(info.done_action[-1]["status"], "done")

        conv.should_continue = True
        with patch.object(conversation.time, "time", return_value=100.0):
            await conv._handle_action("block_and_ignore", "ignore", observation, info)
        self.assertEqual(conv.state, ConversationState.IGNORED)
        self.assertEqual(conv.ignore_until_timestamp, 700.0)

    async def test_send_timeout_message_uses_latest_cached_message_as_reply_anchor(self) -> None:
        conv = make_conversation()
        conv.chat_observer = SimpleNamespace(
            get_cached_messages=Mock(
                return_value=[
                    {
                        "message_id": "msg-1",
                        "time": 12.5,
                        "processed_plain_text": "latest",
                        "user_info": {"platform": "qq", "user_id": "user-2", "user_nickname": "Bob"},
                    }
                ]
            )
        )
        conv.direct_sender = SimpleNamespace(send_message=AsyncMock())

        await conv._send_timeout_message()

        conv.direct_sender.send_message.assert_awaited_once()
        kwargs = conv.direct_sender.send_message.await_args.kwargs
        self.assertEqual(kwargs["chat_stream"], conv.chat_stream)
        self.assertEqual(kwargs["content"], "TODO:超时消息")
        self.assertEqual(kwargs["reply_to_message"].message_info.message_id, "msg-1")


class FakeManagedConversation:
    should_continue = True

    def __init__(self, stream_id: str, private_name: str):
        self.stream_id = stream_id
        self.private_name = private_name
        self.should_continue = True
        self.ignore_until_timestamp = None
        self.initialized = False

    async def _initialize(self):
        self.initialized = True


class PFCManagerTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.original_instance = pfc_manager.PFCManager._instance
        self.original_instances = pfc_manager.PFCManager._instances.copy()
        self.original_initializing = pfc_manager.PFCManager._initializing.copy()
        pfc_manager.PFCManager._instance = None
        pfc_manager.PFCManager._instances = {}
        pfc_manager.PFCManager._initializing = {}

    def tearDown(self) -> None:
        pfc_manager.PFCManager._instance = self.original_instance
        pfc_manager.PFCManager._instances = self.original_instances
        pfc_manager.PFCManager._initializing = self.original_initializing

    async def test_singleton_existing_initializing_and_ignore_paths(self) -> None:
        first = pfc_manager.PFCManager.get_instance()
        self.assertIs(first, pfc_manager.PFCManager.get_instance())

        first._initializing["stream-1"] = True
        self.assertIsNone(await first.get_or_create_conversation("stream-1", "Alice"))

        first._initializing["stream-1"] = False
        existing = SimpleNamespace(should_continue=True)
        first._instances["stream-1"] = existing
        self.assertIs(await first.get_or_create_conversation("stream-1", "Alice"), existing)

        ignored = SimpleNamespace(should_continue=False, ignore_until_timestamp=200.0)
        first._instances["stream-1"] = ignored
        with patch.object(pfc_manager.time, "time", return_value=100.0):
            self.assertIsNone(await first.get_or_create_conversation("stream-1", "Alice"))

    async def test_create_initialize_get_and_failure_cleanup(self) -> None:
        manager = pfc_manager.PFCManager.get_instance()

        with patch.object(pfc_manager, "Conversation", FakeManagedConversation):
            created = await manager.get_or_create_conversation("stream-1", "Alice")

        self.assertIsInstance(created, FakeManagedConversation)
        self.assertTrue(created.initialized)
        self.assertFalse(manager._initializing["stream-1"])
        self.assertIs(await manager.get_conversation("stream-1"), created)

        broken = FakeManagedConversation("broken", "Alice")
        broken._initialize = AsyncMock(side_effect=RuntimeError("init failed"))
        manager._initializing["broken"] = True
        await manager._initialize_conversation(broken)
        self.assertFalse(manager._initializing["broken"])

        def raise_constructor(stream_id, private_name):
            raise RuntimeError("construct failed")

        with patch.object(pfc_manager, "Conversation", side_effect=raise_constructor):
            self.assertIsNone(await manager.get_or_create_conversation("stream-2", "Alice"))
        self.assertFalse(manager._initializing["stream-2"])


if __name__ == "__main__":
    unittest.main()
