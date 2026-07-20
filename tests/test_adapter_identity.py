import unittest

from src.services.adapter_identity import AdapterIdentityRegistry


class AdapterIdentityRegistryTest(unittest.TestCase):
    def test_register_resolve_and_unregister_identity_by_adapter_instance(self) -> None:
        registry = AdapterIdentityRegistry()

        identity = registry.register(
            adapter_id="onebot_default",
            platform="qq",
            account_id="10001",
            nickname="Riya",
        )

        self.assertEqual(identity.adapter_id, "onebot_default")
        self.assertEqual(registry.get("onebot_default"), identity)
        self.assertEqual(registry.get_for_platform("qq"), identity)
        self.assertTrue(registry.is_bot_account("qq", "10001"))
        self.assertFalse(registry.is_bot_account("qq", "other"))

        registry.unregister("onebot_default")

        self.assertIsNone(registry.get("onebot_default"))
        self.assertIsNone(registry.get_for_platform("qq"))
        self.assertFalse(registry.is_bot_account("qq", "10001"))

    def test_multiple_instances_on_the_same_platform_are_all_recognized(self) -> None:
        registry = AdapterIdentityRegistry()
        registry.register("onebot_primary", "qq", "10001", "Primary")
        registry.register("onebot_secondary", "qq", "10002", "Secondary")

        self.assertTrue(registry.is_bot_account("qq", "10001"))
        self.assertTrue(registry.is_bot_account("qq", "10002"))
        self.assertEqual(registry.get_for_platform("qq").account_id, "10002")

    def test_identity_values_are_trimmed_and_required(self) -> None:
        registry = AdapterIdentityRegistry()

        identity = registry.register(" onebot ", " qq ", " 10001 ", " Riya ")

        self.assertEqual(
            (identity.adapter_id, identity.platform, identity.account_id, identity.nickname),
            ("onebot", "qq", "10001", "Riya"),
        )
        for values in (
            ("", "qq", "10001"),
            ("onebot", "", "10001"),
            ("onebot", "qq", ""),
        ):
            with self.subTest(values=values), self.assertRaises(ValueError):
                registry.register(*values)


if __name__ == "__main__":
    unittest.main()
