import asyncio
import base64
import hashlib
import unittest
from unittest.mock import patch

from maim_message import BaseMessageInfo, MessageBase, Seg, UserInfo

from src.common.data_models import BaseDataModel, transform_class_to_dict
from src.common.data_models.database_data_model import DatabaseActionRecords, DatabaseMessages
from src.common.data_models.llm_data_model import LLMGenerationDataModel
from src.common.data_models.message_component_model import (
    AtComponent,
    FileComponent,
    ForwardComponent,
    EmojiComponent,
    ImageComponent,
    MessageComponentSequence,
    ReplyComponent,
    SegmentListComponent,
    TextComponent,
    UnknownComponent,
    VoiceComponent,
    components_to_plain_text,
    from_components_to_seg,
    from_seg_to_components,
)
from src.common.data_models.message_data_model import (
    ForwardNode,
    MessageAndActionModel,
    ReplyContent,
    ReplyContentType,
    ReplySetModel,
)


class BaseDataModelTest(unittest.TestCase):
    def test_deepcopy_returns_independent_nested_model(self) -> None:
        model = LLMGenerationDataModel(content="hello", processed_output=["a"])

        copied = model.deepcopy()
        copied.processed_output.append("b")

        self.assertEqual(model.processed_output, ["a"])
        self.assertEqual(copied.processed_output, ["a", "b"])

    def test_transform_class_to_dict_recursively_converts_and_flattens_models(self) -> None:
        class SampleModel(BaseDataModel):
            nested = {"x": 1}
            label = "sample"

        message = DatabaseMessages(
            message_id="msg-1",
            time=1.5,
            processed_plain_text="hello",
            user_id="u1",
            user_nickname="Alice",
            user_platform="qq",
            chat_info_user_id="u1",
            chat_info_user_nickname="Alice",
            chat_info_user_platform="qq",
            chat_info_stream_id="stream-1",
            chat_info_platform="qq",
            chat_info_create_time=1.0,
            chat_info_last_active_time=2.0,
        )

        converted = transform_class_to_dict({"model": SampleModel, "message": message})

        self.assertEqual(converted["x"], 1)
        self.assertEqual(converted["label"], "sample")
        self.assertEqual(converted["message_id"], "msg-1")
        self.assertEqual(converted["user_nickname"], "Alice")

    def test_transform_class_to_dict_preserves_sequence_types_and_set_values(self) -> None:
        class NestedModel(BaseDataModel):
            values = (1, 2)
            tags = {"alpha", "beta"}

        transformed_list = transform_class_to_dict([NestedModel, {"items": (3, 4)}])
        transformed_tuple = transform_class_to_dict((NestedModel, {"items": [5]}))
        transformed_set = transform_class_to_dict({1, 2})

        self.assertEqual(transformed_list[0]["values"], (1, 2))
        self.assertEqual(transformed_list[0]["tags"], {"alpha", "beta"})
        self.assertEqual(transformed_list[1]["items"], (3, 4))
        self.assertEqual(transformed_tuple[0]["values"], (1, 2))
        self.assertEqual(transformed_tuple[1]["items"], [5])
        self.assertEqual(transformed_set, {1, 2})


class DatabaseDataModelTest(unittest.TestCase):
    def test_database_messages_builds_nested_info_and_flatten_preserves_legacy_fields(self) -> None:
        message = DatabaseMessages(
            message_id="msg-1",
            time=123.0,
            chat_id="chat-1",
            processed_plain_text="hello",
            is_command=True,
            intercept_message_level=2,
            user_id="u1",
            user_nickname="Alice",
            user_cardname="Ali",
            user_platform="qq",
            chat_info_group_id="g1",
            chat_info_group_name="Group",
            chat_info_group_platform="qq",
            chat_info_user_id="u2",
            chat_info_user_nickname="Bob",
            chat_info_user_platform="qq",
            chat_info_stream_id="stream-1",
            chat_info_platform="qq",
            chat_info_create_time=100.0,
            chat_info_last_active_time=120.0,
            extra_field="kept",
        )

        message.user_id = "u1-updated"
        message.user_nickname = "Alice2"
        message.user_cardname = "Ali2"
        message.user_platform = "qq-updated"
        flattened = message.flatten()

        self.assertEqual(message.user_id, "u1-updated")
        self.assertEqual(message.user_nickname, "Alice2")
        self.assertEqual(message.user_cardname, "Ali2")
        self.assertEqual(message.user_platform, "qq-updated")
        self.assertEqual(message.user_info.user_id, "u1-updated")
        self.assertEqual(message.user_info.user_nickname, "Alice2")
        self.assertEqual(message.user_info.user_cardname, "Ali2")
        self.assertEqual(message.user_info.platform, "qq-updated")
        self.assertEqual(message.chat_info.group_info.group_name, "Group")
        self.assertEqual(message.extra_field, "kept")
        self.assertEqual(flattened["message_id"], "msg-1")
        self.assertEqual(flattened["user_id"], "u1-updated")
        self.assertEqual(flattened["user_nickname"], "Alice2")
        self.assertEqual(flattened["user_cardname"], "Ali2")
        self.assertEqual(flattened["user_platform"], "qq-updated")
        self.assertEqual(flattened["chat_info_group_id"], "g1")
        self.assertEqual(flattened["intercept_message_level"], 2)

    def test_message_and_action_model_projects_database_message_fields(self) -> None:
        db_message = DatabaseMessages(
            message_id="msg-2",
            time=5.0,
            chat_id="chat-2",
            processed_plain_text="stored",
            display_message="display",
            is_command=True,
            intercept_message_level=3,
            user_id="u1",
            user_nickname="Alice",
            user_platform="qq",
            chat_info_user_id="u1",
            chat_info_user_nickname="Alice",
            chat_info_user_platform="qq",
            chat_info_stream_id="stream-2",
            chat_info_platform="qq",
        )

        projected = MessageAndActionModel.from_DatabaseMessages(db_message)

        self.assertEqual(projected.message_id, "msg-2")
        self.assertEqual(projected.processed_plain_text, "stored")
        self.assertTrue(projected.is_command)
        self.assertEqual(projected.intercept_message_level, 3)
        self.assertFalse(projected.is_action_record)

    def test_database_action_records_parses_json_action_data_and_rejects_non_string(self) -> None:
        record = DatabaseActionRecords(
            action_id="act-1",
            time=1.0,
            action_name="reply",
            action_data='{"text": "hello"}',
            action_done=True,
            action_build_into_prompt=False,
            action_prompt_display="display",
            chat_id="chat-1",
            chat_info_stream_id="stream-1",
            chat_info_platform="qq",
            action_reasoning="reason",
        )

        self.assertEqual(record.action_data, {"text": "hello"})
        with self.assertRaises(ValueError):
            DatabaseActionRecords(
                action_id="act-2",
                time=1.0,
                action_name="reply",
                action_data={"text": "hello"},
                action_done=True,
                action_build_into_prompt=False,
                action_prompt_display="display",
                chat_id="chat-1",
                chat_info_stream_id="stream-1",
                chat_info_platform="qq",
                action_reasoning="reason",
            )


class ReplyDataModelTest(unittest.TestCase):
    def test_reply_content_constructors_and_validation_enforce_list_shape_by_type(self) -> None:
        text = ReplyContent.construct_as_text("hello")
        image = ReplyContent.construct_as_image("image64")
        voice = ReplyContent.construct_as_voice("voice64")
        emoji = ReplyContent.construct_as_emoji("smile")
        command = ReplyContent.construct_as_command({"name": "ping"})
        hybrid = ReplyContent.construct_as_hybrid([(ReplyContentType.TEXT, "hello"), ("emoji", "smile")])
        forward = ReplyContent.construct_as_forward([ForwardNode.construct_as_id_reference("msg-1")])

        self.assertEqual(text.content_type, ReplyContentType.TEXT)
        self.assertEqual(text.content, "hello")
        self.assertEqual(image.content_type, ReplyContentType.IMAGE)
        self.assertEqual(voice.content_type, ReplyContentType.VOICE)
        self.assertEqual(emoji.content_type, ReplyContentType.EMOJI)
        self.assertEqual(command.content, {"name": "ping"})
        self.assertEqual(hybrid.content_type, ReplyContentType.HYBRID)
        self.assertEqual(len(hybrid.content), 2)
        self.assertEqual(forward.content[0].content, "msg-1")
        with self.assertRaises(ValueError):
            ReplyContent(ReplyContentType.TEXT, [ReplyContent.construct_as_text("bad")])
        with self.assertRaises(ValueError):
            ReplyContent(ReplyContentType.HYBRID, "not-a-list")

    def test_reply_set_collects_text_media_hybrid_custom_and_forward_content(self) -> None:
        reply_set = ReplySetModel()
        reply_set.add_text_content("hello")
        reply_set.add_image_content("image64")
        reply_set.add_voice_content("voice64")
        reply_set.add_hybrid_content_by_raw([(ReplyContentType.TEXT, "a"), (ReplyContentType.IMAGE, "b")])
        reply_set.add_hybrid_content([ReplyContent.construct_as_text("built")])
        reply_set.add_custom_content("custom", {"x": 1})
        reply_set.add_forward_content([ForwardNode.construct_as_created_node("u1", "Alice", [])])

        self.assertEqual(len(reply_set), 7)
        self.assertEqual(reply_set.reply_data[0].content_type, ReplyContentType.TEXT)
        self.assertEqual(reply_set.reply_data[3].content_type, ReplyContentType.HYBRID)
        self.assertEqual(reply_set.reply_data[4].content[0].content, "built")
        self.assertEqual(reply_set.reply_data[5].content, {"x": 1})
        self.assertEqual(reply_set.reply_data[6].content[0].user_nickname, "Alice")
        with self.assertRaises(AssertionError):
            reply_set.add_hybrid_content_by_raw([(ReplyContentType.FORWARD, "invalid")])
        with self.assertRaises(AssertionError):
            reply_set.add_hybrid_content([ReplyContent.construct_as_voice("voice64")])
        with self.assertRaises(AssertionError):
            reply_set.add_hybrid_content([ReplyContent(content_type=ReplyContentType.TEXT, content={"bad": "dict"})])


class MessageComponentModelTest(unittest.TestCase):
    def test_from_seg_to_components_hashes_media_and_formats_plain_text(self) -> None:
        image_base64 = base64.b64encode(b"image-data").decode("ascii")
        seq = MessageComponentSequence(
            [
                TextComponent("hello"),
                ImageComponent(base64_data=image_base64, description="cat"),
                VoiceComponent(transcript="hi"),
                AtComponent(target_user_id="u1", target_name="Alice"),
                ReplyComponent(target_message_id="msg-1", target_text="quoted"),
                FileComponent(name="report.pdf", size="10KB", url="https://example.test/report.pdf"),
                UnknownComponent(segment_type="custom", data={"x": 1}),
            ]
        )

        image_component = from_seg_to_components(Seg(type="image", data=image_base64)).components[0]
        invalid_image = from_seg_to_components(Seg(type="image", data="not base64!!")).components[0]

        self.assertEqual(image_component.image_hash, hashlib.md5(b"image-data").hexdigest())
        self.assertEqual(invalid_image.image_hash, hashlib.md5(b"not base64!!").hexdigest())
        self.assertEqual(
            components_to_plain_text(seq),
            "hello [图片：cat] [语音：hi] [@Alice] [回复：quoted] "
            "[文件: report.pdf, 大小: 10KB] 链接: https://example.test/report.pdf [custom:{'x': 1}]",
        )

    def test_from_seg_to_components_handles_empty_media_simple_segments_and_invalid_forward_nodes(self) -> None:
        emoji_base64 = base64.b64encode(b"emoji-data").decode("ascii")
        voice_base64 = base64.b64encode(b"voice-data").decode("ascii")

        empty = from_seg_to_components(None)
        empty_image = from_seg_to_components(Seg(type="image", data=None)).components[0]
        emoji = from_seg_to_components(Seg(type="emoji", data=emoji_base64)).components[0]
        voice = from_seg_to_components(Seg(type="voice", data=voice_base64)).components[0]
        at = from_seg_to_components(Seg(type="at", data=123)).components[0]
        reply = from_seg_to_components(Seg(type="reply", data="msg-1")).components[0]
        file_component = from_seg_to_components(Seg(type="file", data="report.pdf")).components[0]
        invalid_forward = from_seg_to_components(Seg(type="forward", data=[{"bad": "node"}])).components[0]

        self.assertEqual(empty.components, [])
        self.assertIsNone(empty_image.image_hash)
        self.assertEqual(emoji.emoji_hash, hashlib.md5(b"emoji-data").hexdigest())
        self.assertEqual(voice.voice_hash, hashlib.md5(b"voice-data").hexdigest())
        self.assertEqual(at.target_user_id, "123")
        self.assertEqual(reply.target_message_id, "msg-1")
        self.assertEqual(file_component.name, "report.pdf")
        self.assertIsInstance(invalid_forward.nodes[0].components[0], UnknownComponent)

        with patch.object(MessageBase, "from_dict", side_effect=RuntimeError("bad node")):
            failed_forward = from_seg_to_components(Seg(type="forward", data=[{"bad": "node"}])).components[0]
        self.assertIsInstance(failed_forward.nodes[0].components[0], UnknownComponent)

    def test_seglist_round_trip_preserves_nested_seglist_file_forward_and_unknown_segments(self) -> None:
        forward_raw = [
            MessageBase(
                message_segment=Seg(type="text", data="forward text"),
                message_info=BaseMessageInfo(user_info=UserInfo(user_id="u2", user_nickname="Bob")),
            ).to_dict()
        ]
        seg = Seg(
            type="seglist",
            data=[
                Seg(type="text", data="outer"),
                Seg(type="seglist", data=[Seg(type="text", data="inner")]),
                Seg(type="file", data={"file": "report.pdf", "file_size": "1024", "url": "https://example.test"}),
                Seg(type="forward", data=forward_raw),
                Seg(type="custom_card", data={"x": 1}),
            ],
        )

        seq = from_seg_to_components(seg)
        converted = asyncio.run(from_components_to_seg(seq))

        self.assertTrue(seq.force_seglist)
        self.assertIsInstance(seq.components[1], SegmentListComponent)
        self.assertIsInstance(seq.components[3], ForwardComponent)
        self.assertEqual(converted.type, "seglist")
        self.assertEqual(converted.data[1].type, "seglist")
        self.assertEqual(converted.data[2].data["file"], "report.pdf")
        self.assertEqual(converted.data[3].data, forward_raw)
        self.assertEqual(converted.data[4].type, "custom_card")

    def test_component_to_seg_fallbacks_and_plain_text_cover_media_forward_and_unknown_shapes(self) -> None:
        image_seg = asyncio.run(
            from_components_to_seg(MessageComponentSequence([ImageComponent(base64_data="image64")]))
        )
        image_text = asyncio.run(from_components_to_seg(MessageComponentSequence([ImageComponent(description="cat")])))
        emoji_seg = asyncio.run(
            from_components_to_seg(MessageComponentSequence([EmojiComponent(base64_data="emoji64")]))
        )
        emoji_text = asyncio.run(from_components_to_seg(MessageComponentSequence([EmojiComponent()])))
        voice_seg = asyncio.run(
            from_components_to_seg(MessageComponentSequence([VoiceComponent(base64_data="voice64")]))
        )
        voice_text = asyncio.run(from_components_to_seg(MessageComponentSequence([VoiceComponent()])))
        at_seg = asyncio.run(from_components_to_seg(MessageComponentSequence([AtComponent(target_user_id="u1")])))
        reply_seg = asyncio.run(
            from_components_to_seg(MessageComponentSequence([ReplyComponent(target_message_id="msg-1")]))
        )
        file_seg = asyncio.run(from_components_to_seg(MessageComponentSequence([FileComponent(name="report.pdf")])))
        forward_seg = asyncio.run(
            from_components_to_seg(
                MessageComponentSequence([ForwardComponent(nodes=[MessageComponentSequence([TextComponent("hi")])])])
            )
        )
        multi_seg = asyncio.run(
            from_components_to_seg(MessageComponentSequence([TextComponent("a"), TextComponent("b")]))
        )

        self.assertEqual((image_seg.type, image_seg.data), ("image", "image64"))
        self.assertEqual((image_text.type, image_text.data), ("text", "[图片：cat]"))
        self.assertEqual((emoji_seg.type, emoji_seg.data), ("emoji", "emoji64"))
        self.assertEqual((emoji_text.type, emoji_text.data), ("text", "[表情包]"))
        self.assertEqual((voice_seg.type, voice_seg.data), ("voice", "voice64"))
        self.assertEqual((voice_text.type, voice_text.data), ("text", "[语音消息]"))
        self.assertEqual((at_seg.type, at_seg.data), ("at", "u1"))
        self.assertEqual((reply_seg.type, reply_seg.data), ("reply", "msg-1"))
        self.assertEqual(file_seg.data, {"name": "report.pdf", "size": None, "url": None})
        self.assertEqual(forward_seg.type, "forward")
        self.assertEqual(forward_seg.data[0]["message_segment"]["data"], "hi")
        self.assertEqual(multi_seg.type, "seglist")
        self.assertEqual([seg.data for seg in multi_seg.data], ["a", "b"])

        plain = components_to_plain_text(
            MessageComponentSequence(
                [
                    EmojiComponent(description="smile"),
                    ReplyComponent(target_message_id="msg-1"),
                    ForwardComponent(nodes=[MessageComponentSequence([TextComponent("nested")])]),
                    SegmentListComponent(sequence=MessageComponentSequence([TextComponent("inner")])),
                    UnknownComponent(segment_type="empty", data=None),
                ]
            )
        )

        self.assertEqual(plain, "[表情包：smile] [回复:msg-1] [合并消息]: nested inner [empty]")

    def test_empty_and_multi_component_sequences_convert_to_expected_seg_shapes(self) -> None:
        empty_seg = asyncio.run(from_components_to_seg(MessageComponentSequence()))
        single_seg = asyncio.run(from_components_to_seg(MessageComponentSequence([TextComponent("one")])))
        forced_seg = asyncio.run(
            from_components_to_seg(MessageComponentSequence([TextComponent("one")], force_seglist=True))
        )

        self.assertEqual((empty_seg.type, empty_seg.data), ("text", ""))
        self.assertEqual((single_seg.type, single_seg.data), ("text", "one"))
        self.assertEqual(forced_seg.type, "seglist")
        self.assertEqual(forced_seg.data[0].data, "one")


if __name__ == "__main__":
    unittest.main()
