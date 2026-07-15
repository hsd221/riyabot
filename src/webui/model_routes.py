"""
模型列表获取API路由

提供从各个 AI 厂商 API 获取可用模型列表的代理接口
"""

import asyncio
import ipaddress
import json
import os
import re
import socket
import time
from typing import Literal, Optional
from urllib.parse import urlsplit, urlunsplit

import httpx
import tomlkit
from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field

from src.common.logger import get_logger
from src.config.config import CONFIG_DIR
from src.webui.auth import verify_auth_token_from_cookie_or_header
from src.webui.error_utils import log_exception_type

logger = get_logger("webui")

router = APIRouter(prefix="/models", tags=["models"])

MAX_MODEL_RESPONSE_BYTES = 5 * 1024 * 1024
"""模型供应商响应体上限（5 MiB，按解压后的字节计）。"""

MAX_MODEL_ITEMS = 10_000
MAX_MODEL_FIELD_CHARS = 512
_MAX_MODEL_URL_LENGTH = 4096
_MAX_MODEL_ENDPOINT_LENGTH = 2048
_TRUE_VALUES = {"1", "true", "yes"}
_NAT64_WELL_KNOWN_PREFIX = ipaddress.ip_network("64:ff9b::/96")
_IPV4_COMPATIBLE_PREFIX = ipaddress.ip_network("::/96")
_PRIVATE_MODEL_NETWORKS = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("fc00::/7"),
)
_BLOCKED_MODEL_ADDRESSES = frozenset(
    {
        ipaddress.ip_address("169.254.169.254"),
        ipaddress.ip_address("fd00:ec2::254"),
    }
)


class ModelResponseTooLargeError(ValueError):
    """模型供应商响应超过允许大小。"""


class ModelsByURLRequest(BaseModel):
    """通过自定义 URL 获取模型列表的请求体。"""

    base_url: str = Field(..., min_length=1, max_length=_MAX_MODEL_URL_LENGTH)
    api_key: str = Field(..., min_length=1, max_length=8192)
    parser: Literal["openai", "gemini"] = "openai"
    endpoint: str = Field("/models", min_length=1, max_length=_MAX_MODEL_ENDPOINT_LENGTH)
    client_type: Literal["openai", "gemini"] = "openai"


class TestConnectionRequest(BaseModel):
    """测试模型供应商连接的请求体。"""

    base_url: str = Field(..., min_length=1, max_length=_MAX_MODEL_URL_LENGTH)
    api_key: Optional[str] = Field(None, max_length=8192)


def require_auth(
    maibot_session: Optional[str] = Cookie(None),
    authorization: Optional[str] = Header(None),
) -> bool:
    """认证依赖：验证用户是否已登录"""
    return verify_auth_token_from_cookie_or_header(maibot_session, authorization)


# 模型获取器配置
MODEL_FETCHER_CONFIG = {
    # OpenAI 兼容格式的提供商
    "openai": {
        "endpoint": "/models",
        "parser": "openai",
    },
    # Gemini 格式
    "gemini": {
        "endpoint": "/models",
        "parser": "gemini",
    },
}


def _normalize_url(url: str) -> str:
    """规范化 URL（去掉尾部斜杠）"""
    if not url:
        return ""
    return url.rstrip("/")


def _env_enabled(name: str) -> bool:
    return os.getenv(name, "").lower() in _TRUE_VALUES


def _validate_url_text(value: str, *, maximum_length: int, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} 不能为空")
    if value != value.strip() or len(value) > maximum_length:
        raise ValueError(f"{field_name} 格式无效")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError(f"{field_name} 包含控制字符")
    return value


def _ascii_hostname(host: str) -> str:
    if not host or host.startswith("-") or "%" in host:
        raise ValueError("模型服务主机名格式无效")

    try:
        return str(ipaddress.ip_address(host))
    except ValueError:
        pass

    try:
        ascii_host = host.encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise ValueError("模型服务主机名格式无效") from exc

    host_without_root_dot = ascii_host[:-1] if ascii_host.endswith(".") else ascii_host
    labels = host_without_root_dot.split(".")
    if (
        not host_without_root_dot
        or len(ascii_host) > 253
        or any(len(label) > 63 or not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", label) for label in labels)
    ):
        raise ValueError("模型服务主机名格式无效")
    return ascii_host


def _validate_model_base_url(base_url: str) -> str:
    base_url = _validate_url_text(
        base_url,
        maximum_length=_MAX_MODEL_URL_LENGTH,
        field_name="base_url",
    )
    try:
        parsed = urlsplit(base_url)
        scheme = parsed.scheme.lower()
        hostname = parsed.hostname
        _ = parsed.port
    except ValueError as exc:
        raise ValueError("base_url 格式无效") from exc

    if scheme not in {"http", "https"}:
        raise ValueError("base_url 仅允许 HTTP(S) 协议")
    if not hostname:
        raise ValueError("base_url 缺少主机名")
    _ascii_hostname(hostname)
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("base_url 不允许内嵌认证凭据")
    if parsed.query:
        raise ValueError("base_url 不允许包含查询参数")
    if parsed.fragment:
        raise ValueError("base_url 不允许包含片段")
    return base_url.rstrip("/")


def _validate_model_endpoint(endpoint: str) -> str:
    endpoint = _validate_url_text(
        endpoint,
        maximum_length=_MAX_MODEL_ENDPOINT_LENGTH,
        field_name="endpoint",
    )
    parsed = urlsplit(endpoint)
    if not endpoint.startswith("/") or endpoint.startswith("//") or parsed.scheme or parsed.netloc:
        raise ValueError("endpoint 必须是以单个 / 开头的相对路径")
    if parsed.query:
        raise ValueError("endpoint 不允许包含查询参数")
    if parsed.fragment:
        raise ValueError("endpoint 不允许包含片段")
    return endpoint


def _build_provider_url(base_url: str, endpoint: str) -> str:
    return f"{_validate_model_base_url(base_url)}{_validate_model_endpoint(endpoint)}"


def _is_public_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if not address.is_global:
        return False

    if isinstance(address, ipaddress.IPv6Address):
        embedded_addresses = [
            candidate for candidate in (address.ipv4_mapped, address.sixtofour) if candidate is not None
        ]
        if address.teredo is not None:
            embedded_addresses.extend(address.teredo)
        if address in _NAT64_WELL_KNOWN_PREFIX or address in _IPV4_COMPATIBLE_PREFIX:
            embedded_addresses.append(ipaddress.IPv4Address(int(address) & 0xFFFFFFFF))
        if any(not embedded.is_global for embedded in embedded_addresses):
            return False
    return True


def _is_allowed_model_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if address in _BLOCKED_MODEL_ADDRESSES:
        return False
    if _is_public_address(address) or address.is_loopback:
        return True
    return any(address in network for network in _PRIVATE_MODEL_NETWORKS if address.version == network.version)


async def _resolve_model_host(host: str, port: int, scheme: str) -> tuple[str, ...]:
    ascii_host = _ascii_hostname(host)
    try:
        addresses = [ipaddress.ip_address(ascii_host)]
    except ValueError:
        try:
            address_info = await asyncio.to_thread(
                socket.getaddrinfo,
                ascii_host,
                port,
                type=socket.SOCK_STREAM,
            )
        except OSError as exc:
            raise ValueError("无法解析模型服务主机名") from exc

        addresses = []
        for item in address_info:
            address = ipaddress.ip_address(item[4][0])
            if address not in addresses:
                addresses.append(address)

    if not addresses:
        raise ValueError("无法解析模型服务主机名")
    if any(not _is_allowed_model_address(address) for address in addresses):
        raise ValueError("模型服务地址属于禁止访问的网络范围")
    if (
        scheme == "http"
        and any(_is_public_address(address) for address in addresses)
        and not _env_enabled("MAIBOT_ALLOW_INSECURE_MODEL_URLS")
    ):
        raise ValueError("公网模型服务必须使用 HTTPS")
    return tuple(str(address) for address in addresses)


def _format_ip_for_url(address: str) -> str:
    return f"[{address}]" if ":" in address else address


def _build_pinned_request(url: str, address: str) -> tuple[str, dict[str, str], dict[str, str]]:
    parsed = urlsplit(url)
    hostname = _ascii_hostname(parsed.hostname or "")
    pinned_netloc = _format_ip_for_url(address)
    host_header = f"[{hostname}]" if ":" in hostname else hostname
    if parsed.port is not None:
        pinned_netloc = f"{pinned_netloc}:{parsed.port}"
        host_header = f"{host_header}:{parsed.port}"

    pinned_url = urlunsplit((parsed.scheme, pinned_netloc, parsed.path, parsed.query, ""))
    extensions = {"sni_hostname": hostname} if parsed.scheme.lower() == "https" else {}
    return pinned_url, {"Host": host_header}, extensions


async def _prepare_model_request(url: str) -> tuple[str, ...]:
    parsed = urlsplit(url)
    scheme = parsed.scheme.lower()
    port = parsed.port or (443 if scheme == "https" else 80)
    return await _resolve_model_host(parsed.hostname or "", port, scheme)


async def _read_limited_response(response: httpx.Response) -> bytes:
    content_length = response.headers.get("content-length")
    if content_length:
        try:
            declared_length = int(content_length)
        except ValueError:
            declared_length = 0
        if declared_length > MAX_MODEL_RESPONSE_BYTES:
            raise ModelResponseTooLargeError("模型供应商响应过大")

    body = bytearray()
    async for chunk in response.aiter_bytes():
        if len(body) + len(chunk) > MAX_MODEL_RESPONSE_BYTES:
            raise ModelResponseTooLargeError("模型供应商响应过大")
        body.extend(chunk)
    return bytes(body)


def _parse_openai_response(data: dict) -> list[dict]:
    """
    解析 OpenAI 格式的模型列表响应

    格式: { "data": [{ "id": "gpt-4", "object": "model", ... }] }
    """
    models = []
    if "data" in data and isinstance(data["data"], list):
        for model in data["data"][:MAX_MODEL_ITEMS]:
            if isinstance(model, dict):
                model_id = model.get("id")
                if not isinstance(model_id, str) or not 1 <= len(model_id) <= MAX_MODEL_FIELD_CHARS:
                    continue
                model_name = model.get("name")
                if not isinstance(model_name, str) or not 1 <= len(model_name) <= MAX_MODEL_FIELD_CHARS:
                    model_name = model_id
                owned_by = model.get("owned_by", "")
                if not isinstance(owned_by, str) or len(owned_by) > MAX_MODEL_FIELD_CHARS:
                    owned_by = ""
                models.append(
                    {
                        "id": model_id,
                        "name": model_name,
                        "owned_by": owned_by,
                    }
                )
    return models


def _parse_gemini_response(data: dict) -> list[dict]:
    """
    解析 Gemini 格式的模型列表响应

    格式: { "models": [{ "name": "models/gemini-pro", "displayName": "Gemini Pro", ... }] }
    """
    models = []
    if "models" in data and isinstance(data["models"], list):
        for model in data["models"][:MAX_MODEL_ITEMS]:
            if isinstance(model, dict):
                # Gemini 的 name 格式是 "models/gemini-pro"，我们只取后面部分
                model_id = model.get("name")
                if not isinstance(model_id, str) or not 1 <= len(model_id) <= MAX_MODEL_FIELD_CHARS + 7:
                    continue
                if model_id.startswith("models/"):
                    model_id = model_id[7:]  # 去掉 "models/" 前缀
                if not model_id or len(model_id) > MAX_MODEL_FIELD_CHARS:
                    continue
                model_name = model.get("displayName")
                if not isinstance(model_name, str) or not 1 <= len(model_name) <= MAX_MODEL_FIELD_CHARS:
                    model_name = model_id
                models.append(
                    {
                        "id": model_id,
                        "name": model_name,
                        "owned_by": "google",
                    }
                )
    return models


async def _fetch_models_from_provider(
    base_url: str,
    api_key: str,
    endpoint: str,
    parser: str,
    client_type: str = "openai",
) -> list[dict]:
    """
    从提供商 API 获取模型列表

    Args:
        base_url: 提供商的基础 URL
        api_key: API 密钥
        endpoint: 获取模型列表的端点
        parser: 响应解析器类型 ('openai' | 'gemini')
        client_type: 客户端类型 ('openai' | 'gemini')

    Returns:
        模型列表
    """
    if parser not in {"openai", "gemini"}:
        raise HTTPException(status_code=400, detail=f"不支持的解析器类型: {parser}")
    if client_type not in {"openai", "gemini"}:
        raise HTTPException(status_code=400, detail="不支持的客户端类型")

    try:
        url = _build_provider_url(base_url, endpoint)
        addresses = await _prepare_model_request(url)
    except ValueError:
        raise HTTPException(status_code=400, detail="模型供应商 URL 或端点无效") from None

    # 根据客户端类型设置请求头
    auth_headers = {}
    params = {}

    if client_type == "gemini":
        # 使用请求头避免 API Key 出现在 URL、代理日志和异常文本中
        auth_headers["x-goog-api-key"] = api_key
    else:
        # OpenAI 兼容格式使用 Authorization 头
        auth_headers["Authorization"] = f"Bearer {api_key}"

    try:
        last_request_error: Optional[httpx.RequestError] = None
        async with httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=False,
            trust_env=_env_enabled("MAIBOT_ALLOW_MODEL_PROXY"),
        ) as client:
            for address in addresses:
                pinned_url, pinned_headers, request_extensions = _build_pinned_request(url, address)
                request_headers = {**pinned_headers, **auth_headers}
                try:
                    async with client.stream(
                        "GET",
                        pinned_url,
                        headers=request_headers,
                        params=params,
                        extensions=request_extensions,
                    ) as response:
                        response.raise_for_status()
                        raw_body = await _read_limited_response(response)
                    try:
                        data = json.loads(raw_body)
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        raise HTTPException(status_code=502, detail="上游模型列表响应格式无效") from None
                    if not isinstance(data, dict):
                        raise HTTPException(status_code=502, detail="上游模型列表响应格式无效")
                    break
                except (httpx.ConnectError, httpx.TimeoutException) as exc:
                    last_request_error = exc
            else:
                if isinstance(last_request_error, httpx.TimeoutException):
                    raise HTTPException(status_code=504, detail="请求超时，请稍后重试") from None
                raise HTTPException(status_code=502, detail="无法连接模型供应商") from None
    except HTTPException:
        raise
    except ModelResponseTooLargeError:
        raise HTTPException(status_code=502, detail="上游模型列表响应过大，最大允许 5 MiB") from None
    except httpx.HTTPStatusError as exc:
        # 注意：使用 502 Bad Gateway 而不是原始的 401/403，
        # 因为前端的 fetchWithAuth 会把 401 当作 WebUI 认证失败处理
        if exc.response.status_code == 401:
            raise HTTPException(status_code=502, detail="API Key 无效或已过期") from None
        elif exc.response.status_code == 403:
            raise HTTPException(status_code=502, detail="没有权限访问模型列表，请检查 API Key 权限") from None
        elif exc.response.status_code == 404:
            raise HTTPException(status_code=502, detail="该提供商不支持获取模型列表") from None
        elif 300 <= exc.response.status_code < 400:
            raise HTTPException(status_code=502, detail="上游服务返回重定向，已拒绝跟随") from None
        else:
            raise HTTPException(status_code=502, detail=f"上游服务请求失败 ({exc.response.status_code})") from None
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="请求超时，请稍后重试") from None
    except httpx.RequestError as exc:
        logger.warning("获取模型列表请求失败", error_type=type(exc).__name__)
        raise HTTPException(status_code=502, detail="无法连接模型供应商") from None
    except Exception as exc:
        logger.error("获取模型列表失败", error_type=type(exc).__name__)
        raise HTTPException(status_code=500, detail="获取模型列表失败") from None

    # 根据解析器类型解析响应
    if parser == "openai":
        return _parse_openai_response(data)
    return _parse_gemini_response(data)


def _get_provider_config(provider_name: str) -> Optional[dict]:
    """
    从 model_config.toml 获取指定提供商的配置

    Args:
        provider_name: 提供商名称

    Returns:
        提供商配置，如果未找到则返回 None
    """
    config_path = os.path.join(CONFIG_DIR, "model_config.toml")
    if not os.path.exists(config_path):
        return None

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config_data = tomlkit.load(f)

        providers = config_data.get("api_providers", [])
        for provider in providers:
            if provider.get("name") == provider_name:
                return dict(provider)

        return None
    except Exception as e:
        log_exception_type(logger, "读取提供商配置失败", e)
        return None


@router.get("/list")
async def get_provider_models(
    provider_name: str = Query(..., description="提供商名称"),
    parser: str = Query("openai", description="响应解析器类型 (openai | gemini)"),
    endpoint: str = Query("/models", description="获取模型列表的端点"),
    _auth: bool = Depends(require_auth),
):
    """
    获取指定提供商的可用模型列表

    通过提供商名称查找配置，然后请求对应的模型列表端点
    """
    # 获取提供商配置
    provider_config = _get_provider_config(provider_name)
    if not provider_config:
        raise HTTPException(status_code=404, detail=f"未找到提供商: {provider_name}")

    base_url = provider_config.get("base_url")
    api_key = provider_config.get("api_key")
    client_type = provider_config.get("client_type", "openai")

    if not base_url:
        raise HTTPException(status_code=400, detail="提供商配置缺少 base_url")
    if not api_key:
        raise HTTPException(status_code=400, detail="提供商配置缺少 api_key")

    # 获取模型列表
    models = await _fetch_models_from_provider(
        base_url=base_url,
        api_key=api_key,
        endpoint=endpoint,
        parser=parser,
        client_type=client_type,
    )

    return {
        "success": True,
        "models": models,
        "provider": provider_name,
        "count": len(models),
    }


@router.post("/list-by-url")
async def get_models_by_url(
    request: ModelsByURLRequest,
    _auth: bool = Depends(require_auth),
):
    """
    通过 URL 直接获取模型列表（用于自定义提供商）
    """
    models = await _fetch_models_from_provider(
        base_url=request.base_url,
        api_key=request.api_key,
        endpoint=request.endpoint,
        parser=request.parser,
        client_type=request.client_type,
    )

    return {
        "success": True,
        "models": models,
        "count": len(models),
    }


async def _request_provider_status(url: str, headers: Optional[dict[str, str]], timeout: float) -> int:
    addresses = await _prepare_model_request(url)
    last_request_error: Optional[httpx.RequestError] = None

    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=False,
        trust_env=_env_enabled("MAIBOT_ALLOW_MODEL_PROXY"),
    ) as client:
        for address in addresses:
            pinned_url, pinned_headers, request_extensions = _build_pinned_request(url, address)
            request_headers = {**pinned_headers, **(headers or {})}
            try:
                async with client.stream(
                    "GET",
                    pinned_url,
                    headers=request_headers,
                    extensions=request_extensions,
                ) as response:
                    return response.status_code
            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                last_request_error = exc

    if last_request_error is not None:
        raise last_request_error
    raise httpx.ConnectError("provider connection failed")


@router.post("/test-connection")
async def test_provider_connection(
    request: TestConnectionRequest,
    _auth: bool = Depends(require_auth),
):
    """
    测试提供商连接状态

    分两步测试：
    1. 网络连通性测试：向 base_url 发送请求，检查是否能连接
    2. API Key 验证（可选）：如果提供了 api_key，尝试获取模型列表验证 Key 是否有效

    返回：
    - network_ok: 网络是否连通
    - api_key_valid: API Key 是否有效（仅在提供 api_key 时返回）
    - latency_ms: 响应延迟（毫秒）
    - error: 错误信息（如果有）
    """
    try:
        base_url = _validate_model_base_url(request.base_url)
    except ValueError:
        raise HTTPException(status_code=400, detail="模型供应商 URL 无效") from None

    result = {
        "network_ok": False,
        "api_key_valid": None,
        "latency_ms": None,
        "error": None,
        "http_status": None,
    }

    # 第一步：测试网络连通性
    try:
        start_time = time.monotonic()
        status_code = await _request_provider_status(base_url, headers=None, timeout=10.0)
        latency = (time.monotonic() - start_time) * 1000

        result["network_ok"] = True
        result["latency_ms"] = round(latency, 2)
        result["http_status"] = status_code

    except ValueError:
        raise HTTPException(status_code=400, detail="模型供应商 URL 无效") from None
    except httpx.ConnectError:
        result["error"] = "连接失败：无法连接到服务器"
        return result
    except httpx.TimeoutException:
        result["error"] = "连接超时：服务器响应时间过长"
        return result
    except httpx.RequestError:
        result["error"] = "请求错误：无法连接模型供应商"
        return result
    except Exception as exc:
        logger.warning("模型供应商连通性测试失败", error_type=type(exc).__name__)
        result["error"] = "未知错误：连接测试失败"
        return result

    # 第二步：如果提供了 API Key，验证其有效性
    if request.api_key:
        try:
            headers = {
                "Authorization": f"Bearer {request.api_key}",
                "Content-Type": "application/json",
            }
            models_url = _build_provider_url(base_url, "/models")
            status_code = await _request_provider_status(models_url, headers=headers, timeout=15.0)

            if status_code == 200:
                result["api_key_valid"] = True
            elif status_code in (401, 403):
                result["api_key_valid"] = False
                result["error"] = "API Key 无效或已过期"
            else:
                # 其他状态码，可能是端点不支持，但 Key 可能是有效的
                result["api_key_valid"] = None

        except Exception as exc:
            # API Key 验证失败不影响网络连通性结果
            logger.warning("API Key 验证失败", error_type=type(exc).__name__)
            result["api_key_valid"] = None

    return result


@router.post("/test-connection-by-name")
async def test_provider_connection_by_name(
    provider_name: str = Query(..., description="提供商名称"),
    _auth: bool = Depends(require_auth),
):
    """
    通过提供商名称测试连接（从配置文件读取信息）
    """
    # 读取配置文件
    model_config_path = os.path.join(CONFIG_DIR, "model_config.toml")
    if not os.path.exists(model_config_path):
        raise HTTPException(status_code=404, detail="配置文件不存在")

    with open(model_config_path, "r", encoding="utf-8") as f:
        config = tomlkit.load(f)

    # 查找提供商
    providers = config.get("api_providers", [])
    provider = None
    for p in providers:
        if p.get("name") == provider_name:
            provider = p
            break

    if not provider:
        raise HTTPException(status_code=404, detail=f"未找到提供商: {provider_name}")

    base_url = provider.get("base_url", "")
    api_key = provider.get("api_key", "")

    if not base_url:
        raise HTTPException(status_code=400, detail="提供商配置缺少 base_url")

    # 调用测试接口
    return await test_provider_connection(
        request=TestConnectionRequest(base_url=base_url, api_key=api_key if api_key else None),
        _auth=True,
    )
