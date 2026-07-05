"""WebUI API 路由"""

from fastapi import APIRouter, HTTPException, Header, Response, Request, Cookie, Depends
from pydantic import BaseModel, Field
from typing import Optional
from src.common.logger import get_logger
from src.common.agreement import are_agreements_confirmed, confirm_agreements, get_agreement_status
from .token_manager import get_token_manager
from .auth import set_auth_cookie, clear_auth_cookie
from .rate_limiter import get_rate_limiter, check_auth_rate_limit
from .config_routes import router as config_router
from .statistics_routes import router as statistics_router
from .person_routes import router as person_router
from .expression_routes import router as expression_router
from .jargon_routes import router as jargon_router
from .emoji_routes import router as emoji_router
from .plugin_routes import router as plugin_router
from .plugin_progress_ws import get_progress_router
from .routers.system import router as system_router
from .model_routes import router as model_router
from .ws_auth import router as ws_auth_router
from .annual_report_routes import router as annual_report_router
from .memory_routes import router as memory_router

logger = get_logger("webui.api")

# 创建路由器
router = APIRouter(prefix="/api/webui", tags=["WebUI"])

# 注册配置管理路由
router.include_router(config_router)
# 注册统计数据路由
router.include_router(statistics_router)
# 注册人物信息管理路由
router.include_router(person_router)
# 注册表达方式管理路由
router.include_router(expression_router)
# 注册黑话管理路由
router.include_router(jargon_router)
# 注册表情包管理路由
router.include_router(emoji_router)
# 注册插件管理路由
router.include_router(plugin_router)
# 注册插件进度 WebSocket 路由
router.include_router(get_progress_router())
# 注册系统控制路由
router.include_router(system_router)
# 注册模型列表获取路由
router.include_router(model_router)
# 注册 WebSocket 认证路由
router.include_router(ws_auth_router)
# 注册年度报告路由
router.include_router(annual_report_router)
# 注册记忆系统路由
router.include_router(memory_router)


class TokenVerifyRequest(BaseModel):
    """Token 验证请求"""

    token: str = Field(..., description="访问令牌")


class TokenVerifyResponse(BaseModel):
    """Token 验证响应"""

    valid: bool = Field(..., description="Token 是否有效")
    message: str = Field(..., description="验证结果消息")
    is_first_setup: bool = Field(False, description="是否为首次设置")


class TokenUpdateRequest(BaseModel):
    """Token 更新请求"""

    new_token: str = Field(..., description="新的访问令牌", min_length=10)


class TokenUpdateResponse(BaseModel):
    """Token 更新响应"""

    success: bool = Field(..., description="是否更新成功")
    message: str = Field(..., description="更新结果消息")


class TokenRegenerateResponse(BaseModel):
    """Token 重新生成响应"""

    success: bool = Field(..., description="是否生成成功")
    token: str = Field(..., description="新生成的令牌")
    message: str = Field(..., description="生成结果消息")


class FirstSetupStatusResponse(BaseModel):
    """首次配置状态响应"""

    is_first_setup: bool = Field(..., description="是否为首次配置")
    message: str = Field(..., description="状态消息")
    agreement_required: bool = Field(False, description="是否需要确认 EULA 或隐私条款")
    created_config_files: list[str] = Field(default_factory=list, description="本次启动新创建的配置文件")
    model_config_required: bool = Field(False, description="是否需要补全模型配置")
    model_config_message: str = Field("", description="模型配置待补全原因")


class AgreementDocumentResponse(BaseModel):
    """协议文件状态响应"""

    title: str = Field(..., description="协议标题")
    file_name: str = Field(..., description="协议文件名")
    hash: str = Field(..., description="当前协议内容哈希")
    confirmed: bool = Field(..., description="是否已确认")
    environment_confirmed: bool = Field(False, description="是否由环境变量确认")
    content: str = Field("", description="协议内容")


class AgreementStatusResponse(BaseModel):
    """协议确认状态响应"""

    agreement_required: bool = Field(..., description="是否需要确认协议")
    eula: AgreementDocumentResponse = Field(..., description="EULA 状态")
    privacy: AgreementDocumentResponse = Field(..., description="隐私条款状态")


class AgreementConfirmRequest(BaseModel):
    """协议确认请求"""

    eula_hash: str = Field(..., description="用户确认时看到的 EULA 哈希")
    privacy_hash: str = Field(..., description="用户确认时看到的隐私条款哈希")


class AgreementConfirmResponse(BaseModel):
    """协议确认响应"""

    success: bool = Field(..., description="是否成功")
    message: str = Field(..., description="结果消息")
    agreement: AgreementStatusResponse = Field(..., description="更新后的协议状态")


class CompleteSetupResponse(BaseModel):
    """完成配置响应"""

    success: bool = Field(..., description="是否成功")
    message: str = Field(..., description="结果消息")


class ResetSetupResponse(BaseModel):
    """重置配置响应"""

    success: bool = Field(..., description="是否成功")
    message: str = Field(..., description="结果消息")


@router.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "healthy", "service": "RiyaBot WebUI"}


def _build_agreement_status_response(include_content: bool = True) -> AgreementStatusResponse:
    """构造协议状态响应。"""
    status = get_agreement_status(include_content=include_content)

    def to_response(key: str) -> AgreementDocumentResponse:
        document = status[key]
        return AgreementDocumentResponse(
            title=document.title,
            file_name=document.file_name,
            hash=document.hash,
            confirmed=document.confirmed,
            environment_confirmed=document.environment_confirmed,
            content=document.content,
        )

    return AgreementStatusResponse(
        agreement_required=not all(document.confirmed for document in status.values()),
        eula=to_response("eula"),
        privacy=to_response("privacy"),
    )


def _get_model_config_readiness_error() -> str:
    """读取磁盘上的模型配置并返回未完成原因。"""
    from src.config.config import CONFIG_DIR, api_ada_load_config
    import os

    try:
        current_model_config = api_ada_load_config(os.path.join(CONFIG_DIR, "model_config.toml"))
        return current_model_config.get_runtime_readiness_error() or ""
    except Exception as e:
        return f"模型配置文件解析失败: {e}"


@router.post("/auth/verify", response_model=TokenVerifyResponse)
async def verify_token(
    request_body: TokenVerifyRequest,
    request: Request,
    response: Response,
    _rate_limit: None = Depends(check_auth_rate_limit),
):
    """
    验证访问令牌，验证成功后设置 HttpOnly Cookie

    Args:
        request_body: 包含 token 的验证请求
        request: FastAPI Request 对象（用于获取客户端 IP）
        response: FastAPI Response 对象

    Returns:
        验证结果（包含首次配置状态）
    """
    try:
        token_manager = get_token_manager()
        rate_limiter = get_rate_limiter()

        is_valid = token_manager.verify_token(request_body.token)

        if is_valid:
            # 认证成功，重置失败计数
            rate_limiter.reset_failures(request)
            # 设置 HttpOnly Cookie（传入 request 以检测协议）
            set_auth_cookie(response, request_body.token, request)
            # 同时返回首次配置状态，避免额外请求
            is_first_setup = (
                token_manager.is_first_setup()
                or not are_agreements_confirmed()
                or bool(_get_model_config_readiness_error())
            )
            return TokenVerifyResponse(valid=True, message="Token 验证成功", is_first_setup=is_first_setup)
        else:
            # 记录失败尝试
            blocked, remaining = rate_limiter.record_failed_attempt(
                request,
                max_failures=5,  # 5 次失败
                window_seconds=300,  # 5 分钟窗口
                block_duration=600,  # 封禁 10 分钟
            )

            if blocked:
                raise HTTPException(status_code=429, detail="认证失败次数过多，您的 IP 已被临时封禁 10 分钟")

            message = "Token 无效或已过期"
            if remaining <= 2:
                message += f"（剩余 {remaining} 次尝试机会）"

            return TokenVerifyResponse(valid=False, message=message)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Token 验证失败: {e}")
        raise HTTPException(status_code=500, detail="Token 验证失败") from e


@router.post("/auth/logout")
async def logout(response: Response):
    """
    登出并清除认证 Cookie

    Args:
        response: FastAPI Response 对象

    Returns:
        登出结果
    """
    clear_auth_cookie(response)
    return {"success": True, "message": "已成功登出"}


@router.get("/auth/check")
async def check_auth_status(
    request: Request,
    maibot_session: Optional[str] = Cookie(None),
    authorization: Optional[str] = Header(None),
):
    """
    检查当前认证状态（用于前端判断是否已登录）

    Returns:
        认证状态
    """
    try:
        token = None

        # 记录请求信息用于调试
        logger.debug(
            f"检查认证状态 - Cookie: {maibot_session[:20] if maibot_session else 'None'}..., Authorization: {'Present' if authorization else 'None'}"
        )

        # 优先从 Cookie 获取
        if maibot_session:
            token = maibot_session
            logger.debug("使用 Cookie 中的 token")
        # 其次从 Header 获取
        elif authorization and authorization.startswith("Bearer "):
            token = authorization.replace("Bearer ", "")
            logger.debug("使用 Header 中的 token")

        if not token:
            logger.debug("未找到 token，返回未认证")
            return {"authenticated": False}

        token_manager = get_token_manager()
        is_valid = token_manager.verify_token(token)
        logger.debug(f"Token 验证结果: {is_valid}")

        if is_valid:
            return {"authenticated": True}
        else:
            return {"authenticated": False}
    except Exception as e:
        logger.error(f"认证检查失败: {e}", exc_info=True)
        return {"authenticated": False}


@router.post("/auth/update", response_model=TokenUpdateResponse)
async def update_token(
    request: TokenUpdateRequest,
    response: Response,
    req: Request,
    maibot_session: Optional[str] = Cookie(None),
    authorization: Optional[str] = Header(None),
):
    """
    更新访问令牌（需要当前有效的 token）

    Args:
        request: 包含新 token 的更新请求
        response: FastAPI Response 对象
        maibot_session: Cookie 中的 token
        authorization: Authorization header (Bearer token)

    Returns:
        更新结果
    """
    try:
        # 验证当前 token（优先 Cookie，其次 Header）
        current_token = None
        if maibot_session:
            current_token = maibot_session
        elif authorization and authorization.startswith("Bearer "):
            current_token = authorization.replace("Bearer ", "")

        if not current_token:
            raise HTTPException(status_code=401, detail="未提供有效的认证信息")

        token_manager = get_token_manager()

        if not token_manager.verify_token(current_token):
            raise HTTPException(status_code=401, detail="当前 Token 无效")

        # 更新 token
        success, message = token_manager.update_token(request.new_token)

        # 如果更新成功，清除 Cookie，要求用户重新登录
        if success:
            clear_auth_cookie(response)

        return TokenUpdateResponse(success=success, message=message)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Token 更新失败: {e}")
        raise HTTPException(status_code=500, detail="Token 更新失败") from e


@router.post("/auth/regenerate", response_model=TokenRegenerateResponse)
async def regenerate_token(
    response: Response,
    request: Request,
    maibot_session: Optional[str] = Cookie(None),
    authorization: Optional[str] = Header(None),
):
    """
    重新生成访问令牌（需要当前有效的 token）

    Args:
        response: FastAPI Response 对象
        maibot_session: Cookie 中的 token
        authorization: Authorization header (Bearer token)

    Returns:
        新生成的 token
    """
    try:
        # 验证当前 token（优先 Cookie，其次 Header）
        current_token = None
        if maibot_session:
            current_token = maibot_session
        elif authorization and authorization.startswith("Bearer "):
            current_token = authorization.replace("Bearer ", "")

        if not current_token:
            raise HTTPException(status_code=401, detail="未提供有效的认证信息")

        token_manager = get_token_manager()

        if not token_manager.verify_token(current_token):
            raise HTTPException(status_code=401, detail="当前 Token 无效")

        # 重新生成 token
        new_token = token_manager.regenerate_token()

        # 清除 Cookie，要求用户重新登录
        clear_auth_cookie(response)

        return TokenRegenerateResponse(success=True, token=new_token, message="Token 已重新生成")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Token 重新生成失败: {e}")
        raise HTTPException(status_code=500, detail="Token 重新生成失败") from e


@router.get("/setup/status", response_model=FirstSetupStatusResponse)
async def get_setup_status(
    request: Request,
    maibot_session: Optional[str] = Cookie(None),
    authorization: Optional[str] = Header(None),
):
    """
    获取首次配置状态

    Args:
        maibot_session: Cookie 中的 token
        authorization: Authorization header (Bearer token)

    Returns:
        首次配置状态
    """
    try:
        # 验证 token（优先 Cookie，其次 Header）
        current_token = None
        if maibot_session:
            current_token = maibot_session
        elif authorization and authorization.startswith("Bearer "):
            current_token = authorization.replace("Bearer ", "")

        if not current_token:
            raise HTTPException(status_code=401, detail="未提供有效的认证信息")

        token_manager = get_token_manager()

        if not token_manager.verify_token(current_token):
            raise HTTPException(status_code=401, detail="Token 无效")

        # 检查是否为首次配置
        from src.config.config import get_created_config_files

        agreement_required = not are_agreements_confirmed()
        created_config_files = get_created_config_files()
        model_config_message = _get_model_config_readiness_error()
        model_config_required = bool(model_config_message)
        is_first = token_manager.is_first_setup() or agreement_required or bool(created_config_files) or model_config_required

        return FirstSetupStatusResponse(
            is_first_setup=is_first,
            message="首次配置" if is_first else "已完成配置",
            agreement_required=agreement_required,
            created_config_files=created_config_files,
            model_config_required=model_config_required,
            model_config_message=model_config_message,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取配置状态失败: {e}")
        raise HTTPException(status_code=500, detail="获取配置状态失败") from e


@router.get("/setup/agreement", response_model=AgreementStatusResponse)
async def get_setup_agreement(
    request: Request,
    maibot_session: Optional[str] = Cookie(None),
    authorization: Optional[str] = Header(None),
):
    """获取 EULA 和隐私条款内容及确认状态。"""
    try:
        current_token = None
        if maibot_session:
            current_token = maibot_session
        elif authorization and authorization.startswith("Bearer "):
            current_token = authorization.replace("Bearer ", "")

        if not current_token:
            raise HTTPException(status_code=401, detail="未提供有效的认证信息")

        token_manager = get_token_manager()
        if not token_manager.verify_token(current_token):
            raise HTTPException(status_code=401, detail="Token 无效")

        return _build_agreement_status_response(include_content=True)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取协议状态失败: {e}")
        raise HTTPException(status_code=500, detail="获取协议状态失败") from e


@router.post("/setup/agreement/confirm", response_model=AgreementConfirmResponse)
async def confirm_setup_agreement(
    request_body: AgreementConfirmRequest,
    request: Request,
    maibot_session: Optional[str] = Cookie(None),
    authorization: Optional[str] = Header(None),
):
    """确认当前 EULA 和隐私条款。"""
    try:
        current_token = None
        if maibot_session:
            current_token = maibot_session
        elif authorization and authorization.startswith("Bearer "):
            current_token = authorization.replace("Bearer ", "")

        if not current_token:
            raise HTTPException(status_code=401, detail="未提供有效的认证信息")

        token_manager = get_token_manager()
        if not token_manager.verify_token(current_token):
            raise HTTPException(status_code=401, detail="Token 无效")

        confirm_agreements(request_body.eula_hash, request_body.privacy_hash)
        return AgreementConfirmResponse(
            success=True,
            message="协议已确认",
            agreement=_build_agreement_status_response(include_content=True),
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"确认协议失败: {e}")
        raise HTTPException(status_code=500, detail="确认协议失败") from e


@router.post("/setup/complete", response_model=CompleteSetupResponse)
async def complete_setup(
    request: Request,
    maibot_session: Optional[str] = Cookie(None),
    authorization: Optional[str] = Header(None),
):
    """
    标记首次配置完成

    Args:
        maibot_session: Cookie 中的 token
        authorization: Authorization header (Bearer token)

    Returns:
        完成结果
    """
    try:
        # 验证 token（优先 Cookie，其次 Header）
        current_token = None
        if maibot_session:
            current_token = maibot_session
        elif authorization and authorization.startswith("Bearer "):
            current_token = authorization.replace("Bearer ", "")

        if not current_token:
            raise HTTPException(status_code=401, detail="未提供有效的认证信息")

        token_manager = get_token_manager()

        if not token_manager.verify_token(current_token):
            raise HTTPException(status_code=401, detail="Token 无效")

        if not are_agreements_confirmed():
            raise HTTPException(status_code=400, detail="请先阅读并同意 EULA 和隐私条款")

        model_config_message = _get_model_config_readiness_error()

        if model_config_message:
            raise HTTPException(status_code=400, detail=model_config_message)

        # 标记配置完成
        success = token_manager.mark_setup_completed()

        return CompleteSetupResponse(success=success, message="配置已完成" if success else "标记失败")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"标记配置完成失败: {e}")
        raise HTTPException(status_code=500, detail="标记配置完成失败") from e


@router.post("/setup/reset", response_model=ResetSetupResponse)
async def reset_setup(
    request: Request,
    maibot_session: Optional[str] = Cookie(None),
    authorization: Optional[str] = Header(None),
):
    """
    重置首次配置状态，允许重新进入配置向导

    Args:
        maibot_session: Cookie 中的 token
        authorization: Authorization header (Bearer token)

    Returns:
        重置结果
    """
    try:
        # 验证 token（优先 Cookie，其次 Header）
        current_token = None
        if maibot_session:
            current_token = maibot_session
        elif authorization and authorization.startswith("Bearer "):
            current_token = authorization.replace("Bearer ", "")

        if not current_token:
            raise HTTPException(status_code=401, detail="未提供有效的认证信息")

        token_manager = get_token_manager()

        if not token_manager.verify_token(current_token):
            raise HTTPException(status_code=401, detail="Token 无效")

        # 重置配置状态
        success = token_manager.reset_setup_status()

        return ResetSetupResponse(success=success, message="配置状态已重置" if success else "重置失败")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"重置配置状态失败: {e}")
        raise HTTPException(status_code=500, detail="重置配置状态失败") from e
