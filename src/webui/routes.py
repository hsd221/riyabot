"""WebUI API 路由"""

from fastapi import APIRouter, HTTPException, Header, Response, Request, Cookie, Depends
from pydantic import BaseModel, Field
from typing import Optional
from src.common.logger import get_logger
from src.common.agreement import are_agreements_confirmed, confirm_agreements, get_agreement_status
from src.webui.error_utils import internal_server_error, log_exception_type
from .token_manager import get_token_manager
from .auth import clear_auth_cookie, require_same_site_request, set_auth_cookie
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
from .behavior_routes import router as behavior_router
from .model_trace_routes import router as model_trace_router
from .chat_history_import_routes import router as chat_history_import_router

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
# 注册行为学习路由
router.include_router(behavior_router)
# 注册模型请求追踪路由
router.include_router(model_trace_router)
# 注册聊天记录导入学习路由
router.include_router(chat_history_import_router)


class PasswordLoginRequest(BaseModel):
    """密码登录请求。"""

    password: str = Field(..., min_length=1, max_length=1024, description="WebUI 密码")


class TokenVerifyRequest(BaseModel):
    """旧版登录请求，保留一个迁移周期。"""

    token: str = Field(..., min_length=1, max_length=1024, description="旧版访问令牌或 WebUI 密码")


class TokenVerifyResponse(BaseModel):
    """Token 验证响应"""

    valid: bool = Field(..., description="Token 是否有效")
    message: str = Field(..., description="验证结果消息")
    is_first_setup: bool = Field(False, description="是否为首次设置")


class PasswordSetupRequest(BaseModel):
    """首次设置密码请求。"""

    password: str = Field(..., min_length=1, max_length=128, description="8-128 位密码，需包含字母和数字")


class PasswordChangeRequest(BaseModel):
    """修改密码请求。"""

    current_password: str = Field(..., min_length=1, max_length=1024, description="当前密码")
    new_password: str = Field(..., min_length=1, max_length=128, description="8-128 位密码，需包含字母和数字")


class TokenUpdateRequest(BaseModel):
    """旧版 Token 更新请求。"""

    new_token: str = Field(..., min_length=1, max_length=1024, description="旧版新访问令牌")


class TokenUpdateResponse(BaseModel):
    """密码操作响应。"""

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
        log_exception_type(logger, "读取模型配置就绪状态失败", e)
        return "模型配置文件解析失败，请检查配置格式"


def _get_session_token(maibot_session: Optional[str], authorization: Optional[str]) -> Optional[str]:
    if isinstance(maibot_session, str) and maibot_session:
        return maibot_session
    if isinstance(authorization, str) and authorization.startswith("Bearer "):
        token = authorization.removeprefix("Bearer ").strip()
        return token or None
    return None


def _require_authenticated_session(maibot_session: Optional[str], authorization: Optional[str]) -> tuple[object, str]:
    token = _get_session_token(maibot_session, authorization)
    if not token:
        raise HTTPException(status_code=401, detail="未提供有效的认证信息")
    token_manager = get_token_manager()
    if not token_manager.verify_token(token):
        raise HTTPException(status_code=401, detail="认证无效或已过期")
    return token_manager, token


def _needs_initial_setup(token_manager) -> bool:
    return token_manager.is_first_setup() or not are_agreements_confirmed() or bool(_get_model_config_readiness_error())


def _complete_password_login(password: str, request: Request, response: Response) -> TokenVerifyResponse:
    if not isinstance(password, str) or not password or len(password) > 1024:
        return TokenVerifyResponse(valid=False, message="密码错误")

    token_manager = get_token_manager()
    if not token_manager.is_password_configured():
        raise HTTPException(status_code=409, detail="WebUI 密码尚未设置")

    rate_limiter = get_rate_limiter()
    if token_manager.authenticate(password):
        session_token = token_manager.create_session()
        if not session_token:
            raise HTTPException(status_code=500, detail="无法创建登录会话")
        rate_limiter.reset_failures(request)
        set_auth_cookie(response, session_token, request)
        response.headers["Cache-Control"] = "no-store"
        return TokenVerifyResponse(
            valid=True,
            message="密码验证成功",
            is_first_setup=_needs_initial_setup(token_manager),
        )

    blocked, remaining = rate_limiter.record_failed_attempt(
        request,
        max_failures=5,
        window_seconds=300,
        block_duration=600,
    )
    if blocked:
        raise HTTPException(
            status_code=429,
            detail="认证失败次数过多，请在 10 分钟后重试",
            headers={"Retry-After": "600"},
        )
    message = "密码错误"
    if remaining <= 2:
        message += f"（剩余 {remaining} 次尝试机会）"
    return TokenVerifyResponse(valid=False, message=message)


@router.post("/auth/setup", response_model=TokenUpdateResponse)
async def setup_password(
    request_body: PasswordSetupRequest,
    request: Request,
    response: Response,
    _rate_limit: None = Depends(check_auth_rate_limit),
):
    """首次运行时设置密码；该操作只能成功一次。"""
    require_same_site_request(request)
    token_manager = get_token_manager()
    valid, message = token_manager.validate_password(request_body.password)
    if not valid:
        raise HTTPException(status_code=422, detail=message)

    success, message = token_manager.set_initial_password(request_body.password)
    if not success:
        status_code = 409 if token_manager.is_password_configured() else 422
        raise HTTPException(status_code=status_code, detail=message)

    session_token = token_manager.create_session()
    if not session_token:
        raise HTTPException(status_code=500, detail="无法创建登录会话")
    get_rate_limiter().reset_failures(request)
    set_auth_cookie(response, session_token, request)
    response.headers["Cache-Control"] = "no-store"
    return TokenUpdateResponse(success=True, message="密码设置成功")


@router.post("/auth/login", response_model=TokenVerifyResponse)
async def login(
    request_body: PasswordLoginRequest,
    request: Request,
    response: Response,
    _rate_limit: None = Depends(check_auth_rate_limit),
):
    """使用密码登录并签发 HttpOnly 会话 Cookie。"""
    require_same_site_request(request)
    try:
        return _complete_password_login(request_body.password, request, response)
    except HTTPException:
        raise
    except Exception as e:
        log_exception_type(logger, "WebUI 密码验证失败", e, event_code="webui.auth.login_failed")
        raise HTTPException(status_code=500, detail="登录失败") from None


@router.post("/auth/verify", response_model=TokenVerifyResponse, deprecated=True)
async def verify_token(
    request_body: TokenVerifyRequest,
    request: Request,
    response: Response,
    _rate_limit: None = Depends(check_auth_rate_limit),
):
    """兼容旧前端的登录入口。"""
    require_same_site_request(request)
    try:
        return _complete_password_login(request_body.token, request, response)
    except HTTPException:
        raise
    except Exception as e:
        log_exception_type(logger, "旧版 WebUI 登录失败", e, event_code="webui.auth.legacy_login_failed")
        raise HTTPException(status_code=500, detail="登录失败") from None


@router.post("/auth/logout")
async def logout(response: Response, request: Request = None):
    """登出并清除认证 Cookie。"""
    if request is not None:
        require_same_site_request(request)
        clear_auth_cookie(response, request)
    else:
        # 兼容内部脚本直接传入 Response 的旧调用方式；浏览器路由始终会注入 Request。
        clear_auth_cookie(response)
    response.headers["Cache-Control"] = "no-store"
    return {"success": True, "message": "已成功登出"}


@router.get("/auth/check")
async def check_auth_status(
    request: Request,
    maibot_session: Optional[str] = Cookie(None),
    authorization: Optional[str] = Header(None),
):
    """返回登录状态以及是否需要先设置密码。"""
    try:
        token_manager = get_token_manager()
        password_configured = token_manager.is_password_configured()
        token = _get_session_token(maibot_session, authorization)
        if not token:
            return {"authenticated": False, "password_configured": password_configured}
        return {
            "authenticated": token_manager.verify_token(token),
            "password_configured": password_configured,
        }
    except Exception as e:
        log_exception_type(logger, "WebUI 认证状态检查失败", e, event_code="webui.auth.status_failed")
        return {"authenticated": False, "password_configured": True}


@router.post("/auth/password", response_model=TokenUpdateResponse)
async def change_password(
    request_body: PasswordChangeRequest,
    response: Response,
    request: Request,
    maibot_session: Optional[str] = Cookie(None),
    authorization: Optional[str] = Header(None),
):
    """验证当前密码后修改密码，并撤销已有会话。"""
    require_same_site_request(request)
    token_manager, _ = _require_authenticated_session(maibot_session, authorization)
    valid, message = token_manager.validate_password(request_body.new_password)
    if not valid:
        raise HTTPException(status_code=422, detail=message)
    success, message = token_manager.update_password(request_body.current_password, request_body.new_password)
    if not success:
        raise HTTPException(status_code=400, detail=message)
    clear_auth_cookie(response, request)
    response.headers["Cache-Control"] = "no-store"
    return TokenUpdateResponse(success=True, message=message)


@router.post("/auth/update", response_model=TokenUpdateResponse, deprecated=True)
async def update_token(
    request_body: TokenUpdateRequest,
    response: Response,
    request: Request,
    maibot_session: Optional[str] = Cookie(None),
    authorization: Optional[str] = Header(None),
):
    """旧版无当前密码的修改接口已停用。"""
    require_same_site_request(request)
    _require_authenticated_session(maibot_session, authorization)
    raise HTTPException(status_code=410, detail="旧版 Token 接口已停用，请使用密码修改接口")


@router.post("/auth/regenerate", response_model=TokenRegenerateResponse, deprecated=True)
async def regenerate_token(
    response: Response,
    request: Request,
    maibot_session: Optional[str] = Cookie(None),
    authorization: Optional[str] = Header(None),
):
    """旧版明文令牌生成接口已停用。"""
    require_same_site_request(request)
    _require_authenticated_session(maibot_session, authorization)
    raise HTTPException(status_code=410, detail="不再生成访问令牌，请使用自定义密码")


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
        is_first = (
            token_manager.is_first_setup() or agreement_required or bool(created_config_files) or model_config_required
        )

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
        raise internal_server_error(logger, "获取配置状态失败", e) from None


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
        raise internal_server_error(logger, "获取协议状态失败", e) from None


@router.post("/setup/agreement/confirm", response_model=AgreementConfirmResponse)
async def confirm_setup_agreement(
    request_body: AgreementConfirmRequest,
    request: Request,
    maibot_session: Optional[str] = Cookie(None),
    authorization: Optional[str] = Header(None),
):
    """确认当前 EULA 和隐私条款。"""
    try:
        require_same_site_request(request)
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
    except ValueError:
        raise HTTPException(status_code=409, detail="协议内容已更新，请刷新页面后重新确认") from None
    except HTTPException:
        raise
    except Exception as e:
        raise internal_server_error(logger, "确认协议失败", e) from None


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
        require_same_site_request(request)
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
        raise internal_server_error(logger, "标记配置完成失败", e) from None


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
        require_same_site_request(request)
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
        raise internal_server_error(logger, "重置配置状态失败", e) from None
