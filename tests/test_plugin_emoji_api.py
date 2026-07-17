import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from src.plugin_system.apis import emoji_api


def make_emoji(
    emoji_hash: str,
    *,
    filename: str = "emoji.png",
    full_path: str | None = None,
    description: str = "开心表情",
    emotion: list[str] | None = None,
    is_deleted: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        hash=emoji_hash,
        filename=filename,
        full_path=full_path or f"/tmp/{filename}",
        description=description,
        emotion=["开心"] if emotion is None else emotion,
        is_deleted=is_deleted,
    )


def make_manager(emojis: list[SimpleNamespace] | None = None) -> SimpleNamespace:
    emojis = emojis or []
    return SimpleNamespace(
        emoji_objects=emojis,
        emoji_num=len([emoji for emoji in emojis if not emoji.is_deleted]),
        emoji_num_max=10,
        emoji_num_max_reach_deletion=True,
        record_usage=Mock(),
        get_emoji_for_text=AsyncMock(),
        get_emoji_candidates_by_vector=AsyncMock(),
        register_emoji_by_filename=AsyncMock(),
        get_emoji_from_manager=AsyncMock(),
        delete_emoji=AsyncMock(),
    )


class EmojiApiLookupTest(unittest.IsolatedAsyncioTestCase):
    async def test_get_by_emotion_vector_preserves_vector_availability_and_converts_matches(self) -> None:
        matching = make_emoji("match", filename="match.png", description="轻松调侃", emotion=["调侃"])
        unreadable = make_emoji("broken", filename="broken.png", description="损坏", emotion=["开心"])
        manager = make_manager([matching, unreadable])
        manager.get_emoji_candidates_by_vector.return_value = [
            (matching, "轻松调侃", 0.91),
            (unreadable, "开心", 0.82),
        ]

        with (
            patch.object(emoji_api, "get_emoji_manager", return_value=manager),
            patch.object(emoji_api, "image_path_to_base64", side_effect=["base64-match", ""]),
        ):
            result = await emoji_api.get_by_emotion_vector("轻松调侃", count=5)

        self.assertEqual(result, [("base64-match", "轻松调侃", "轻松调侃")])
        manager.get_emoji_candidates_by_vector.assert_awaited_once_with("轻松调侃", limit=5)
        manager.record_usage.assert_called_once_with("match")

        manager.get_emoji_candidates_by_vector.return_value = None
        with patch.object(emoji_api, "get_emoji_manager", return_value=manager):
            self.assertIsNone(await emoji_api.get_by_emotion_vector("不可用"))

        manager.get_emoji_candidates_by_vector.return_value = []
        with patch.object(emoji_api, "get_emoji_manager", return_value=manager):
            self.assertEqual(await emoji_api.get_by_emotion_vector("无匹配"), [])

    async def test_get_by_emotion_vector_validates_input(self) -> None:
        with self.assertRaises(ValueError):
            await emoji_api.get_by_emotion_vector("")
        with self.assertRaises(TypeError):
            await emoji_api.get_by_emotion_vector(123)  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            await emoji_api.get_by_emotion_vector("开心", count=0)

    async def test_get_by_description_validates_input_and_converts_manager_match_to_base64(self) -> None:
        manager = make_manager()
        manager.get_emoji_for_text.return_value = ("/tmp/happy.png", "开心表情", "开心")

        with (
            patch.object(emoji_api, "get_emoji_manager", return_value=manager),
            patch.object(emoji_api, "image_path_to_base64", return_value="base64-image") as to_base64,
        ):
            self.assertEqual(await emoji_api.get_by_description("开心"), ("base64-image", "开心表情", "开心"))

        manager.get_emoji_for_text.assert_awaited_once_with("开心")
        to_base64.assert_called_once_with("/tmp/happy.png")

        with self.assertRaises(ValueError):
            await emoji_api.get_by_description("")
        with self.assertRaises(TypeError):
            await emoji_api.get_by_description(123)  # type: ignore[arg-type]

    async def test_get_by_description_returns_none_for_missing_unreadable_and_manager_errors(self) -> None:
        manager = make_manager()
        manager.get_emoji_for_text.return_value = None

        with patch.object(emoji_api, "get_emoji_manager", return_value=manager):
            self.assertIsNone(await emoji_api.get_by_description("不存在"))

        manager.get_emoji_for_text.return_value = ("/tmp/missing.png", "坏表情", "疑惑")
        with (
            patch.object(emoji_api, "get_emoji_manager", return_value=manager),
            patch.object(emoji_api, "image_path_to_base64", return_value=""),
        ):
            self.assertIsNone(await emoji_api.get_by_description("坏图"))

        with patch.object(emoji_api, "get_emoji_manager", side_effect=RuntimeError("manager down")):
            self.assertIsNone(await emoji_api.get_by_description("异常"))

    async def test_get_random_filters_deleted_caps_count_records_usage_and_skips_unreadable_files(self) -> None:
        happy = make_emoji("happy", filename="happy.png", description="happy", emotion=["开心", "快乐"])
        sad = make_emoji("sad", filename="sad.png", description="sad", emotion=["难过"])
        deleted = make_emoji("deleted", is_deleted=True)
        manager = make_manager([happy, sad, deleted])

        with (
            patch.object(emoji_api, "get_emoji_manager", return_value=manager),
            patch.object(emoji_api.random, "sample", side_effect=lambda values, count: values[:count]),
            patch.object(emoji_api.random, "choice", side_effect=lambda values: values[0]),
            patch.object(emoji_api, "image_path_to_base64", side_effect=["base64-happy", ""]),
        ):
            result = await emoji_api.get_random(count=5)

        self.assertEqual(result, [("base64-happy", "happy", "开心")])
        manager.record_usage.assert_called_once_with("happy")

        self.assertEqual(await emoji_api.get_random(count=0), [])
        with self.assertRaises(ValueError):
            await emoji_api.get_random(count=-1)
        with self.assertRaises(TypeError):
            await emoji_api.get_random(count="1")  # type: ignore[arg-type]

    async def test_get_random_returns_empty_for_empty_deleted_unreadable_and_manager_errors(self) -> None:
        with patch.object(emoji_api, "get_emoji_manager", return_value=make_manager()):
            self.assertEqual(await emoji_api.get_random(count=1), [])

        deleted = make_emoji("deleted", is_deleted=True)
        with patch.object(emoji_api, "get_emoji_manager", return_value=make_manager([deleted])):
            self.assertEqual(await emoji_api.get_random(count=1), [])

        unreadable = make_emoji("unreadable")
        manager = make_manager([unreadable])
        with (
            patch.object(emoji_api, "get_emoji_manager", return_value=manager),
            patch.object(emoji_api.random, "sample", return_value=[unreadable]),
            patch.object(emoji_api, "image_path_to_base64", return_value=""),
        ):
            self.assertEqual(await emoji_api.get_random(count=1), [])
        manager.record_usage.assert_not_called()

        with patch.object(emoji_api, "get_emoji_manager", side_effect=RuntimeError("manager down")):
            self.assertEqual(await emoji_api.get_random(count=1), [])

    async def test_get_by_emotion_matches_case_insensitively_and_records_usage(self) -> None:
        matching = make_emoji("laugh", description="大笑", emotion=["Joy", "Funny"])
        other = make_emoji("sad", description="难过", emotion=["sad"])
        manager = make_manager([matching, other])

        with (
            patch.object(emoji_api, "get_emoji_manager", return_value=manager),
            patch.object(emoji_api.random, "choice", return_value=matching),
            patch.object(emoji_api, "image_path_to_base64", return_value="base64-laugh"),
        ):
            self.assertEqual(await emoji_api.get_by_emotion("joy"), ("base64-laugh", "大笑", "joy"))
            self.assertIsNone(await emoji_api.get_by_emotion("angry"))

        manager.record_usage.assert_called_once_with("laugh")

    async def test_get_by_emotion_validates_input_and_handles_conversion_or_manager_errors(self) -> None:
        with self.assertRaises(ValueError):
            await emoji_api.get_by_emotion("")
        with self.assertRaises(TypeError):
            await emoji_api.get_by_emotion(123)  # type: ignore[arg-type]

        matching = make_emoji("sad", description="难过", emotion=["sad"])
        manager = make_manager([matching])
        with (
            patch.object(emoji_api, "get_emoji_manager", return_value=manager),
            patch.object(emoji_api.random, "choice", return_value=matching),
            patch.object(emoji_api, "image_path_to_base64", return_value=""),
        ):
            self.assertIsNone(await emoji_api.get_by_emotion("sad"))
        manager.record_usage.assert_not_called()

        with patch.object(emoji_api, "get_emoji_manager", side_effect=RuntimeError("manager down")):
            self.assertIsNone(await emoji_api.get_by_emotion("sad"))


class EmojiApiInfoTest(unittest.IsolatedAsyncioTestCase):
    async def test_info_helpers_report_counts_emotions_descriptions_and_all_readable_emojis(self) -> None:
        first = make_emoji("first", description="第一个", emotion=["开心", "快乐"])
        second = make_emoji("second", description="第二个", emotion=[])
        deleted = make_emoji("deleted", description="删除", emotion=["难过"], is_deleted=True)
        manager = make_manager([first, second, deleted])
        manager.emoji_num_max = 20

        with (
            patch.object(emoji_api, "get_emoji_manager", return_value=manager),
            patch.object(emoji_api.random, "choice", side_effect=lambda values: values[0]),
            patch.object(emoji_api, "image_path_to_base64", side_effect=["base64-first", "base64-second"]),
        ):
            self.assertEqual(emoji_api.get_count(), 2)
            self.assertEqual(emoji_api.get_info(), {"current_count": 2, "max_count": 20, "available_emojis": 2})
            self.assertEqual(emoji_api.get_emotions(), ["开心", "快乐"])
            self.assertEqual(emoji_api.get_descriptions(), ["第一个", "第二个"])
            self.assertEqual(
                await emoji_api.get_all(),
                [("base64-first", "第一个", "开心"), ("base64-second", "第二个", "随机表情")],
            )

    async def test_info_helpers_return_empty_defaults_when_manager_fails(self) -> None:
        with patch.object(emoji_api, "get_emoji_manager", side_effect=RuntimeError("manager down")):
            self.assertEqual(emoji_api.get_count(), 0)
            self.assertEqual(emoji_api.get_info(), {"current_count": 0, "max_count": 0, "available_emojis": 0})
            self.assertEqual(emoji_api.get_emotions(), [])
            self.assertEqual(emoji_api.get_descriptions(), [])
            self.assertEqual(await emoji_api.get_all(), [])

    async def test_get_all_returns_empty_for_empty_store_and_skips_unreadable_files(self) -> None:
        with patch.object(emoji_api, "get_emoji_manager", return_value=make_manager()):
            self.assertEqual(await emoji_api.get_all(), [])

        unreadable = make_emoji("bad", description="坏图")
        deleted = make_emoji("deleted", is_deleted=True)
        with (
            patch.object(emoji_api, "get_emoji_manager", return_value=make_manager([unreadable, deleted])),
            patch.object(emoji_api, "image_path_to_base64", return_value=""),
        ):
            self.assertEqual(await emoji_api.get_all(), [])


class EmojiApiMutationTest(unittest.IsolatedAsyncioTestCase):
    async def test_register_emoji_validates_arguments(self) -> None:
        with self.assertRaises(ValueError):
            await emoji_api.register_emoji("")
        with self.assertRaises(TypeError):
            await emoji_api.register_emoji(123)  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            await emoji_api.register_emoji("base64-image", filename=object())  # type: ignore[arg-type]

    async def test_register_emoji_rejects_full_capacity_when_replacement_is_disabled(self) -> None:
        manager = make_manager([make_emoji("existing")])
        manager.emoji_num = 10
        manager.emoji_num_max = 10
        manager.emoji_num_max_reach_deletion = False

        with patch.object(emoji_api, "get_emoji_manager", return_value=manager):
            result = await emoji_api.register_emoji("base64-image", filename="new.png")

        self.assertFalse(result["success"])
        self.assertIn("表情包数量已达上限", result["message"])
        manager.register_emoji_by_filename.assert_not_awaited()

    async def test_register_emoji_saves_image_appends_extension_and_returns_new_metadata(self) -> None:
        manager = make_manager()
        created = make_emoji("new-hash", filename="custom.png", description="新表情", emotion=["惊喜"])

        async def register(filename: str) -> bool:
            manager.emoji_objects.append(created)
            manager.emoji_num = 1
            return True

        manager.register_emoji_by_filename.side_effect = register

        with (
            patch.object(emoji_api, "get_emoji_manager", return_value=manager),
            patch.object(emoji_api, "EMOJI_DIR", "/tmp/emoji-api"),
            patch.object(emoji_api.os, "makedirs") as makedirs,
            patch.object(emoji_api.os.path, "exists", return_value=False),
            patch.object(emoji_api, "base64_to_image", return_value=True) as to_image,
        ):
            result = await emoji_api.register_emoji("base64-image", filename="custom")

        self.assertEqual(
            result,
            {
                "success": True,
                "message": "表情包注册成功 (新增表情包)",
                "description": "新表情",
                "emotions": ["惊喜"],
                "replaced": False,
                "hash": "new-hash",
            },
        )
        makedirs.assert_called_once_with("/tmp/emoji-api", exist_ok=True)
        to_image.assert_called_once_with("base64-image", "/tmp/emoji-api/custom.png")
        manager.register_emoji_by_filename.assert_awaited_once_with("custom.png")

    async def test_register_emoji_cleans_temp_file_when_manager_rejects_saved_file(self) -> None:
        manager = make_manager()
        manager.register_emoji_by_filename.return_value = False
        saved_file = False

        def fake_exists(_path: str) -> bool:
            return saved_file

        def fake_base64_to_image(_image_base64: str, _temp_file_path: str) -> bool:
            nonlocal saved_file
            saved_file = True
            return True

        with (
            patch.object(emoji_api, "get_emoji_manager", return_value=manager),
            patch.object(emoji_api, "EMOJI_DIR", "/tmp/emoji-api"),
            patch.object(emoji_api.os, "makedirs"),
            patch.object(emoji_api.os.path, "exists", side_effect=fake_exists),
            patch.object(emoji_api, "base64_to_image", side_effect=fake_base64_to_image),
            patch.object(emoji_api.os, "remove") as remove,
        ):
            result = await emoji_api.register_emoji("base64-image", filename="bad.png")

        self.assertFalse(result["success"])
        self.assertEqual(result["message"], "表情包注册失败，可能因为重复、格式不支持或审核未通过")
        remove.assert_called_once_with("/tmp/emoji-api/bad.png")

    async def test_register_emoji_handles_auto_filename_collisions_and_generated_metadata(self) -> None:
        manager = make_manager()
        captured_filename = ""

        async def register(filename: str) -> bool:
            nonlocal captured_filename
            captured_filename = filename
            manager.emoji_objects.append(
                make_emoji("auto-hash", filename=filename, full_path=f"/tmp/emoji-api/{filename}", description="自动")
            )
            manager.emoji_num = 1
            return True

        manager.register_emoji_by_filename.side_effect = register

        with (
            patch.object(emoji_api, "get_emoji_manager", return_value=manager),
            patch.object(emoji_api, "EMOJI_DIR", "/tmp/emoji-api"),
            patch.object(emoji_api.os, "makedirs"),
            patch.object(emoji_api.os.path, "exists", side_effect=[True, False, False]),
            patch.object(emoji_api.random, "getrandbits", return_value=0),
            patch.object(emoji_api, "base64_to_image", return_value=True),
        ):
            result = await emoji_api.register_emoji("base64-image")

        self.assertTrue(result["success"])
        self.assertEqual(result["description"], "自动")
        self.assertEqual(result["hash"], "auto-hash")
        self.assertTrue(captured_filename.endswith(".png"))

    async def test_register_emoji_reports_filename_exhaustion_save_failures_and_cleanup_errors(self) -> None:
        manager = make_manager()
        with (
            patch.object(emoji_api, "get_emoji_manager", return_value=manager),
            patch.object(emoji_api, "EMOJI_DIR", "/tmp/emoji-api"),
            patch.object(emoji_api.os, "makedirs"),
            patch.object(emoji_api.os.path, "exists", return_value=True),
            patch.object(emoji_api.random, "getrandbits", return_value=0),
            patch.object(emoji_api.uuid, "uuid4", return_value="uuid-value"),
        ):
            exhausted = await emoji_api.register_emoji("base64-image", filename="fixed.png")
        self.assertFalse(exhausted["success"])
        self.assertEqual(exhausted["message"], "无法生成唯一文件名，请稍后重试")

        with (
            patch.object(emoji_api, "get_emoji_manager", return_value=manager),
            patch.object(emoji_api, "EMOJI_DIR", "/tmp/emoji-api"),
            patch.object(emoji_api.os, "makedirs"),
            patch.object(emoji_api.os.path, "exists", return_value=False),
            patch.object(emoji_api, "base64_to_image", return_value=False),
        ):
            save_failed = await emoji_api.register_emoji("base64-image", filename="bad.png")
        self.assertFalse(save_failed["success"])
        self.assertEqual(save_failed["message"], "无法保存图片文件")

        with (
            patch.object(emoji_api, "get_emoji_manager", return_value=manager),
            patch.object(emoji_api, "EMOJI_DIR", "/tmp/emoji-api"),
            patch.object(emoji_api.os, "makedirs"),
            patch.object(emoji_api.os.path, "exists", return_value=False),
            patch.object(emoji_api, "base64_to_image", side_effect=RuntimeError("decode down")),
        ):
            save_exception = await emoji_api.register_emoji("base64-image", filename="bad.png")
        self.assertFalse(save_exception["success"])
        self.assertEqual(save_exception["message"], "保存图片文件失败: decode down")

        manager.register_emoji_by_filename.return_value = False
        with (
            patch.object(emoji_api, "get_emoji_manager", return_value=manager),
            patch.object(emoji_api, "EMOJI_DIR", "/tmp/emoji-api"),
            patch.object(emoji_api.os, "makedirs"),
            patch.object(emoji_api.os.path, "exists", side_effect=[False, False, True]),
            patch.object(emoji_api, "base64_to_image", return_value=True),
            patch.object(emoji_api.os, "remove", side_effect=RuntimeError("cleanup down")),
        ):
            cleanup_failed = await emoji_api.register_emoji("base64-image", filename="cleanup.png")
        self.assertFalse(cleanup_failed["success"])
        self.assertEqual(cleanup_failed["message"], "表情包注册失败，可能因为重复、格式不支持或审核未通过")

    async def test_register_emoji_handles_metadata_lookup_and_outer_exceptions(self) -> None:
        class BadEmojiObjects:
            def __reversed__(self):
                raise RuntimeError("lookup down")

        manager = SimpleNamespace(
            emoji_num=0,
            emoji_num_max=10,
            emoji_num_max_reach_deletion=True,
            emoji_objects=BadEmojiObjects(),
            register_emoji_by_filename=AsyncMock(return_value=True),
        )

        async def register(_filename: str) -> bool:
            manager.emoji_num = 1
            return True

        manager.register_emoji_by_filename.side_effect = register

        with (
            patch.object(emoji_api, "get_emoji_manager", return_value=manager),
            patch.object(emoji_api, "EMOJI_DIR", "/tmp/emoji-api"),
            patch.object(emoji_api.os, "makedirs"),
            patch.object(emoji_api.os.path, "exists", return_value=False),
            patch.object(emoji_api, "base64_to_image", return_value=True),
        ):
            result = await emoji_api.register_emoji("base64-image", filename="meta.png")
        self.assertTrue(result["success"])
        self.assertIsNone(result["description"])
        self.assertIsNone(result["hash"])

        with patch.object(emoji_api, "get_emoji_manager", side_effect=RuntimeError("manager down")):
            failed = await emoji_api.register_emoji("base64-image", filename="bad.png")
        self.assertFalse(failed["success"])
        self.assertEqual(failed["message"], "注册过程中发生错误: manager down")

    async def test_delete_emoji_reports_deleted_metadata_counts_and_failures(self) -> None:
        target = make_emoji("hash-1", description="目标", emotion=["开心"])
        manager = make_manager([target])
        manager.get_emoji_from_manager.return_value = target

        async def delete(_emoji_hash: str) -> bool:
            manager.emoji_num = 0
            return True

        manager.delete_emoji.side_effect = delete

        with patch.object(emoji_api, "get_emoji_manager", return_value=manager):
            result = await emoji_api.delete_emoji("hash-1")

        self.assertEqual(
            result,
            {
                "success": True,
                "message": "表情包删除成功 (哈希: hash-1...)",
                "count_before": 1,
                "count_after": 0,
                "description": "目标",
                "emotions": ["开心"],
            },
        )
        manager.get_emoji_from_manager.assert_awaited_once_with("hash-1")
        manager.delete_emoji.assert_awaited_once_with("hash-1")

        with self.assertRaises(ValueError):
            await emoji_api.delete_emoji("")
        with self.assertRaises(TypeError):
            await emoji_api.delete_emoji(123)  # type: ignore[arg-type]

    async def test_delete_emoji_handles_info_lookup_delete_failure_and_manager_errors(self) -> None:
        manager = make_manager([make_emoji("hash-1")])
        manager.get_emoji_from_manager.side_effect = RuntimeError("info down")
        manager.delete_emoji.return_value = True
        with patch.object(emoji_api, "get_emoji_manager", return_value=manager):
            info_error = await emoji_api.delete_emoji("hash-1")
        self.assertTrue(info_error["success"])
        self.assertIsNone(info_error["description"])
        self.assertIsNone(info_error["emotions"])

        manager = make_manager([make_emoji("hash-1")])
        manager.get_emoji_from_manager.return_value = None
        manager.delete_emoji.return_value = False
        with patch.object(emoji_api, "get_emoji_manager", return_value=manager):
            delete_failed = await emoji_api.delete_emoji("hash-1")
        self.assertFalse(delete_failed["success"])
        self.assertEqual(delete_failed["message"], "表情包删除失败，可能因为哈希值不存在或删除过程出错")

        with patch.object(emoji_api, "get_emoji_manager", side_effect=RuntimeError("manager down")):
            failed = await emoji_api.delete_emoji("hash-1")
        self.assertFalse(failed["success"])
        self.assertEqual(failed["message"], "删除过程中发生错误: manager down")

    async def test_delete_emoji_by_description_supports_exact_and_fuzzy_matching(self) -> None:
        happy = make_emoji("happy", description="开心大笑")
        exact = make_emoji("exact", description="开心")
        deleted = make_emoji("deleted", description="开心", is_deleted=True)
        manager = make_manager([happy, exact, deleted])
        manager.delete_emoji.return_value = True

        with patch.object(emoji_api, "get_emoji_manager", return_value=manager):
            fuzzy = await emoji_api.delete_emoji_by_description("开心")

        self.assertTrue(fuzzy["success"])
        self.assertEqual(fuzzy["deleted_hashes"], ["happy", "exact"])
        self.assertEqual(fuzzy["matched_count"], 2)

        manager.delete_emoji.reset_mock()
        with patch.object(emoji_api, "get_emoji_manager", return_value=manager):
            exact_result = await emoji_api.delete_emoji_by_description("开心", exact_match=True)
            missing = await emoji_api.delete_emoji_by_description("不存在")

        self.assertTrue(exact_result["success"])
        self.assertEqual(exact_result["deleted_hashes"], ["exact"])
        self.assertFalse(missing["success"])
        self.assertEqual(missing["matched_count"], 0)

    async def test_delete_emoji_by_description_validates_and_reports_delete_failures(self) -> None:
        with self.assertRaises(ValueError):
            await emoji_api.delete_emoji_by_description("")
        with self.assertRaises(TypeError):
            await emoji_api.delete_emoji_by_description(123)  # type: ignore[arg-type]

        first = make_emoji("first", description="开心")
        second = make_emoji("second", description="开心")
        manager = make_manager([first, second])
        manager.delete_emoji.side_effect = [RuntimeError("delete down"), False]
        with patch.object(emoji_api, "get_emoji_manager", return_value=manager):
            failed = await emoji_api.delete_emoji_by_description("开心", exact_match=True)

        self.assertFalse(failed["success"])
        self.assertEqual(failed["message"], "匹配到 2 个表情包，但删除全部失败")
        self.assertEqual(failed["matched_count"], 2)
        self.assertEqual(failed["deleted_hashes"], [])

        with patch.object(emoji_api, "get_emoji_manager", side_effect=RuntimeError("manager down")):
            outer_failed = await emoji_api.delete_emoji_by_description("开心")
        self.assertFalse(outer_failed["success"])
        self.assertEqual(outer_failed["message"], "删除过程中发生错误: manager down")


if __name__ == "__main__":
    unittest.main()
