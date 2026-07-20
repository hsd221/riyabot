from __future__ import annotations

import time

from dataclasses import dataclass, field
from threading import RLock


@dataclass(frozen=True, slots=True)
class AdapterIdentity:
    adapter_id: str
    platform: str
    account_id: str
    nickname: str = ""
    registered_at: float = field(default_factory=time.time)

    def to_public_dict(self) -> dict[str, str]:
        return {"account_id": self.account_id, "nickname": self.nickname}


class AdapterIdentityRegistry:
    def __init__(self) -> None:
        self._identities: dict[str, AdapterIdentity] = {}
        self._lock = RLock()

    def register(
        self,
        adapter_id: str,
        platform: str,
        account_id: str,
        nickname: str = "",
    ) -> AdapterIdentity:
        normalized_adapter_id = str(adapter_id or "").strip()
        normalized_platform = str(platform or "").strip().lower()
        normalized_account_id = str(account_id or "").strip()
        normalized_nickname = str(nickname or "").strip()
        if not normalized_adapter_id or not normalized_platform or not normalized_account_id:
            raise ValueError("adapter_id, platform and account_id are required")

        identity = AdapterIdentity(
            adapter_id=normalized_adapter_id,
            platform=normalized_platform,
            account_id=normalized_account_id,
            nickname=normalized_nickname,
        )
        with self._lock:
            self._identities.pop(normalized_adapter_id, None)
            self._identities[normalized_adapter_id] = identity
        return identity

    def unregister(self, adapter_id: str) -> None:
        with self._lock:
            self._identities.pop(str(adapter_id or "").strip(), None)

    def get(self, adapter_id: str) -> AdapterIdentity | None:
        with self._lock:
            return self._identities.get(str(adapter_id or "").strip())

    def get_for_platform(self, platform: str) -> AdapterIdentity | None:
        normalized_platform = str(platform or "").strip().lower()
        with self._lock:
            identities = tuple(self._identities.values())
        return next(
            (identity for identity in reversed(identities) if identity.platform == normalized_platform),
            None,
        )

    def is_bot_account(self, platform: str, account_id: str) -> bool:
        normalized_platform = str(platform or "").strip().lower()
        normalized_account_id = str(account_id or "").strip()
        if not normalized_platform or not normalized_account_id:
            return False
        with self._lock:
            return any(
                identity.platform == normalized_platform and identity.account_id == normalized_account_id
                for identity in self._identities.values()
            )

    def list_identities(self) -> tuple[AdapterIdentity, ...]:
        with self._lock:
            return tuple(self._identities.values())

    def clear(self) -> None:
        with self._lock:
            self._identities.clear()


_adapter_identity_registry = AdapterIdentityRegistry()


def get_adapter_identity_registry() -> AdapterIdentityRegistry:
    return _adapter_identity_registry
