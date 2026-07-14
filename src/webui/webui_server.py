"""独立的 WebUI 服务器 - 运行在 0.0.0.0:8001"""

import asyncio
import mimetypes
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from uvicorn import Config, Server as UvicornServer
from src.common.logger import get_logger, hash_id, redact_secret

logger = get_logger("webui_server")


class WebUIServer:
    """独立的 WebUI 服务器"""

    def __init__(self, host: str = "0.0.0.0", port: int = 8001):
        self.host = host
        self.port = port
        self.app = FastAPI(title="RiyaBot WebUI")
        self._server = None

        # 配置防爬虫中间件（需要在CORS之前注册）
        self._setup_anti_crawler()

        # 配置 CORS（支持开发环境跨域请求）
        self._setup_cors()

        # 显示 Access Token
        self._show_access_token()

        # 重要：先注册 API 路由，再设置静态文件
        self._register_api_routes()
        self._setup_static_files()

        # 注册robots.txt路由
        self._setup_robots_txt()

    def _setup_cors(self):
        """配置 CORS 中间件"""
        # 开发环境需要允许前端开发服务器的跨域请求
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=[
                "http://localhost:5173",  # Vite 开发服务器
                "http://127.0.0.1:5173",
                "http://localhost:7999",  # 前端开发服务器备用端口
                "http://127.0.0.1:7999",
                "http://localhost:8001",  # 生产环境
                "http://127.0.0.1:8001",
            ],
            allow_credentials=True,  # 允许携带 Cookie
            allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],  # 明确指定允许的方法
            allow_headers=[
                "Content-Type",
                "Authorization",
                "Accept",
                "Origin",
                "X-Requested-With",
            ],  # 明确指定允许的头
            expose_headers=["Content-Length", "Content-Type"],  # 允许前端读取的响应头
        )
        logger.debug("CORS 中间件已配置", event_code="webui.cors.configured")

    def _show_access_token(self):
        """显示 WebUI Access Token"""
        try:
            from src.webui.token_manager import get_token_manager

            token_manager = get_token_manager()
            current_token = token_manager.get_token()
            logger.info(
                "WebUI Access Token 已加载",
                event_code="webui.access_token.loaded",
                token_preview=redact_secret(current_token),
                token_hash=hash_id(current_token),
            )
        except Exception:
            logger.exception("WebUI Access Token 获取失败", event_code="webui.access_token.load_failed")

    def _setup_static_files(self):
        """设置静态文件服务"""
        # 确保正确的 MIME 类型映射
        mimetypes.init()
        mimetypes.add_type("application/javascript", ".js")
        mimetypes.add_type("application/javascript", ".mjs")
        mimetypes.add_type("text/css", ".css")
        mimetypes.add_type("application/json", ".json")

        base_dir = Path(__file__).parent.parent.parent
        static_path = base_dir / "webui" / "dist"

        if not static_path.exists():
            logger.warning(
                "WebUI 静态文件目录不存在",
                event_code="webui.static.missing_dist",
                path=str(static_path),
                remediation="cd webui && bun run build",
            )
            return

        if not (static_path / "index.html").exists():
            logger.warning(
                "WebUI 静态入口文件不存在",
                event_code="webui.static.missing_index",
                path=str(static_path / "index.html"),
                remediation="cd webui && bun run build",
            )
            return

        static_root = static_path.resolve()

        # 处理 SPA 路由 - 注意：这个路由优先级最低
        @self.app.get("/{full_path:path}", include_in_schema=False)
        async def serve_spa(full_path: str):
            """服务单页应用 - 只处理非 API 请求"""
            # 如果是根路径，直接返回 index.html
            if not full_path or full_path == "/":
                response = FileResponse(static_path / "index.html", media_type="text/html")
                response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
                return response

            # 检查是否是静态文件
            try:
                file_path = (static_path / full_path).resolve()
                is_safe_static_file = file_path.is_relative_to(static_root) and file_path.is_file()
            except (OSError, RuntimeError):
                is_safe_static_file = False

            if is_safe_static_file:
                # 自动检测 MIME 类型
                media_type = mimetypes.guess_type(str(file_path))[0]
                response = FileResponse(file_path, media_type=media_type)
                # HTML 文件添加防索引头
                if str(file_path).endswith(".html"):
                    response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
                return response

            # 其他路径返回 index.html（SPA 路由）
            response = FileResponse(static_path / "index.html", media_type="text/html")
            response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
            return response

        logger.info("WebUI 静态文件服务已配置", event_code="webui.static.configured", path=str(static_path))

    def _setup_anti_crawler(self):
        """配置防爬虫中间件"""
        try:
            from src.webui.anti_crawler import AntiCrawlerMiddleware
            from src.config.config import global_config

            # 从配置读取防爬虫模式
            anti_crawler_mode = global_config.webui.anti_crawler_mode

            # 注意：中间件按注册顺序反向执行，所以先注册的中间件后执行
            # 我们需要在CORS之前注册，这样防爬虫检查会在CORS之前执行
            self.app.add_middleware(AntiCrawlerMiddleware, mode=anti_crawler_mode)

            mode_descriptions = {"false": "已禁用", "strict": "严格模式", "loose": "宽松模式", "basic": "基础模式"}
            mode_desc = mode_descriptions.get(anti_crawler_mode, "基础模式")
            logger.info(
                "防爬虫中间件已配置",
                event_code="webui.anti_crawler.configured",
                mode=anti_crawler_mode,
                mode_description=mode_desc,
            )
        except Exception:
            logger.exception("防爬虫中间件配置失败", event_code="webui.anti_crawler.configure_failed")

    def _setup_robots_txt(self):
        """设置robots.txt路由"""
        try:
            from src.webui.anti_crawler import create_robots_txt_response

            @self.app.get("/robots.txt", include_in_schema=False)
            async def robots_txt():
                """返回robots.txt，禁止所有爬虫"""
                return create_robots_txt_response()

            logger.debug("robots.txt 路由已注册", event_code="webui.robots.registered")
        except Exception:
            logger.exception("robots.txt 路由注册失败", event_code="webui.robots.register_failed")

    def _register_api_routes(self):
        """注册所有 WebUI API 路由"""
        try:
            # 导入所有 WebUI 路由
            from src.webui.routes import router as webui_router
            from src.webui.logs_ws import router as logs_router
            from src.webui.knowledge_routes import router as knowledge_router

            # 导入本地聊天室路由
            from src.webui.chat_routes import router as chat_router

            # 导入规划器监控路由
            from src.webui.api.planner import router as planner_router

            # 导入回复器监控路由
            from src.webui.api.replier import router as replier_router

            # 注册路由
            self.app.include_router(webui_router)
            self.app.include_router(logs_router)
            self.app.include_router(knowledge_router)
            self.app.include_router(chat_router)
            self.app.include_router(planner_router)
            self.app.include_router(replier_router)

            logger.info("WebUI API 路由已注册", event_code="webui.routes.registered")
        except Exception:
            logger.exception("WebUI API 路由注册失败", event_code="webui.routes.register_failed")

    async def start(self):
        """启动服务器"""
        # 预先检查端口是否可用
        if not self._check_port_available():
            logger.error(
                "WebUI 服务器端口不可用",
                event_code="webui.server.port_unavailable",
                host=self.host,
                port=self.port,
                remediation="检查端口占用或通过 WEBUI_PORT 修改端口",
            )
            raise OSError(f"端口 {self.port} 已被占用，无法启动 WebUI 服务器")

        config = Config(
            app=self.app,
            host=self.host,
            port=self.port,
            log_config=None,
            access_log=False,
        )
        self._server = UvicornServer(config=config)

        logger.info("WebUI 服务器启动中", event_code="webui.server.starting", host=self.host, port=self.port)

        # 根据地址类型显示正确的访问地址
        if ":" in self.host:
            # IPv6 地址需要用方括号包裹
            logger.info("WebUI 访问地址", event_code="webui.server.address", url=f"http://[{self.host}]:{self.port}")
            if self.host == "::":
                logger.info(
                    "WebUI 本机访问地址", event_code="webui.server.local_address", url=f"http://[::1]:{self.port}"
                )
                logger.info(
                    "WebUI 本机访问地址",
                    event_code="webui.server.local_address",
                    url=f"http://127.0.0.1:{self.port}",
                )
            elif self.host == "::1":
                logger.info("WebUI 仅监听 IPv6 本机地址", event_code="webui.server.ipv6_local_only")
        else:
            # IPv4 地址
            logger.info("WebUI 访问地址", event_code="webui.server.address", url=f"http://{self.host}:{self.port}")
            if self.host == "0.0.0.0":
                logger.info(
                    "WebUI 本机访问地址",
                    event_code="webui.server.local_address",
                    url=f"http://localhost:{self.port}",
                    alternate_url=f"http://127.0.0.1:{self.port}",
                )

        try:
            await self._server.serve()
        except OSError as e:
            # 处理端口绑定相关的错误
            if "address already in use" in str(e).lower() or e.errno in (98, 10048):  # 98: Linux, 10048: Windows
                logger.error(
                    "WebUI 服务器端口绑定失败",
                    event_code="webui.server.bind_failed",
                    host=self.host,
                    port=self.port,
                    remediation="检查端口占用或通过 WEBUI_PORT 修改端口",
                )
            else:
                logger.error("WebUI 服务器网络错误", event_code="webui.server.network_error", error=str(e))
            raise
        except Exception:
            logger.exception("WebUI 服务器运行失败", event_code="webui.server.run_failed")
            raise

    def _check_port_available(self) -> bool:
        """检查端口是否可用（支持 IPv4 和 IPv6）"""
        import socket

        # 判断使用 IPv4 还是 IPv6
        if ":" in self.host:
            # IPv6 地址
            family = socket.AF_INET6
            test_host = self.host if self.host != "::" else "::1"
        else:
            # IPv4 地址
            family = socket.AF_INET
            test_host = self.host if self.host != "0.0.0.0" else "127.0.0.1"

        try:
            with socket.socket(family, socket.SOCK_STREAM) as s:
                s.settimeout(1)
                # 与 uvicorn 的实际绑定行为保持一致，避免刚关闭服务后的 TIME_WAIT 被误判为端口占用。
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                # 尝试绑定端口
                s.bind((test_host, self.port))
                return True
        except OSError:
            return False

    async def shutdown(self):
        """关闭服务器"""
        if self._server:
            logger.info("WebUI 服务器开始关闭", event_code="webui.server.shutdown_started")
            self._server.should_exit = True
            try:
                await asyncio.wait_for(self._server.shutdown(), timeout=3.0)
                logger.info("WebUI 服务器已关闭", event_code="webui.server.shutdown_completed")
            except asyncio.TimeoutError:
                logger.warning("WebUI 服务器关闭超时", event_code="webui.server.shutdown_timeout", timeout_seconds=3.0)
            except Exception:
                logger.exception("WebUI 服务器关闭失败", event_code="webui.server.shutdown_failed")
            finally:
                self._server = None


# 全局 WebUI 服务器实例
_webui_server = None


def get_webui_server() -> WebUIServer:
    """获取全局 WebUI 服务器实例"""
    global _webui_server
    if _webui_server is None:
        # 从环境变量读取
        import os

        host = os.getenv("WEBUI_HOST", "127.0.0.1")
        port = int(os.getenv("WEBUI_PORT", "8001"))
        _webui_server = WebUIServer(host=host, port=port)
    return _webui_server
