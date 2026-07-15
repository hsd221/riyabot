"""WebUI 密码和会话管理。

历史版本把访问令牌当作密码，并将其明文写入 ``data/webui.json``。新版本只
持久化密码哈希，登录后使用独立的、带签名和过期时间的会话令牌。
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import re
import secrets
import stat
import tempfile
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

from src.common.logger import get_logger
from src.webui.error_utils import log_exception_type

logger = get_logger("webui")


class TokenManager:
    """管理 WebUI 密码、初始化状态和签名会话。"""

    PASSWORD_MIN_LENGTH = 8
    PASSWORD_MAX_LENGTH = 128
    SESSION_TTL_SECONDS = 7 * 24 * 60 * 60
    SCRYPT_N = 2**14
    SCRYPT_R = 8
    SCRYPT_P = 1
    SCRYPT_DKLEN = 32
    MAX_CONFIG_BYTES = 1024 * 1024
    _SESSION_NONCE_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
    _SESSION_SIGNATURE_PATTERN = re.compile(r"^[0-9a-f]{64}$")

    def __init__(self, config_path: Optional[Path] = None):
        if config_path is None:
            project_root = Path(__file__).parent.parent.parent
            config_path = project_root / "data" / "webui.json"

        self.config_path = Path(config_path)
        self._lock = threading.RLock()
        self._prepare_storage()
        self._ensure_config()

    def _prepare_storage(self) -> None:
        """创建并保护凭据目录，同时拒绝配置文件符号链接。"""
        parent = self.config_path.parent
        try:
            if parent.is_symlink():
                raise RuntimeError("WebUI 配置目录不能是符号链接")
            parent.mkdir(parents=True, exist_ok=True)
            parent_stat = os.lstat(parent)
            if not stat.S_ISDIR(parent_stat.st_mode):
                raise RuntimeError("WebUI 配置目录无效")

            parent_mode = stat.S_IMODE(parent_stat.st_mode)
            if parent_mode & 0o022:
                os.chmod(parent, parent_mode & ~0o022)

            if self.config_path.is_symlink():
                raise RuntimeError("WebUI 配置文件不能是符号链接")
        except RuntimeError:
            raise
        except OSError as exc:
            raise RuntimeError("无法安全初始化 WebUI 配置目录") from exc

    @contextmanager
    def _file_lock(self) -> Iterator[None]:
        """在多个 worker 进程之间串行化初始化和配置更新。"""
        lock_path = self.config_path.with_name(f"{self.config_path.name}.lock")
        if lock_path.is_symlink():
            raise RuntimeError("WebUI 配置锁文件路径无效")
        flags = os.O_CREAT | os.O_RDWR
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            fd = os.open(lock_path, flags, 0o600)
        except OSError as exc:
            raise RuntimeError("无法安全打开 WebUI 配置锁文件") from exc
        try:
            lock_stat = os.fstat(fd)
            if not stat.S_ISREG(lock_stat.st_mode) or lock_stat.st_nlink != 1:
                raise RuntimeError("WebUI 配置锁文件路径无效")
            if hasattr(os, "fchmod"):
                os.fchmod(fd, 0o600)
            try:
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_EX)
            except (ImportError, AttributeError):
                # Windows 没有 fcntl；进程内锁仍能保护常规开发环境。
                pass
            yield
        finally:
            try:
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_UN)
            except (ImportError, AttributeError):
                pass
            os.close(fd)

    def _default_config(self) -> dict:
        now = self._get_current_timestamp()
        return {
            "created_at": now,
            "updated_at": now,
            "first_setup_completed": False,
        }

    def _ensure_config(self) -> None:
        """创建最小配置，不生成密码或可登录令牌。"""
        with self._lock, self._file_lock():
            if not self.config_path.exists():
                logger.info(
                    "WebUI 配置文件不存在，创建待初始化状态",
                    event_code="webui.config.create_started",
                    path=str(self.config_path),
                )
                self._write_config_unlocked(self._default_config())
                return

            try:
                config = self._load_config()
            except (OSError, ValueError, TypeError) as error:
                log_exception_type(
                    logger,
                    "WebUI 配置文件读取失败，已拒绝进入未初始化状态",
                    error,
                    event_code="webui.config.load_failed",
                )
                raise RuntimeError(
                    f"WebUI 配置文件损坏或不可读：{self.config_path}。请修复该文件，或确认无需保留后再手动删除"
                ) from error

            changed = False
            if not config.get("created_at"):
                config["created_at"] = self._get_current_timestamp()
                changed = True
            if not config.get("updated_at"):
                config["updated_at"] = config["created_at"]
                changed = True
            if not isinstance(config.get("first_setup_completed"), bool):
                config["first_setup_completed"] = False
                changed = True
            # 旧版本可能写入空 access_token；它不应被视为密码。
            if "access_token" in config and not isinstance(config["access_token"], str):
                config.pop("access_token", None)
                changed = True
            if changed:
                config["updated_at"] = self._get_current_timestamp()
                self._write_config_unlocked(config)
            else:
                try:
                    os.chmod(self.config_path, 0o600)
                except OSError:
                    logger.warning("无法限制 WebUI 配置文件权限", event_code="webui.config.chmod_failed")

    def _load_config(self) -> dict:
        if self.config_path.is_symlink():
            raise ValueError("WebUI 配置文件路径无效")
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        file_descriptor = os.open(self.config_path, flags)
        try:
            config_stat = os.fstat(file_descriptor)
            if not stat.S_ISREG(config_stat.st_mode) or config_stat.st_nlink != 1:
                raise ValueError("WebUI 配置文件路径无效")
            if config_stat.st_size > self.MAX_CONFIG_BYTES:
                raise ValueError("WebUI 配置文件过大")
            with os.fdopen(file_descriptor, "rb") as file:
                file_descriptor = -1
                raw_value = file.read(self.MAX_CONFIG_BYTES + 1)
        finally:
            if file_descriptor >= 0:
                os.close(file_descriptor)

        if len(raw_value) > self.MAX_CONFIG_BYTES:
            raise ValueError("WebUI 配置文件过大")
        try:
            value = json.loads(raw_value.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("WebUI 配置文件格式无效") from exc
        if not isinstance(value, dict):
            raise ValueError("WebUI 配置必须是 JSON 对象")
        return value

    def _write_config_unlocked(self, config: dict) -> None:
        """原子写入配置，并将配置文件限制为仅所有者可读写。"""
        self._prepare_storage()
        fd, temp_name = tempfile.mkstemp(prefix=".webui-", suffix=".tmp", dir=self.config_path.parent)
        try:
            if hasattr(os, "fchmod"):
                os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as file:
                json.dump(config, file, ensure_ascii=False, indent=2)
                file.write("\n")
                file.flush()
                os.fsync(file.fileno())
            os.replace(temp_name, self.config_path)
            try:
                os.chmod(self.config_path, 0o600)
            except OSError:
                logger.warning("无法限制 WebUI 配置文件权限", event_code="webui.config.chmod_failed")
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

    def _save_config(self, config: dict) -> None:
        with self._lock, self._file_lock():
            self._write_config_unlocked(config)
        logger.info("WebUI 配置已保存", event_code="webui.config.saved", path=str(self.config_path))

    def _get_current_timestamp(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    @classmethod
    def validate_password(cls, password: str) -> tuple[bool, str]:
        """验证初始化和改密使用的密码策略。"""
        if not isinstance(password, str) or not password:
            return False, "密码不能为空"
        if len(password) < cls.PASSWORD_MIN_LENGTH:
            return False, f"密码长度至少为 {cls.PASSWORD_MIN_LENGTH} 位"
        if len(password) > cls.PASSWORD_MAX_LENGTH:
            return False, f"密码长度不能超过 {cls.PASSWORD_MAX_LENGTH} 位"
        if any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in password):
            return False, "密码不能包含换行或控制字符"
        if not any(char.isalpha() for char in password):
            return False, "密码必须包含字母"
        if not any(char.isdecimal() for char in password):
            return False, "密码必须包含数字"
        return True, "密码格式正确"

    @classmethod
    def _hash_password(cls, password: str) -> str:
        salt = secrets.token_bytes(16)
        digest = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=cls.SCRYPT_N,
            r=cls.SCRYPT_R,
            p=cls.SCRYPT_P,
            dklen=cls.SCRYPT_DKLEN,
        )

        def encode(value: bytes) -> str:
            return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")

        return f"scrypt${cls.SCRYPT_N}${cls.SCRYPT_R}${cls.SCRYPT_P}${encode(salt)}${encode(digest)}"

    @staticmethod
    def _decode_b64(value: str) -> bytes:
        return base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)

    @classmethod
    def _verify_password_hash(cls, password: str, encoded: str) -> bool:
        try:
            scheme, n_text, r_text, p_text, salt_text, digest_text = encoded.split("$")
            if scheme != "scrypt":
                return False
            n, r, p = int(n_text), int(r_text), int(p_text)
            # 参数来自磁盘配置，必须在进入高成本计算前固定到受支持值，
            # 避免损坏或被篡改的配置触发内存/CPU 资源耗尽。
            if (n, r, p) != (cls.SCRYPT_N, cls.SCRYPT_R, cls.SCRYPT_P):
                return False
            salt = cls._decode_b64(salt_text)
            expected = cls._decode_b64(digest_text)
            if len(salt) != 16 or len(expected) != cls.SCRYPT_DKLEN:
                return False
            actual = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=len(expected))
            return secrets.compare_digest(actual, expected)
        except (binascii.Error, ValueError, TypeError, UnicodeError, OverflowError):
            return False

    def is_password_configured(self) -> bool:
        config = self._load_config()
        return bool(config.get("password_hash") or config.get("access_token"))

    # 兼容调用方使用的命名。
    has_password = is_password_configured

    def get_token(self) -> str:
        """兼容旧调用但不再暴露任何明文凭据。"""
        return ""

    def get_adapter_config_path_preference(self) -> Optional[str]:
        """读取适配器配置路径偏好，不暴露其他凭据字段。"""
        with self._lock:
            value = self._load_config().get("adapter_config_path")
        return value if isinstance(value, str) and value else None

    def set_adapter_config_path_preference(self, path: str) -> None:
        """在同一受保护配置中原子保存适配器配置路径偏好。"""
        if not isinstance(path, str) or not path or len(path) > 4096:
            raise ValueError("适配器配置路径偏好无效")
        with self._lock, self._file_lock():
            config = self._load_config()
            config["adapter_config_path"] = path
            config["updated_at"] = self._get_current_timestamp()
            self._write_config_unlocked(config)

    def set_initial_password(self, password: str) -> tuple[bool, str]:
        """在未初始化状态下设置密码，成功后仍需完成其余向导步骤。"""
        valid, message = self.validate_password(password)
        if not valid:
            return False, message

        with self._lock, self._file_lock():
            config = self._load_config()
            if config.get("password_hash") or config.get("access_token"):
                return False, "密码已经设置"
            config["password_hash"] = self._hash_password(password)
            config["session_secret"] = secrets.token_urlsafe(32)
            config["session_version"] = 1
            config["password_configured_at"] = self._get_current_timestamp()
            config["updated_at"] = self._get_current_timestamp()
            config.pop("access_token", None)
            self._write_config_unlocked(config)
        logger.info("WebUI 初始密码已设置", event_code="webui.password.initialized")
        return True, "密码设置成功"

    def _migrate_legacy_password_unlocked(self, password: str, config: dict) -> None:
        config["password_hash"] = self._hash_password(password)
        config["session_secret"] = secrets.token_urlsafe(32)
        config["session_version"] = 1
        config["password_migrated_at"] = self._get_current_timestamp()
        config.pop("access_token", None)
        config["updated_at"] = self._get_current_timestamp()
        self._write_config_unlocked(config)
        logger.info("旧版 WebUI 令牌已迁移为密码哈希", event_code="webui.password.legacy_migrated")

    def authenticate(self, password: str) -> bool:
        """验证密码；旧版明文令牌只在首次成功验证时用于迁移。"""
        if not isinstance(password, str) or not password:
            return False
        try:
            with self._lock, self._file_lock():
                config = self._load_config()
                encoded = config.get("password_hash")
                if isinstance(encoded, str) and encoded:
                    return self._verify_password_hash(password, encoded)

                legacy = config.get("access_token")
                if not isinstance(legacy, str) or not legacy:
                    return False
                if not secrets.compare_digest(password, legacy):
                    return False
                self._migrate_legacy_password_unlocked(password, config)
                return True
        except (OSError, ValueError, TypeError, UnicodeError) as e:
            log_exception_type(logger, "WebUI 密码配置读取失败", e, event_code="webui.password.authenticate_failed")
            return False

    def verify_password(self, password: str) -> bool:
        return self.authenticate(password)

    def create_session(self) -> str:
        """创建带版本、过期时间和随机 nonce 的签名会话。"""
        with self._lock, self._file_lock():
            config = self._load_config()
            if not config.get("password_hash"):
                return ""
            secret = config.get("session_secret")
            try:
                version = int(config.get("session_version", 0))
            except (TypeError, ValueError):
                version = 0
            changed = False
            if not isinstance(secret, str) or not secret:
                secret = secrets.token_urlsafe(32)
                config["session_secret"] = secret
                version = max(version, 0) + 1
                config["session_version"] = version
                changed = True
            if version < 1:
                version = 1
                config["session_version"] = version
                changed = True
            if changed:
                config["updated_at"] = self._get_current_timestamp()
                self._write_config_unlocked(config)

        expires_at = int(time.time()) + self.SESSION_TTL_SECONDS
        payload = f"{version}.{expires_at}.{secrets.token_urlsafe(24)}"
        signature = hmac.new(secret.encode("utf-8"), payload.encode("ascii"), hashlib.sha256).hexdigest()
        return f"{payload}.{signature}"

    def verify_session(self, token: str) -> bool:
        if not isinstance(token, str) or len(token) > 512 or not token.isascii():
            return False
        try:
            version_text, expires_text, nonce, signature = token.split(".")
            if (
                not version_text.isdigit()
                or not expires_text.isdigit()
                or not self._SESSION_NONCE_PATTERN.fullmatch(nonce)
                or not self._SESSION_SIGNATURE_PATTERN.fullmatch(signature)
            ):
                return False
            version = int(version_text)
            expires_at = int(expires_text)
            if version < 1 or expires_at <= int(time.time()):
                return False
        except (ValueError, AttributeError, OverflowError):
            return False

        try:
            config = self._load_config()
        except (OSError, ValueError, TypeError):
            return False
        secret = config.get("session_secret")
        current_version = config.get("session_version")
        if not isinstance(secret, str) or type(current_version) is not int or version != current_version:
            return False
        payload = f"{version}.{expires_text}.{nonce}"
        try:
            expected = hmac.new(secret.encode("utf-8"), payload.encode("ascii"), hashlib.sha256).hexdigest()
            return secrets.compare_digest(signature, expected)
        except (UnicodeError, TypeError, ValueError):
            return False

    def verify_token(self, token: str) -> bool:
        """验证会话令牌，并短期兼容尚未迁移的旧版令牌。"""
        if not isinstance(token, str) or not token or len(token) > 512:
            return False
        if self.verify_session(token):
            return True
        try:
            config = self._load_config()
        except (OSError, ValueError, TypeError):
            return False
        legacy = config.get("access_token")
        if isinstance(legacy, str) and legacy and not config.get("password_hash"):
            if secrets.compare_digest(token, legacy):
                # 旧客户端可能直接携带 Bearer/query 令牌；首次成功认证也必须
                # 立即完成迁移，避免明文令牌长期留在配置文件中。
                return self.authenticate(token)
        return False

    def update_password(self, current_password: str, new_password: str) -> tuple[bool, str]:
        valid, message = self.validate_password(new_password)
        if not valid:
            return False, message
        if not self.authenticate(current_password):
            return False, "当前密码不正确"

        with self._lock, self._file_lock():
            config = self._load_config()
            encoded = config.get("password_hash")
            if not isinstance(encoded, str) or not self._verify_password_hash(current_password, encoded):
                return False, "当前密码不正确"
            try:
                current_version = int(config.get("session_version", 0))
            except (TypeError, ValueError, OverflowError):
                return False, "WebUI 会话配置无效"
            if current_version < 0:
                return False, "WebUI 会话配置无效"
            config["password_hash"] = self._hash_password(new_password)
            config["session_secret"] = secrets.token_urlsafe(32)
            config["session_version"] = current_version + 1
            config["password_updated_at"] = self._get_current_timestamp()
            config["updated_at"] = self._get_current_timestamp()
            self._write_config_unlocked(config)
        logger.info("WebUI 密码已更新", event_code="webui.password.updated")
        return True, "密码更新成功"

    def update_token(self, new_token: str) -> tuple[bool, str]:
        """拒绝旧版无当前密码校验的更新调用。"""
        del new_token
        return False, "旧版 Token 接口已停用，请使用密码修改接口"

    def regenerate_token(self) -> str:
        """旧版令牌生成接口已移除，避免重新引入可复制的明文凭证。"""
        raise ValueError("不再支持生成访问令牌，请在安全设置中修改密码")

    def is_first_setup(self) -> bool:
        config = self._load_config()
        return not bool(config.get("password_hash") or config.get("access_token")) or not bool(
            config.get("first_setup_completed", False)
        )

    def mark_setup_completed(self) -> bool:
        try:
            with self._lock, self._file_lock():
                config = self._load_config()
                if not config.get("password_hash"):
                    return False
                config["first_setup_completed"] = True
                config["setup_completed_at"] = self._get_current_timestamp()
                config.pop("setup_required_reason", None)
                config["updated_at"] = self._get_current_timestamp()
                self._write_config_unlocked(config)
            logger.info("WebUI 首次配置已标记为完成", event_code="webui.setup.completed")
            return True
        except Exception as e:
            log_exception_type(logger, "WebUI 首次配置标记失败", e, event_code="webui.setup.complete_failed")
            return False

    def reset_setup_status(self) -> bool:
        try:
            with self._lock, self._file_lock():
                config = self._load_config()
                config["first_setup_completed"] = False
                config.pop("setup_completed_at", None)
                config["updated_at"] = self._get_current_timestamp()
                self._write_config_unlocked(config)
            logger.info("WebUI 首次配置状态已重置", event_code="webui.setup.reset")
            return True
        except Exception as e:
            log_exception_type(logger, "WebUI 首次配置状态重置失败", e, event_code="webui.setup.reset_failed")
            return False


_token_manager_instance: Optional[TokenManager] = None
_token_manager_lock = threading.Lock()


def get_token_manager() -> TokenManager:
    """获取 TokenManager 单例。"""
    global _token_manager_instance
    if _token_manager_instance is None:
        with _token_manager_lock:
            if _token_manager_instance is None:
                _token_manager_instance = TokenManager()
    return _token_manager_instance
