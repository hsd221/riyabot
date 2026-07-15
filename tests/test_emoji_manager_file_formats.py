import unittest

from src.chat.emoji_system.emoji_manager import is_supported_emoji_filename


class EmojiManagerFileFormatTest(unittest.TestCase):
    def test_pending_scanner_accepts_common_qq_emoji_formats(self) -> None:
        for filename in ("face.jpg", "face.JPEG", "face.png", "face.gif", "face.webp"):
            with self.subTest(filename=filename):
                self.assertTrue(is_supported_emoji_filename(filename))

        self.assertFalse(is_supported_emoji_filename("face.svg"))


if __name__ == "__main__":
    unittest.main()
