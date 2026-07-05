# ruff: noqa: E402
import asyncio
import importlib
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

from maim_message import BaseMessageInfo, GroupInfo, MessageBase, Seg, UserInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.chat.heart_flow.turn_scheduler import ReplyTurnScheduler
from src.chat.message_receive.chat_stream import ChatStream
from src.chat.message_receive.message import MessageRecv, MessageSending
from src.chat.message_receive.storage import MessageStorage
from src.common.data_models.database_data_model import DatabaseMessages
from src.common.data_models.message_component_model import (
    EmojiComponent,
    ForwardComponent,
    ImageComponent,
    MessageComponentSequence,
    ReplyComponent,
    TextComponent,
    from_components_to_seg,
    from_seg_to_components,
)
from src.plugin_system.base.base_command import BaseCommand
from src.plugin_system.base.base_events_handler import BaseEventHandler
from src.plugin_system.base.component_types import EventType, MaiMessages
from src.plugin_system.core.events_manager import EventsManager
from src.plugin_system.apis import send_api
from src.services import send_service


def _message_info(message_id: str = "msg-1") -> dict:
    return {
        "platform": "test",
        "message_id": message_id,
        "time": 1.0,
        "group_info": {"platform": "test", "group_id": "g1", "group_name": "group"},
        "user_info": {"platform": "test", "user_id": "u1", "user_nickname": "user", "user_cardname": ""},
        "additional_config": {},
        "format_info": {"content_format": "", "accept_format": ""},
        "template_info": {"template_items": {}},
    }


def _message_info_with_additional_config(message_id: str, additional_config) -> dict:
    message_info = _message_info(message_id)
    message_info["additional_config"] = additional_config
    return message_info


async def test_lightweight_inbound() -> None:
    import src.chat.message_receive.message as message_module

    calls = []
    original_image = message_module.schedule_image_description_task
    original_emoji = message_module.schedule_emoji_description_task
    original_voice = message_module.schedule_voice_transcription_task
    try:
        message_module.schedule_image_description_task = lambda data, message_id=None: calls.append(
            ("image", data, message_id)
        )
        message_module.schedule_emoji_description_task = lambda data, message_id=None: calls.append(
            ("emoji", data, message_id)
        )
        message_module.schedule_voice_transcription_task = lambda data, message_id=None: calls.append(
            ("voice", data, message_id)
        )

        message = MessageRecv(
            {
                "message_info": _message_info(),
                "message_segment": Seg(
                    type="seglist",
                    data=[
                        Seg(type="text", data="hello"),
                        Seg(type="image", data="aW1hZ2U="),
                        Seg(type="emoji", data="ZW1vamk="),
                        Seg(type="voice", data="dm9pY2U="),
                    ],
                ).to_dict(),
                "raw_message": "",
            }
        )
        await message.process(enable_heavy_media_analysis=False, enable_voice_transcription=False)

        assert message.processed_plain_text == "hello [图片] [表情包] [语音消息]"
        assert calls == [
            ("image", "aW1hZ2U=", "msg-1"),
            ("emoji", "ZW1vamk=", "msg-1"),
            ("voice", "dm9pY2U=", "msg-1"),
        ]
        assert message.message_components.force_seglist is True
    finally:
        message_module.schedule_image_description_task = original_image
        message_module.schedule_emoji_description_task = original_emoji
        message_module.schedule_voice_transcription_task = original_voice


def test_message_recv_json_additional_config() -> None:
    message = MessageRecv(
        {
            "message_info": _message_info_with_additional_config("msg-json-config", '{"at_bot": true}'),
            "message_segment": Seg(type="text", data="hello").to_dict(),
            "raw_message": "hello",
        }
    )

    assert message.is_mentioned is True
    assert message.message_info.additional_config["at_bot"] is True


async def test_media_background_enrichment() -> None:
    import src.chat.message_receive.media_background as bg
    from src.common.database.database import db
    from src.common.database.database_model import EmojiDescriptionCache, ImageDescriptions

    async def fake_analyze(kind: str, media_data: str) -> str:
        await asyncio.sleep(0)
        return {"image": "[图片：desc]", "emoji": "[表情包：happy]", "voice": "[语音：hello]"}[kind]

    original_analyze = bg._analyze_media
    original_load_cached = bg._load_cached_media_result
    original_backfill = bg._schedule_placeholder_backfill
    bg._media_task_states.clear()
    bg._message_media_refs.clear()
    bg._backfill_locks.clear()
    backfills = []
    try:
        bg._analyze_media = fake_analyze
        bg._schedule_placeholder_backfill = lambda kind, message_id, result_text, occurrence_index: backfills.append(
            (kind, message_id, result_text, occurrence_index)
        )

        bg.schedule_image_description_task("aW1hZ2U=", "msg-media")
        await asyncio.sleep(0.05)

        assert len(bg._media_task_states) == 1
        assert bg.enhance_media_placeholders("msg-media", "see [图片]") == "see [图片：desc]"

        bg._media_task_states.clear()
        bg._message_media_refs.clear()
        bg._backfill_locks.clear()
        backfills.clear()

        async def unexpected_analyze(kind: str, media_data: str) -> str:
            raise AssertionError("cached media should not be analyzed")

        bg._analyze_media = unexpected_analyze
        bg._load_cached_media_result = lambda kind, media_hash: "[表情包：cached]" if kind == "emoji" else None
        bg.schedule_emoji_description_task("ZW1vamk=", "msg-cached-media")

        assert len(bg._media_task_states) == 1
        assert next(iter(bg._media_task_states.values())).status == "done"
        assert bg.enhance_media_placeholders("msg-cached-media", "see [表情包]") == "see [表情包：cached]"
        assert backfills == [("emoji", "msg-cached-media", "[表情包：cached]", 0)]

        bg._media_task_states.clear()
        bg._message_media_refs.clear()
        first_key = "image:first"
        second_key = "image:second"
        bg._media_task_states[first_key] = bg._MediaTaskState(kind="image", media_hash="first", status="processing")
        bg._media_task_states[second_key] = bg._MediaTaskState(
            kind="image",
            media_hash="second",
            status="done",
            result_text="[图片：second]",
        )
        bg._remember_message_ref("msg-two-images", first_key, bg._media_task_states[first_key])
        bg._remember_message_ref("msg-two-images", second_key, bg._media_task_states[second_key])
        assert (
            bg.enhance_media_placeholders("msg-two-images", "see [图片] then [图片]")
            == "see [图片] then [图片：second]"
        )
        bg._media_task_states[first_key].status = "done"
        bg._media_task_states[first_key].result_text = "[图片：first]"
        assert (
            bg.enhance_media_placeholders("msg-two-images", "see [图片] then [图片]")
            == "see [图片：first] then [图片：second]"
        )

        bg._load_cached_media_result = original_load_cached
        db.connect(reuse_if_open=True)
        db.create_tables([ImageDescriptions, EmojiDescriptionCache], safe=True)
        image_hash = uuid.uuid4().hex
        emoji_hash = uuid.uuid4().hex
        with db.atomic() as txn:
            ImageDescriptions.create(
                type="image",
                image_description_hash=image_hash,
                description="persistent image",
                timestamp=1.0,
            )
            EmojiDescriptionCache.create(
                emoji_hash=emoji_hash,
                description="persistent emoji",
                emotion_tags="joy",
                timestamp=1.0,
            )

            assert bg._load_cached_media_result("image", image_hash) == "[图片：persistent image]"
            assert bg._load_cached_media_result("emoji", emoji_hash) == "[表情包：joy]"
            txn.rollback()
    finally:
        bg._analyze_media = original_analyze
        bg._load_cached_media_result = original_load_cached
        bg._schedule_placeholder_backfill = original_backfill
        bg._media_task_states.clear()
        bg._message_media_refs.clear()


async def test_send_service_build_hook() -> None:
    ev_mod = importlib.import_module("src.plugin_system.core.events_manager")

    class FakeChatManager:
        def __init__(self, stream: ChatStream):
            self.stream = stream

        def get_stream(self, stream_id: str) -> ChatStream:
            assert stream_id == self.stream.stream_id
            return self.stream

    class FakeSender:
        message = None

        async def send_message(self, message, **kwargs):
            if kwargs.get("set_reply"):
                message.build_reply()
            await message.process()
            self.__class__.message = message
            assert kwargs["storage_message"] is False
            return True

    async def fake_hook(*args, **kwargs):
        modified = MaiMessages(additional_data={"selected_expressions": [1, 2]})
        modified.modify_message_segments([Seg(type="text", data="modified")], suppress_warning=True)
        return True, modified

    stream = ChatStream(
        stream_id="stream-1",
        platform="test",
        user_info=UserInfo(platform="test", user_id="u1", user_nickname="user"),
        group_info=GroupInfo(platform="test", group_id="g1", group_name="group"),
    )
    original_get_chat_manager = send_service.get_chat_manager
    original_sender = send_service.UniversalMessageSender
    original_hook = ev_mod.events_manager.handle_mai_events
    try:
        send_service.get_chat_manager = lambda: FakeChatManager(stream)
        send_service.UniversalMessageSender = FakeSender
        ev_mod.events_manager.handle_mai_events = fake_hook

        sent = await send_service.text_to_stream_with_message("original", stream.stream_id, storage_message=False)

        assert sent is not None
        assert FakeSender.message.message_segment.type == "seglist"
        assert FakeSender.message.message_segment.data[0].data == "modified"
        assert sent.message_components.components[0].text == "modified"
        assert FakeSender.message.selected_expressions == [1, 2]

        async def no_op_hook(*args, **kwargs):
            return True, None

        ev_mod.events_manager.handle_mai_events = no_op_hook

        image_sent = await send_service.image_to_stream_with_message(
            "aW1hZ2U=",
            stream.stream_id,
            storage_message=False,
        )
        assert image_sent is not None
        assert image_sent.message_segment.type == "image"
        assert isinstance(image_sent.message_components.components[0], ImageComponent)
        assert image_sent.message_components.components[0].base64_data == "aW1hZ2U="

        emoji_status = await send_api.emoji_to_stream("ZW1vamk=", stream.stream_id, storage_message=False)
        assert emoji_status is True
        assert FakeSender.message.message_segment.type == "emoji"
        assert isinstance(FakeSender.message.message_components.components[0], EmojiComponent)
        assert FakeSender.message.message_components.components[0].base64_data == "ZW1vamk="

        reply_sent = await send_service.components_to_stream_with_message(
            MessageComponentSequence([ReplyComponent(target_message_id="reply-1", target_text="preview text")]),
            stream.stream_id,
            storage_message=False,
        )
        assert reply_sent is not None
        assert isinstance(FakeSender.message.message_components.components[0], ReplyComponent)
        assert FakeSender.message.message_components.components[0].target_text == "preview text"
        assert FakeSender.message.processed_plain_text == "[回复：preview text]"

        anchor_reply = DatabaseMessages(
            message_id="anchor-reply",
            time=1.0,
            processed_plain_text="anchor preview",
            additional_config={},
            user_id="u2",
            user_nickname="anchor user",
            user_platform="test",
            chat_info_user_id="u1",
            chat_info_user_nickname="user",
            chat_info_user_platform="test",
            chat_info_group_id="g1",
            chat_info_group_name="group",
            chat_info_group_platform="test",
            chat_info_stream_id="stream-1",
            chat_info_platform="test",
            chat_info_create_time=1.0,
            chat_info_last_active_time=1.0,
        )
        wrapped_reply_sent = await send_service.components_to_stream_with_message(
            MessageComponentSequence([ReplyComponent(target_message_id="inner-reply", target_text="inner preview")]),
            stream.stream_id,
            set_reply=True,
            reply_message=anchor_reply,
            storage_message=False,
        )
        assert wrapped_reply_sent is not None
        assert isinstance(FakeSender.message.message_components.components[0], ReplyComponent)
        assert FakeSender.message.message_components.components[0].target_message_id == "anchor-reply"
        assert FakeSender.message.message_components.components[0].target_text == "anchor preview"
        assert isinstance(FakeSender.message.message_components.components[1], ReplyComponent)
        assert FakeSender.message.message_components.components[1].target_message_id == "inner-reply"
        assert FakeSender.message.message_components.components[1].target_text == "inner preview"
        assert "anchor preview" in FakeSender.message.processed_plain_text
        assert "inner preview" in FakeSender.message.processed_plain_text
    finally:
        send_service.get_chat_manager = original_get_chat_manager
        send_service.UniversalMessageSender = original_sender
        ev_mod.events_manager.handle_mai_events = original_hook


def test_db_message_to_message_recv() -> None:
    db_message = DatabaseMessages(
        message_id="db-msg",
        time=1.0,
        processed_plain_text="stored text",
        additional_config='{"at_bot": true}',
        user_id="u1",
        user_nickname="user",
        user_platform="test",
        chat_info_user_id="u1",
        chat_info_user_nickname="user",
        chat_info_user_platform="test",
        chat_info_stream_id="stream-1",
        chat_info_platform="test",
        chat_info_create_time=1.0,
        chat_info_last_active_time=1.0,
    )

    recv = send_service.db_message_to_message_recv(db_message)

    assert recv.message_segment.type == "text"
    assert recv.message_segment.data == "stored text"
    assert recv.processed_plain_text == "stored text"
    assert recv.message_info.additional_config["at_bot"] is True
    assert recv.message_info.group_info is None


def test_turn_scheduler() -> None:
    scheduler = ReplyTurnScheduler()
    empty = scheduler.decide_group_turn(stream_id="stream", recent_messages=[], consecutive_no_reply_count=0)
    assert empty.should_observe is False
    assert empty.sleep_seconds == 0.2

    mentioned = SimpleNamespace(is_mentioned=True, is_at=False)
    decision = scheduler.decide_group_turn(stream_id="stream", recent_messages=[mentioned], consecutive_no_reply_count=0)
    assert decision.should_observe is True
    assert decision.force_reply_message is mentioned

    private = scheduler.decide_private_turn(recent_messages=[SimpleNamespace()])
    assert private.should_observe is True
    assert private.should_update_last_read_time is True
    assert private.should_set_new_message_event is True


async def test_components_round_trip() -> None:
    seglist = Seg(type="seglist", data=[Seg(type="text", data="only")])
    seq = from_seg_to_components(seglist)
    converted = await from_components_to_seg(seq)
    assert converted.type == "seglist"
    assert converted.data[0].type == "text"

    nested_seglist = Seg(
        type="seglist",
        data=[
            Seg(type="text", data="outer"),
            Seg(type="seglist", data=[Seg(type="text", data="inner"), Seg(type="image", data="aW1hZ2U=")]),
            Seg(type="text", data="tail"),
        ],
    )
    nested_converted = await from_components_to_seg(from_seg_to_components(nested_seglist))
    assert nested_converted.type == "seglist"
    assert nested_converted.data[1].type == "seglist"
    assert nested_converted.data[1].data[0].data == "inner"
    assert nested_converted.data[1].data[1].type == "image"

    file_payload = {"file": "report.pdf", "file_size": "1024", "url": "https://example.test/report.pdf"}
    file_converted = await from_components_to_seg(from_seg_to_components(Seg(type="file", data=file_payload)))
    assert file_converted.type == "file"
    assert file_converted.data == file_payload

    forward_raw = [
        MessageBase(
            message_segment=Seg(type="text", data="forward text"),
            message_info=BaseMessageInfo(user_info=UserInfo(user_id="u2", user_nickname="user2")),
        ).to_dict()
    ]
    forward_converted = await from_components_to_seg(from_seg_to_components(Seg(type="forward", data=forward_raw)))
    assert forward_converted.type == "forward"
    assert forward_converted.data == forward_raw

    unknown = await from_components_to_seg(from_seg_to_components(Seg(type="custom_card", data={"x": 1})))
    assert unknown.type == "custom_card"
    assert unknown.data == {"x": 1}

    zero_text = await from_components_to_seg(from_seg_to_components(Seg(type="text", data=0)))
    assert zero_text.type == "text"
    assert zero_text.data == "0"


def test_webui_segment_parsing_forward() -> None:
    from src.chat.message_receive.uni_message_sender import parse_message_components, parse_message_segments

    forward_raw = [
        MessageBase(
            message_segment=Seg(type="text", data="forward text"),
            message_info=BaseMessageInfo(user_info=UserInfo(user_id="u2", user_nickname="user2")),
        ).to_dict()
    ]

    assert parse_message_segments(forward_raw[0]["message_segment"]) == [{"type": "text", "data": "forward text"}]
    assert parse_message_segments(Seg(type="forward", data=forward_raw)) == [
        {"type": "forward", "data": [{"content": [{"type": "text", "data": "forward text"}]}]}
    ]
    component_segments = parse_message_components(
        MessageComponentSequence(
            [
                TextComponent(text="hello"),
                ImageComponent(base64_data="aW1hZ2U="),
                ForwardComponent(nodes=[MessageComponentSequence([TextComponent(text="nested")])]),
            ],
            force_seglist=True,
        )
    )
    assert component_segments == [
        {"type": "text", "data": "hello"},
        {"type": "image", "data": "data:image/png;base64,aW1hZ2U="},
        {"type": "forward", "data": [{"content": [{"type": "text", "data": "nested"}]}]},
    ]


async def test_webui_send_uses_components() -> None:
    import src.chat.message_receive.uni_message_sender as sender_module

    class FakeBroadcaster:
        payload = None

        async def broadcast(self, payload):
            self.__class__.payload = payload

    stream = ChatStream(
        stream_id="webui-stream",
        platform="test",
        user_info=UserInfo(platform="test", user_id="u1", user_nickname="user"),
        group_info=GroupInfo(platform="test", group_id="webui_virtual_group_test_u1", group_name="webui"),
    )
    message = MessageSending(
        message_id="msg-webui-components",
        chat_stream=stream,
        bot_user_info=UserInfo(platform="test", user_id="bot", user_nickname="bot"),
        sender_info=stream.user_info,
        message_segment=Seg(type="text", data="fallback text"),
    )
    message.processed_plain_text = "image content"
    message.message_components = MessageComponentSequence([ImageComponent(base64_data="aW1hZ2U=")])

    original_get_broadcaster = sender_module.get_webui_chat_broadcaster
    try:
        sender_module.get_webui_chat_broadcaster = lambda: (FakeBroadcaster(), "webui")
        assert await sender_module._send_message(message, show_log=False) is True
        assert FakeBroadcaster.payload["message_type"] == "rich"
        assert FakeBroadcaster.payload["segments"] == [
            {"type": "image", "data": "data:image/png;base64,aW1hZ2U="}
        ]
    finally:
        sender_module.get_webui_chat_broadcaster = original_get_broadcaster


async def test_event_extra_data() -> None:
    class CaptureHandler(BaseEventHandler):
        event_type = EventType.ON_COMMAND_BEFORE_EXECUTE
        handler_name = "capture_smoke_handler"
        intercept_message = True
        captured = None

        async def execute(self, message):
            self.__class__.captured = dict(message.additional_data)
            return True, True, "ok", None, None

    manager = EventsManager()
    handler = CaptureHandler()
    handler.set_plugin_name("test_plugin")
    manager._events_subscribers[EventType.ON_COMMAND_BEFORE_EXECUTE].append(handler)

    message = MessageRecv(
        {
            "message_info": _message_info_with_additional_config("msg-hook", '{"from_config": true}'),
            "message_segment": Seg(type="text", data="!cmd").to_dict(),
            "raw_message": "!cmd",
        }
    )
    ok, modified = await manager.handle_mai_events(
        EventType.ON_COMMAND_BEFORE_EXECUTE,
        message,
        extra_data={"command_name": "cmd", "matched_groups": ("x",)},
    )

    assert ok is True
    assert modified is None
    assert CaptureHandler.captured["from_config"] is True
    assert CaptureHandler.captured["command_name"] == "cmd"
    assert CaptureHandler.captured["matched_groups"] == ("x",)


async def test_event_non_intercept_task_cleanup() -> None:
    class AsyncHandler(BaseEventHandler):
        event_type = EventType.ON_MESSAGE_AFTER_PROCESS
        handler_name = "async_cleanup_handler"
        intercept_message = False
        ran = False

        async def execute(self, message):
            await asyncio.sleep(0)
            self.__class__.ran = True
            return True, True, "ok", None, None

    manager = EventsManager()
    handler = AsyncHandler()
    handler.set_plugin_name("test_plugin")
    manager._events_subscribers[EventType.ON_MESSAGE_AFTER_PROCESS].append(handler)

    message = MessageRecv(
        {
            "message_info": _message_info("msg-async-hook"),
            "message_segment": Seg(type="text", data="hello").to_dict(),
            "raw_message": "hello",
        }
    )

    ok, modified = await manager.handle_mai_events(EventType.ON_MESSAGE_AFTER_PROCESS, message)
    await asyncio.sleep(0.05)

    assert ok is True
    assert modified is None
    assert AsyncHandler.ran is True
    assert manager._handler_tasks["async_cleanup_handler"] == []


async def test_planner_hook_prompt_applied() -> None:
    import src.chat.brain_chat.brain_planner as brain_planner_module
    import src.chat.planner_actions.planner as group_planner_module

    async def run_group_planner_case() -> None:
        captured = {}
        planner = group_planner_module.ActionPlanner.__new__(group_planner_module.ActionPlanner)
        planner.chat_id = "stream-plan"
        planner.log_prefix = "[stream-plan]"
        planner.last_obs_time_mark = 0.0
        planner.plan_log = []
        planner.get_necessary_info = lambda: (True, None, {})
        planner._filter_actions_by_activation_type = lambda available_actions, chat_content_block: available_actions

        async def build_prompt(**kwargs):
            return "original group prompt", []

        async def execute_prompt(**kwargs):
            captured["group_prompt"] = kwargs["prompt"]
            return "reason", [], "raw", None, 0.0

        planner.build_planner_prompt = build_prompt
        planner._execute_main_planner = execute_prompt

        modified = MaiMessages(llm_prompt="original group prompt")
        modified.modify_llm_prompt("modified group prompt", suppress_warning=True)

        original_get_raw = group_planner_module.get_raw_msg_before_timestamp_with_chat
        original_build_readable = group_planner_module.build_readable_messages_with_id
        original_events = group_planner_module.events_manager.handle_mai_events
        original_log_plan = group_planner_module.PlanReplyLogger.log_plan
        try:
            group_planner_module.get_raw_msg_before_timestamp_with_chat = lambda **kwargs: []
            group_planner_module.build_readable_messages_with_id = lambda **kwargs: ("", [])
            group_planner_module.events_manager.handle_mai_events = lambda *args, **kwargs: asyncio.sleep(
                0, result=(True, modified)
            )
            group_planner_module.PlanReplyLogger.log_plan = lambda **kwargs: None
            await planner.plan(available_actions={})
            assert captured["group_prompt"] == "modified group prompt"
        finally:
            group_planner_module.get_raw_msg_before_timestamp_with_chat = original_get_raw
            group_planner_module.build_readable_messages_with_id = original_build_readable
            group_planner_module.events_manager.handle_mai_events = original_events
            group_planner_module.PlanReplyLogger.log_plan = original_log_plan

    async def run_brain_planner_case() -> None:
        captured = {}
        planner = brain_planner_module.BrainPlanner.__new__(brain_planner_module.BrainPlanner)
        planner.chat_id = "stream-plan"
        planner.log_prefix = "[stream-plan]"
        planner.last_obs_time_mark = 0.0
        planner.plan_log = []
        planner.get_necessary_info = lambda: (False, None, {})
        planner._filter_actions_by_activation_type = lambda available_actions, chat_content_block: available_actions

        async def build_prompt(**kwargs):
            return "original brain prompt", []

        async def execute_prompt(**kwargs):
            captured["brain_prompt"] = kwargs["prompt"]
            return "reason", [], "raw", None, 0.0

        planner.build_planner_prompt = build_prompt
        planner._execute_main_planner = execute_prompt

        modified = MaiMessages(llm_prompt="original brain prompt")
        modified.modify_llm_prompt("modified brain prompt", suppress_warning=True)

        original_get_raw = brain_planner_module.get_raw_msg_before_timestamp_with_chat
        original_build_readable = brain_planner_module.build_readable_messages_with_id
        original_events = brain_planner_module.events_manager.handle_mai_events
        original_log_plan = brain_planner_module.PlanReplyLogger.log_plan
        try:
            brain_planner_module.get_raw_msg_before_timestamp_with_chat = lambda **kwargs: []
            brain_planner_module.build_readable_messages_with_id = lambda **kwargs: ("", [])
            brain_planner_module.events_manager.handle_mai_events = lambda *args, **kwargs: asyncio.sleep(
                0, result=(True, modified)
            )
            brain_planner_module.PlanReplyLogger.log_plan = lambda **kwargs: None
            await planner.plan(available_actions={})
            assert captured["brain_prompt"] == "modified brain prompt"
        finally:
            brain_planner_module.get_raw_msg_before_timestamp_with_chat = original_get_raw
            brain_planner_module.build_readable_messages_with_id = original_build_readable
            brain_planner_module.events_manager.handle_mai_events = original_events
            brain_planner_module.PlanReplyLogger.log_plan = original_log_plan

    await run_group_planner_case()
    await run_brain_planner_case()


def test_inbound_hook_application() -> None:
    import src.chat.message_receive.bot as bot_module

    message = MessageRecv(
        {
            "message_info": _message_info("msg-inbound-hook"),
            "message_segment": Seg(type="text", data="before").to_dict(),
            "raw_message": "before",
            "processed_plain_text": "before",
        }
    )
    modified = MaiMessages(additional_data={"at_bot": True, "custom": "value"})
    modified.modify_message_segments([Seg(type="text", data="after")], suppress_warning=True)
    modified.modify_plain_text("after", suppress_warning=True)

    bot_module._apply_modified_message(message, modified, merge_additional_data=True)

    assert message.processed_plain_text == "after"
    assert message.message_segment.type == "seglist"
    assert message.message_components.force_seglist is True
    assert message.message_info.additional_config["at_bot"] is True
    assert message.message_info.additional_config["custom"] == "value"


async def test_message_storage_additional_config() -> None:
    import src.chat.message_receive.storage as storage_module

    captured = {}
    original_create = storage_module.Messages.create
    try:
        storage_module.Messages.create = lambda **kwargs: captured.update(kwargs)
        message = MessageRecv(
            {
                "message_info": _message_info_with_additional_config("msg-store", {"custom": "value"}),
                "message_segment": Seg(type="text", data="hello").to_dict(),
                "raw_message": "hello",
                "processed_plain_text": "hello",
            }
        )
        stream = ChatStream(
            stream_id="stream-store",
            platform="test",
            user_info=UserInfo(platform="test", user_id="u1", user_nickname="user"),
            group_info=GroupInfo(platform="test", group_id="g1", group_name="group"),
        )

        await MessageStorage.store_message(message, stream)

        assert captured["additional_config"] == '{"custom": "value"}'
        assert MessageStorage._serialize_selected_expressions([1, 2]) == "[1, 2]"
    finally:
        storage_module.Messages.create = original_create


async def test_command_hooks() -> None:
    import src.chat.message_receive.bot as bot_module

    class FakeCommand(BaseCommand):
        executed = False
        executed_groups = None

        async def execute(self):
            self.__class__.executed = True
            self.__class__.executed_groups = dict(self.matched_groups)
            return True, "executed", 2

    class FailingCommand(BaseCommand):
        sent_texts = []

        async def execute(self):
            raise RuntimeError("boom")

        async def send_text(self, content, set_reply=False, reply_message=None, storage_message=True):
            self.__class__.sent_texts.append(content)
            return True

    class FakeComponentRegistry:
        def find_command_by_text(self, text: str):
            assert text == "!cmd"
            return FakeCommand, {"arg": "value"}, SimpleNamespace(plugin_name="plugin", name="cmd")

        def get_plugin_config(self, plugin_name: str) -> dict:
            assert plugin_name == "plugin"
            return {}

    class FailingComponentRegistry(FakeComponentRegistry):
        def find_command_by_text(self, text: str):
            assert text == "!cmd"
            return FailingCommand, {"arg": "value"}, SimpleNamespace(plugin_name="plugin", name="cmd")

    class FakeAnnouncementManager:
        def get_disabled_chat_commands(self, stream_id: str) -> list[str]:
            return []

    class FakeEvents:
        def __init__(self, before_modified=None, after_modified=None):
            self.before_modified = before_modified
            self.after_modified = after_modified
            self.events = []

        async def handle_mai_events(self, event_type, message, **kwargs):
            self.events.append((event_type, kwargs.get("extra_data")))
            if event_type == EventType.ON_COMMAND_BEFORE_EXECUTE:
                return True, self.before_modified
            if event_type == EventType.ON_COMMAND_AFTER_EXECUTE:
                return True, self.after_modified
            return True, None

    def build_message() -> MessageRecv:
        message = MessageRecv(
            {
                "message_info": _message_info("msg-command"),
                "message_segment": Seg(type="text", data="!cmd").to_dict(),
                "raw_message": "!cmd",
                "processed_plain_text": "!cmd",
            }
        )
        message.chat_stream = SimpleNamespace(stream_id="stream-command")
        return message

    original_registry = bot_module.component_registry
    original_events = bot_module.events_manager
    original_announcements = bot_module.global_announcement_manager
    try:
        bot_module.component_registry = FakeComponentRegistry()
        bot_module.global_announcement_manager = FakeAnnouncementManager()

        before_modified = MaiMessages(additional_data={
            "execute_command": False,
            "response": "blocked",
            "continue_process": False,
        })
        before_events = FakeEvents(before_modified=before_modified)
        bot_module.events_manager = before_events
        FakeCommand.executed = False
        result = await bot_module.ChatBot()._process_commands(build_message())
        assert result == (True, "blocked", False)
        assert FakeCommand.executed is False
        assert [event for event, _ in before_events.events] == [EventType.ON_COMMAND_BEFORE_EXECUTE]

        groups_modified = MaiMessages(additional_data={"matched_groups": {"arg": "rewritten"}})
        groups_events = FakeEvents(before_modified=groups_modified)
        bot_module.events_manager = groups_events
        FakeCommand.executed = False
        FakeCommand.executed_groups = None
        result = await bot_module.ChatBot()._process_commands(build_message())
        assert result == (True, "executed", False)
        assert FakeCommand.executed_groups == {"arg": "rewritten"}
        assert groups_events.events[1][1]["matched_groups"] == {"arg": "rewritten"}

        after_modified = MaiMessages(
            additional_data={
                "response": "after",
                "intercept_message_level": 0,
                "continue_process": True,
            }
        )
        after_events = FakeEvents(after_modified=after_modified)
        bot_module.events_manager = after_events
        FakeCommand.executed = False
        message = build_message()
        result = await bot_module.ChatBot()._process_commands(message)
        assert result == (True, "after", True)
        assert FakeCommand.executed is True
        assert message.intercept_message_level == 0
        assert [event for event, _ in after_events.events] == [
            EventType.ON_COMMAND_BEFORE_EXECUTE,
            EventType.ON_COMMAND_AFTER_EXECUTE,
        ]
        assert after_events.events[1][1]["success"] is True
        assert after_events.events[1][1]["intercept_message_level"] == 2

        bot_module.component_registry = FailingComponentRegistry()
        bot_module.events_manager = FakeEvents()
        FailingCommand.sent_texts = []
        result = await bot_module.ChatBot()._process_commands(build_message())
        assert result == (True, "boom", False)
        assert FailingCommand.sent_texts == ["命令执行出错: boom"]

        failure_modified = MaiMessages(
            additional_data={
                "response": "recovered",
                "intercept_message_level": 0,
                "continue_process": True,
            }
        )
        failure_events = FakeEvents(after_modified=failure_modified)
        bot_module.events_manager = failure_events
        FailingCommand.sent_texts = []
        message = build_message()
        result = await bot_module.ChatBot()._process_commands(message)
        assert result == (True, "recovered", True)
        assert message.intercept_message_level == 0
        assert failure_events.events[1][1]["success"] is False
        assert failure_events.events[1][1]["response"] == "boom"
        assert FailingCommand.sent_texts == []
    finally:
        bot_module.component_registry = original_registry
        bot_module.events_manager = original_events
        bot_module.global_announcement_manager = original_announcements


async def main() -> None:
    await test_lightweight_inbound()
    test_message_recv_json_additional_config()
    await test_media_background_enrichment()
    await test_send_service_build_hook()
    test_db_message_to_message_recv()
    test_turn_scheduler()
    await test_components_round_trip()
    test_webui_segment_parsing_forward()
    await test_webui_send_uses_components()
    await test_event_extra_data()
    await test_event_non_intercept_task_cleanup()
    await test_planner_hook_prompt_applied()
    test_inbound_hook_application()
    await test_message_storage_additional_config()
    await test_command_hooks()
    print("message-chain smoke checks passed")


if __name__ == "__main__":
    asyncio.run(main())
