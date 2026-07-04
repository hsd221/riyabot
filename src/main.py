import asyncio
import time
from maim_message import MessageServer

from src.common.remote import TelemetryHeartBeatTask
from src.manager.async_task_manager import async_task_manager
from src.chat.utils.statistic import OnlineTimeRecordTask, StatisticOutputTask

# from src.chat.utils.token_statistics import TokenStatisticsTask
from src.chat.emoji_system.emoji_manager import get_emoji_manager
from src.chat.message_receive.chat_stream import get_chat_manager
from src.config.config import global_config
from src.chat.message_receive.bot import chat_bot
from src.common.logger import get_logger
from src.common.prompt_manager import prompt_manager
from src.common.server import get_global_server, Server
from rich.traceback import install

# from src.api.main import start_api_server

# 导入新的插件管理器
from src.plugin_system.core.plugin_manager import plugin_manager

# 导入消息API和traceback模块
from src.common.message import get_global_api
from src.bw_learner.expression_auto_check_task import ExpressionAutoCheckTask

# 插件系统现在使用统一的插件加载器

install(extra_lines=3)

logger = get_logger("main")


class MainSystem:
    def __init__(self):
        # 使用消息API替代直接的FastAPI实例
        self.app: MessageServer = get_global_api()
        self.server: Server = get_global_server()
        self.webui_server = None  # 独立的 WebUI 服务器

        # 设置独立的 WebUI 服务器
        self._setup_webui_server()

    def _setup_webui_server(self):
        """设置独立的 WebUI 服务器"""
        from src.config.config import global_config

        if not global_config.webui.enabled:
            logger.info("WebUI 已禁用")
            return

        try:
            from src.webui.webui_server import get_webui_server

            self.webui_server = get_webui_server()

        except Exception as e:
            logger.error(f"❌ 初始化 WebUI 服务器失败: {e}")

    async def initialize(self):
        """初始化系统组件"""
        logger.info(f"正在唤醒{global_config.bot.nickname}......")

        # 其他初始化任务
        await asyncio.gather(self._init_components())

        logger.info(f"""
--------------------------------
全部系统初始化完成，{global_config.bot.nickname}已成功唤醒
--------------------------------
如果想要自定义{global_config.bot.nickname}的功能,请查阅：https://docs.mai-mai.org/manual/usage/
或者遇到了问题，请访问我们的文档:https://docs.mai-mai.org/
--------------------------------
如果你想要编写或了解插件相关内容，请访问开发文档https://docs.mai-mai.org/develop/
--------------------------------
如果你需要查阅模型的消耗以及璃夜的统计数据，请访问根目录的riyabot_statistics.html文件
""")

    async def _init_components(self):
        """初始化其他组件"""
        init_start_time = time.time()

        prompt_manager.load_prompts()
        logger.info(f"已加载 {len(prompt_manager._prompts)} 个外部提示词模板")

        # 同步外部提示词到旧 PromptManager 兼容层
        from src.chat.utils.prompt_builder import init_external_prompts

        synced = init_external_prompts()
        logger.info(f"已同步 {synced} 个提示词到兼容层")

        # 添加在线时间统计任务
        await async_task_manager.add_task(OnlineTimeRecordTask())

        # 添加统计信息输出任务
        await async_task_manager.add_task(StatisticOutputTask())

        # 添加遥测心跳任务
        await async_task_manager.add_task(TelemetryHeartBeatTask())

        # 添加表达方式自动检查任务
        await async_task_manager.add_task(ExpressionAutoCheckTask())

        # 启动API服务器
        # start_api_server()
        # logger.info("API服务器启动成功")

        # 加载所有actions，包括默认的和插件的
        plugin_manager.load_all_plugins()

        # 初始化表情管理器
        get_emoji_manager().initialize()
        logger.info("表情包管理器初始化成功")

        # 初始化聊天管理器
        await get_chat_manager()._initialize()
        asyncio.create_task(get_chat_manager()._auto_save_task())

        logger.info("聊天管理器初始化成功")

        # 初始化记忆存储
        try:
            from src.memory import MemoryStore, MemoryStoreConfig

            mc = global_config.memory
            memory_config = MemoryStoreConfig(
                sqlite_path=mc.sqlite_path,
                qdrant_url=mc.qdrant_url,
                qdrant_api_key=mc.qdrant_api_key or None,
                qdrant_local_path=mc.qdrant_local_path,
                embedding_dimension=mc.embedding_dimension,
                collection_name_atoms=mc.collection_name_atoms,
                collection_name_graph=mc.collection_name_graph,
                vector_batch_size=mc.vector_batch_size,
            )
            store = MemoryStore(memory_config)
            await store.initialize()
            logger.info("记忆存储初始化完成")

            # 启动记忆遗忘定期扫描
            try:
                from src.memory.forgetting import ForgettingManager, ForgettingSweepTask

                forgetting_manager = ForgettingManager(store)
                await async_task_manager.add_task(ForgettingSweepTask(forgetting_manager))
                logger.info("记忆遗忘扫描任务已注册（3600 秒间隔）")
            except Exception as e:
                logger.warning(f"记忆遗忘扫描任务注册失败: {e}")

            # 创建写操作日志记录器（供编码管线和一致性协调任务共享）
            memory_op_logger = None
            try:
                from src.memory.write_ops import WriteOpLogger

                memory_op_logger = WriteOpLogger(
                    db_path=memory_config.sqlite_path,
                    max_entries=5000,
                )
                logger.info("记忆写操作日志记录器已初始化")
            except Exception as e:
                logger.warning(f"记忆写操作日志记录器初始化失败: {e}")

            # 启动编码管线（连接 Layer 2 → Layer 3）
            try:
                from src.memory.encoding_pipeline import EncodingPipeline, EncodingTask

                pipeline = EncodingPipeline(store, op_logger=memory_op_logger)
                await async_task_manager.add_task(EncodingTask(pipeline, interval=300))
                logger.info("编码管线已注册（300 秒间隔）")
            except Exception as e:
                logger.warning(f"编码管线注册失败: {e}")

            # 启动梦境维护任务
            try:
                from src.memory.dream_agent import DreamTask
                from src.memory.dream_weaver import DreamWeaver
                from src.memory.graph_store import GraphStore

                graph_store = GraphStore()
                dream_weaver = DreamWeaver(store=store)
                dream_task = DreamTask(
                    store=store,
                    forgetting_manager=forgetting_manager,
                    graph_store=graph_store,
                    dream_weaver=dream_weaver,
                )
                await async_task_manager.add_task(dream_task)
                dream_config = global_config.dream
                logger.info(f"梦境维护任务已注册（{dream_config.interval_minutes} 分钟间隔）")
            except Exception as e:
                logger.warning(f"梦境维护任务注册失败: {e}")

            # 启动双写一致性协调任务
            if memory_op_logger is not None:
                try:
                    from src.memory.reconciliation import ReconciliationTask

                    recon_task = ReconciliationTask(
                        store=store,
                        op_logger=memory_op_logger,
                        interval=120,
                    )
                    await async_task_manager.add_task(recon_task)
                    logger.info("双写一致性协调任务已注册（120 秒间隔）")
                except Exception as e:
                    logger.warning(f"双写一致性协调任务注册失败: {e}")
            else:
                logger.warning("写操作日志记录器不可用，跳过双写一致性协调任务")
        except Exception as e:
            logger.warning(f"记忆存储初始化失败（不影响主系统运行）: {e}")

        # await asyncio.sleep(0.5) #防止logger输出飞了

        # 将bot.py中的chat_bot.message_process消息处理函数注册到api.py的消息处理基类中
        self.app.register_message_handler(chat_bot.message_process)
        self.app.register_custom_message_handler("message_id_echo", chat_bot.echo_message_process)

        # 触发 ON_START 事件
        from src.plugin_system.core.events_manager import events_manager
        from src.plugin_system.base.component_types import EventType

        await events_manager.handle_mai_events(event_type=EventType.ON_START)
        # logger.info("已触发 ON_START 事件")
        try:
            init_time = int(1000 * (time.time() - init_start_time))
            logger.info(f"初始化完成，神经元放电{init_time}次")
        except Exception as e:
            logger.error(f"启动大脑和外部世界失败: {e}")
            raise

    async def schedule_tasks(self):
        """调度定时任务"""
        try:
            tasks = [
                get_emoji_manager().start_periodic_check_register(),
                self.app.run(),
                self.server.run(),
            ]

            # 如果 WebUI 服务器已初始化，添加到任务列表
            if self.webui_server:
                tasks.append(self.webui_server.start())

            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            logger.info("调度任务已取消")
            raise

    # async def forget_memory_task(self):
    #     """记忆遗忘任务"""
    #     while True:
    #         await asyncio.sleep(global_config.memory.forget_memory_interval)
    #         logger.info("[记忆遗忘] 开始遗忘记忆...")
    #         await self.hippocampus_manager.forget_memory(percentage=global_config.memory.memory_forget_percentage)  # type: ignore
    #         logger.info("[记忆遗忘] 记忆遗忘完成")


async def main():
    """主函数"""
    system = MainSystem()
    await asyncio.gather(
        system.initialize(),
        system.schedule_tasks(),
    )


if __name__ == "__main__":
    asyncio.run(main())
