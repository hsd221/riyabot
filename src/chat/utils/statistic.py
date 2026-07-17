import asyncio
import concurrent.futures

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, Tuple, List

from src.common.logger import get_logger
from src.common.database.database import db
from src.common.database.database_model import OnlineTime, LLMUsage, Messages, ActionRecords
from src.manager.async_task_manager import AsyncTask
from src.manager.local_store_manager import local_storage

logger = get_logger("maibot_statistic")

# 统计数据的键
TOTAL_REQ_CNT = "total_requests"
TOTAL_COST = "total_cost"
REQ_CNT_BY_TYPE = "requests_by_type"
REQ_CNT_BY_USER = "requests_by_user"
REQ_CNT_BY_MODEL = "requests_by_model"
REQ_CNT_BY_MODULE = "requests_by_module"
IN_TOK_BY_TYPE = "in_tokens_by_type"
IN_TOK_BY_USER = "in_tokens_by_user"
IN_TOK_BY_MODEL = "in_tokens_by_model"
IN_TOK_BY_MODULE = "in_tokens_by_module"
OUT_TOK_BY_TYPE = "out_tokens_by_type"
OUT_TOK_BY_USER = "out_tokens_by_user"
OUT_TOK_BY_MODEL = "out_tokens_by_model"
OUT_TOK_BY_MODULE = "out_tokens_by_module"
TOTAL_TOK_BY_TYPE = "tokens_by_type"
TOTAL_TOK_BY_USER = "tokens_by_user"
TOTAL_TOK_BY_MODEL = "tokens_by_model"
TOTAL_TOK_BY_MODULE = "tokens_by_module"
COST_BY_TYPE = "costs_by_type"
COST_BY_USER = "costs_by_user"
COST_BY_MODEL = "costs_by_model"
COST_BY_MODULE = "costs_by_module"
TIME_COST_BY_TYPE = "time_costs_by_type"
TIME_COST_BY_USER = "time_costs_by_user"
TIME_COST_BY_MODEL = "time_costs_by_model"
TIME_COST_BY_MODULE = "time_costs_by_module"
AVG_TIME_COST_BY_TYPE = "avg_time_costs_by_type"
AVG_TIME_COST_BY_USER = "avg_time_costs_by_user"
AVG_TIME_COST_BY_MODEL = "avg_time_costs_by_model"
AVG_TIME_COST_BY_MODULE = "avg_time_costs_by_module"
STD_TIME_COST_BY_TYPE = "std_time_costs_by_type"
STD_TIME_COST_BY_USER = "std_time_costs_by_user"
STD_TIME_COST_BY_MODEL = "std_time_costs_by_model"
STD_TIME_COST_BY_MODULE = "std_time_costs_by_module"
ONLINE_TIME = "online_time"
TOTAL_MSG_CNT = "total_messages"
MSG_CNT_BY_CHAT = "messages_by_chat"
TOTAL_REPLY_CNT = "total_replies"


class OnlineTimeRecordTask(AsyncTask):
    """在线时间记录任务"""

    def __init__(self):
        super().__init__(task_name="Online Time Record Task", run_interval=60)

        self.record_id: int | None = None  # Changed to int for Peewee's default ID
        """记录ID"""

        self._init_database()  # 初始化数据库

    @staticmethod
    def _init_database():
        """初始化数据库"""
        with db.atomic():  # Use atomic operations for schema changes
            OnlineTime.create_table(safe=True)  # Creates table if it doesn't exist, Peewee handles indexes from model

    async def run(self):  # sourcery skip: use-named-expression
        try:
            current_time = datetime.now()
            extended_end_time = current_time + timedelta(minutes=1)

            if self.record_id:
                # 如果有记录，则更新结束时间
                query = OnlineTime.update(end_timestamp=extended_end_time).where(OnlineTime.id == self.record_id)  # type: ignore
                updated_rows = query.execute()
                if updated_rows == 0:
                    # Record might have been deleted or ID is stale, try to find/create
                    self.record_id = None  # Reset record_id to trigger find/create logic below

            if not self.record_id:  # Check again if record_id was reset or initially None
                # 如果没有记录，检查一分钟以内是否已有记录
                # Look for a record whose end_timestamp is recent enough to be considered ongoing
                recent_record = (
                    OnlineTime.select()
                    .where(OnlineTime.end_timestamp >= (current_time - timedelta(minutes=1)))  # type: ignore
                    .order_by(OnlineTime.end_timestamp.desc())
                    .first()
                )

                if recent_record:
                    # 如果有记录，则更新结束时间
                    self.record_id = recent_record.id
                    recent_record.end_timestamp = extended_end_time
                    recent_record.save()
                else:
                    # 若没有记录，则插入新的在线时间记录
                    new_record = OnlineTime.create(
                        timestamp=current_time.timestamp(),  # 添加此行
                        start_timestamp=current_time,
                        end_timestamp=extended_end_time,
                        duration=5,  # 初始时长为5分钟
                    )
                    self.record_id = new_record.id
        except Exception as e:
            logger.error(f"在线时间记录失败，错误信息：{e}")


def _format_online_time(online_seconds: int) -> str:
    """
    格式化在线时间
    :param online_seconds: 在线时间（秒）
    :return: 格式化后的在线时间字符串
    """
    total_online_time = timedelta(seconds=online_seconds)

    days = total_online_time.days
    hours = total_online_time.seconds // 3600
    minutes = (total_online_time.seconds // 60) % 60
    seconds = total_online_time.seconds % 60
    if days > 0:
        # 如果在线时间超过1天，则格式化为"X天X小时X分钟"
        return f"{total_online_time.days}天{hours}小时{minutes}分钟{seconds}秒"
    elif hours > 0:
        # 如果在线时间超过1小时，则格式化为"X小时X分钟X秒"
        return f"{hours}小时{minutes}分钟{seconds}秒"
    else:
        # 其他情况格式化为"X分钟X秒"
        return f"{minutes}分钟{seconds}秒"


def _format_large_number(num: float | int) -> str:
    """
    格式化大数字，使用K后缀节省空间（大于9999时）
    :param num: 要格式化的数字
    :return: 格式化后的字符串，如 12K, 1.3K, 120K
    """
    if num >= 10000:
        # 大于等于10000，使用K后缀
        value = num / 1000.0
        if value >= 10:
            number_part = str(int(value))
        else:
            number_part = f"{value:.1f}"
        return f"{number_part}K"
    else:
        # 小于10000，直接显示
        if isinstance(num, float):
            return f"{num:.1f}" if num != int(num) else str(int(num))
        else:
            return str(num)


class StatisticOutputTask(AsyncTask):
    """统计输出任务"""

    SEP_LINE = "-" * 84

    def __init__(self):
        # 延迟300秒启动，运行间隔300秒
        super().__init__(task_name="Statistics Data Output Task", wait_before_start=0, run_interval=300)

        self.name_mapping: Dict[str, Tuple[str, float]] = {}
        """
            联系人/群聊名称映射 {聊天ID: (联系人/群聊名称, 记录时间（timestamp）)}
            注：设计记录时间的目的是方便更新名称，使联系人/群聊名称保持最新
        """

        now = datetime.now()
        if "deploy_time" in local_storage:
            # 如果存在部署时间，则使用该时间作为全量统计的起始时间
            deploy_time = datetime.fromtimestamp(local_storage["deploy_time"])  # type: ignore
        else:
            # 否则，使用最大时间范围，并记录部署时间为当前时间
            deploy_time = datetime(2000, 1, 1)
            local_storage["deploy_time"] = now.timestamp()

        self.stat_period: List[Tuple[str, timedelta, str]] = [
            ("all_time", now - deploy_time, "自部署以来"),  # 必须保留"all_time"
            ("last_30_days", timedelta(days=30), "近30天"),
            ("last_7_days", timedelta(days=7), "近7天"),
            ("last_3_days", timedelta(days=3), "近3天"),
            ("last_24_hours", timedelta(days=1), "近1天"),
            ("last_3_hours", timedelta(hours=3), "近3小时"),
            ("last_hour", timedelta(hours=1), "近1小时"),
            ("last_15_minutes", timedelta(minutes=15), "近15分钟"),
        ]
        """
        统计时间段 [(统计名称, 统计时间段, 统计描述), ...]
        """

    def _statistic_console_output(self, stats: Dict[str, Any], now: datetime):
        """
        输出统计数据到控制台
        :param stats: 统计数据
        :param now: 基准当前时间
        """
        # 输出最近一小时的统计数据

        output = [
            self.SEP_LINE,
            f"  最近1小时的统计数据  (统计截止时间：{now.strftime('%Y-%m-%d %H:%M:%S')}，完整数据请查看 WebUI)",
            self.SEP_LINE,
            self._format_total_stat(stats["last_hour"]),
            "",
            self._format_model_classified_stat(stats["last_hour"]),
            "",
            self._format_module_classified_stat(stats["last_hour"]),
            "",
            self._format_chat_stat(stats["last_hour"]),
            self.SEP_LINE,
            "",
        ]

        logger.info("\n" + "\n".join(output))

    async def run(self):
        try:
            now = datetime.now()

            # 使用线程池并行执行耗时操作
            loop = asyncio.get_event_loop()

            # 在线程池中执行数据库汇总和控制台输出。
            with concurrent.futures.ThreadPoolExecutor() as executor:
                logger.info("正在收集统计数据...")

                # 数据收集任务
                collect_task = loop.run_in_executor(executor, self._collect_all_statistics, now)

                # 等待数据收集完成
                stats = await collect_task
                logger.info("统计数据收集完成")

                # 数据已经持久化到 SQLite，定时任务只保留控制台摘要。
                await loop.run_in_executor(executor, self._statistic_console_output, stats, now)

            logger.info("统计数据输出完成")
        except Exception as e:
            logger.exception(f"输出统计数据过程中发生异常，错误信息：{e}")

    async def run_async_background(self):
        """
        备选方案：完全异步后台运行统计输出
        使用此方法可以让统计任务完全非阻塞
        """

        async def _async_collect_and_output():
            try:
                import concurrent.futures

                now = datetime.now()
                loop = asyncio.get_event_loop()

                with concurrent.futures.ThreadPoolExecutor() as executor:
                    logger.info("正在后台收集统计数据...")

                    # 创建后台任务，不等待完成
                    collect_task = asyncio.create_task(
                        loop.run_in_executor(executor, self._collect_all_statistics, now)  # type: ignore
                    )

                    stats = await collect_task
                    logger.info("统计数据收集完成")

                    await loop.run_in_executor(executor, self._statistic_console_output, stats, now)

                logger.info("统计数据后台输出完成")
            except Exception as e:
                logger.exception(f"后台统计数据输出过程中发生异常：{e}")

        # 创建后台任务，立即返回
        asyncio.create_task(_async_collect_and_output())

    # -- 以下为统计数据收集方法 --

    @staticmethod
    def _collect_model_request_for_period(collect_period: List[Tuple[str, datetime]]) -> Dict[str, Any]:
        """
        收集指定时间段的LLM请求统计数据

        :param collect_period: 统计时间段
        """
        if not collect_period:
            return {}

        # 排序-按照时间段开始时间降序排列（最晚的时间段在前）
        collect_period.sort(key=lambda x: x[1], reverse=True)

        stats = {
            period_key: {
                TOTAL_REQ_CNT: 0,
                REQ_CNT_BY_TYPE: defaultdict(int),
                REQ_CNT_BY_USER: defaultdict(int),
                REQ_CNT_BY_MODEL: defaultdict(int),
                REQ_CNT_BY_MODULE: defaultdict(int),
                IN_TOK_BY_TYPE: defaultdict(int),
                IN_TOK_BY_USER: defaultdict(int),
                IN_TOK_BY_MODEL: defaultdict(int),
                IN_TOK_BY_MODULE: defaultdict(int),
                OUT_TOK_BY_TYPE: defaultdict(int),
                OUT_TOK_BY_USER: defaultdict(int),
                OUT_TOK_BY_MODEL: defaultdict(int),
                OUT_TOK_BY_MODULE: defaultdict(int),
                TOTAL_TOK_BY_TYPE: defaultdict(int),
                TOTAL_TOK_BY_USER: defaultdict(int),
                TOTAL_TOK_BY_MODEL: defaultdict(int),
                TOTAL_TOK_BY_MODULE: defaultdict(int),
                TOTAL_COST: 0.0,
                COST_BY_TYPE: defaultdict(float),
                COST_BY_USER: defaultdict(float),
                COST_BY_MODEL: defaultdict(float),
                COST_BY_MODULE: defaultdict(float),
                TIME_COST_BY_TYPE: defaultdict(list),
                TIME_COST_BY_USER: defaultdict(list),
                TIME_COST_BY_MODEL: defaultdict(list),
                TIME_COST_BY_MODULE: defaultdict(list),
                AVG_TIME_COST_BY_TYPE: defaultdict(float),
                AVG_TIME_COST_BY_USER: defaultdict(float),
                AVG_TIME_COST_BY_MODEL: defaultdict(float),
                AVG_TIME_COST_BY_MODULE: defaultdict(float),
                STD_TIME_COST_BY_TYPE: defaultdict(float),
                STD_TIME_COST_BY_USER: defaultdict(float),
                STD_TIME_COST_BY_MODEL: defaultdict(float),
                STD_TIME_COST_BY_MODULE: defaultdict(float),
            }
            for period_key, _ in collect_period
        }

        # 以最早的时间戳为起始时间获取记录
        # Assuming LLMUsage.timestamp is a DateTimeField
        query_start_time = collect_period[-1][1]
        for record in LLMUsage.select().where(LLMUsage.timestamp >= query_start_time):  # type: ignore
            record_timestamp = record.timestamp  # This is already a datetime object
            for idx, (_, period_start) in enumerate(collect_period):
                if record_timestamp >= period_start:
                    for period_key, _ in collect_period[idx:]:
                        stats[period_key][TOTAL_REQ_CNT] += 1

                        request_type = record.request_type or "unknown"
                        user_id = record.user_id or "unknown"  # user_id is TextField, already string
                        model_name = record.model_assign_name or record.model_name or "unknown"

                        # 提取模块名：如果请求类型包含"."，取第一个"."之前的部分
                        module_name = request_type.split(".")[0] if "." in request_type else request_type

                        stats[period_key][REQ_CNT_BY_TYPE][request_type] += 1
                        stats[period_key][REQ_CNT_BY_USER][user_id] += 1
                        stats[period_key][REQ_CNT_BY_MODEL][model_name] += 1
                        stats[period_key][REQ_CNT_BY_MODULE][module_name] += 1

                        prompt_tokens = record.prompt_tokens or 0
                        completion_tokens = record.completion_tokens or 0
                        total_tokens = prompt_tokens + completion_tokens

                        stats[period_key][IN_TOK_BY_TYPE][request_type] += prompt_tokens
                        stats[period_key][IN_TOK_BY_USER][user_id] += prompt_tokens
                        stats[period_key][IN_TOK_BY_MODEL][model_name] += prompt_tokens
                        stats[period_key][IN_TOK_BY_MODULE][module_name] += prompt_tokens

                        stats[period_key][OUT_TOK_BY_TYPE][request_type] += completion_tokens
                        stats[period_key][OUT_TOK_BY_USER][user_id] += completion_tokens
                        stats[period_key][OUT_TOK_BY_MODEL][model_name] += completion_tokens
                        stats[period_key][OUT_TOK_BY_MODULE][module_name] += completion_tokens

                        stats[period_key][TOTAL_TOK_BY_TYPE][request_type] += total_tokens
                        stats[period_key][TOTAL_TOK_BY_USER][user_id] += total_tokens
                        stats[period_key][TOTAL_TOK_BY_MODEL][model_name] += total_tokens
                        stats[period_key][TOTAL_TOK_BY_MODULE][module_name] += total_tokens

                        cost = record.cost or 0.0
                        stats[period_key][TOTAL_COST] += cost
                        stats[period_key][COST_BY_TYPE][request_type] += cost
                        stats[period_key][COST_BY_USER][user_id] += cost
                        stats[period_key][COST_BY_MODEL][model_name] += cost
                        stats[period_key][COST_BY_MODULE][module_name] += cost

                        # 收集time_cost数据
                        time_cost = record.time_cost or 0.0
                        if time_cost > 0:  # 只记录有效的time_cost
                            stats[period_key][TIME_COST_BY_TYPE][request_type].append(time_cost)
                            stats[period_key][TIME_COST_BY_USER][user_id].append(time_cost)
                            stats[period_key][TIME_COST_BY_MODEL][model_name].append(time_cost)
                            stats[period_key][TIME_COST_BY_MODULE][module_name].append(time_cost)
                    break

        # 计算平均耗时和标准差
        for period_key in stats:
            for category in [REQ_CNT_BY_TYPE, REQ_CNT_BY_USER, REQ_CNT_BY_MODEL, REQ_CNT_BY_MODULE]:
                time_cost_key = f"time_costs_by_{category.split('_')[-1]}"
                avg_key = f"avg_time_costs_by_{category.split('_')[-1]}"
                std_key = f"std_time_costs_by_{category.split('_')[-1]}"

                for item_name in stats[period_key][category]:
                    time_costs = stats[period_key][time_cost_key].get(item_name, [])
                    if time_costs:
                        # 计算平均耗时
                        avg_time_cost = sum(time_costs) / len(time_costs)
                        stats[period_key][avg_key][item_name] = round(avg_time_cost, 3)

                        # 计算标准差
                        if len(time_costs) > 1:
                            variance = sum((x - avg_time_cost) ** 2 for x in time_costs) / len(time_costs)
                            std_time_cost = variance**0.5
                            stats[period_key][std_key][item_name] = round(std_time_cost, 3)
                        else:
                            stats[period_key][std_key][item_name] = 0.0
                    else:
                        stats[period_key][avg_key][item_name] = 0.0
                        stats[period_key][std_key][item_name] = 0.0

        return stats

    @staticmethod
    def _collect_online_time_for_period(collect_period: List[Tuple[str, datetime]], now: datetime) -> Dict[str, Any]:
        """
        收集指定时间段的在线时间统计数据

        :param collect_period: 统计时间段
        """
        if not collect_period:
            return {}

        collect_period.sort(key=lambda x: x[1], reverse=True)

        stats = {
            period_key: {
                ONLINE_TIME: 0.0,
            }
            for period_key, _ in collect_period
        }

        query_start_time = collect_period[-1][1]
        # Assuming OnlineTime.end_timestamp is a DateTimeField
        for record in OnlineTime.select().where(OnlineTime.end_timestamp >= query_start_time):  # type: ignore
            # record.end_timestamp and record.start_timestamp are datetime objects
            record_end_timestamp = record.end_timestamp
            record_start_timestamp = record.start_timestamp

            for idx, (_, period_boundary_start) in enumerate(collect_period):
                if record_end_timestamp >= period_boundary_start:
                    # Calculate effective end time for this record in relation to 'now'
                    effective_end_time = min(record_end_timestamp, now)

                    for period_key, current_period_start_time in collect_period[idx:]:
                        # Determine the portion of the record that falls within this specific statistical period
                        overlap_start = max(record_start_timestamp, current_period_start_time)
                        overlap_end = effective_end_time  # Already capped by 'now' and record's own end

                        if overlap_end > overlap_start:
                            stats[period_key][ONLINE_TIME] += (overlap_end - overlap_start).total_seconds()
                    break
        return stats

    def _collect_message_count_for_period(self, collect_period: List[Tuple[str, datetime]]) -> Dict[str, Any]:
        """
        收集指定时间段的消息统计数据

        :param collect_period: 统计时间段
        """
        if not collect_period:
            return {}

        collect_period.sort(key=lambda x: x[1], reverse=True)

        stats = {
            period_key: {
                TOTAL_MSG_CNT: 0,
                MSG_CNT_BY_CHAT: defaultdict(int),
                TOTAL_REPLY_CNT: 0,
            }
            for period_key, _ in collect_period
        }

        query_start_timestamp = collect_period[-1][1].timestamp()  # Messages.time is a DoubleField (timestamp)
        for message in Messages.select().where(Messages.time >= query_start_timestamp):  # type: ignore
            message_time_ts = message.time  # This is a float timestamp

            chat_id = None
            chat_name = None

            # Logic based on Peewee model structure, aiming to replicate original intent
            if message.chat_info_group_id:
                chat_id = f"g{message.chat_info_group_id}"
                chat_name = message.chat_info_group_name or f"群{message.chat_info_group_id}"
            elif message.user_id:  # Fallback to sender's info for chat_id if not a group_info based chat
                # This uses the message SENDER's ID as per original logic's fallback
                chat_id = f"u{message.user_id}"  # SENDER's user_id
                chat_name = message.user_nickname  # SENDER's nickname
            else:
                # If neither group_id nor sender_id is available for chat identification
                logger.warning(
                    f"Message (PK: {message.id if hasattr(message, 'id') else 'N/A'}) lacks group_id and user_id for chat stats."
                )
                continue

            if not chat_id:  # Should not happen if above logic is correct
                continue

            # Update name_mapping（仅用于展示聊天名称）
            try:
                if chat_id in self.name_mapping:
                    if chat_name != self.name_mapping[chat_id][0] and message_time_ts > self.name_mapping[chat_id][1]:
                        self.name_mapping[chat_id] = (chat_name, message_time_ts)
                else:
                    self.name_mapping[chat_id] = (chat_name, message_time_ts)
            except (IndexError, TypeError) as e:
                logger.warning(f"更新 name_mapping 时发生错误，chat_id: {chat_id}, 错误: {e}")
                # 重置为正确的格式
                self.name_mapping[chat_id] = (chat_name, message_time_ts)

            for idx, (_, period_start_dt) in enumerate(collect_period):
                if message_time_ts >= period_start_dt.timestamp():
                    for period_key, _ in collect_period[idx:]:
                        stats[period_key][TOTAL_MSG_CNT] += 1
                        stats[period_key][MSG_CNT_BY_CHAT][chat_id] += 1
                    break

        # 使用 ActionRecords 中的 reply 动作次数作为回复数基准
        try:
            action_query_start_timestamp = collect_period[-1][1].timestamp()
            for action in ActionRecords.select().where(ActionRecords.time >= action_query_start_timestamp):  # type: ignore
                # 仅统计已完成的 reply 动作
                if action.action_name != "reply" or not action.action_done:
                    continue

                action_time_ts = action.time
                for idx, (_, period_start_dt) in enumerate(collect_period):
                    if action_time_ts >= period_start_dt.timestamp():
                        for period_key, _ in collect_period[idx:]:
                            stats[period_key][TOTAL_REPLY_CNT] += 1
                        break
        except Exception as e:
            logger.warning(f"统计 reply 动作次数失败，将回复数视为 0，错误信息：{e}")

        return stats

    def _collect_all_statistics(self, now: datetime) -> Dict[str, Dict[str, Any]]:
        """
        收集各时间段的统计数据
        :param now: 基准当前时间
        """

        last_all_time_stat = None

        try:
            if "last_full_statistics" in local_storage:
                # 如果存在上次完整统计数据，则使用该数据进行增量统计
                last_stat: Dict[str, Any] = local_storage["last_full_statistics"]  # 上次完整统计数据 # type: ignore

                # 修复 name_mapping 数据类型不匹配问题
                # JSON 中存储为列表，但代码期望为元组
                raw_name_mapping = last_stat["name_mapping"]
                self.name_mapping = {}
                for chat_id, value in raw_name_mapping.items():
                    if isinstance(value, list) and len(value) == 2:
                        # 将列表转换为元组
                        self.name_mapping[chat_id] = (value[0], value[1])
                    elif isinstance(value, tuple) and len(value) == 2:
                        # 已经是元组，直接使用
                        self.name_mapping[chat_id] = value
                    else:
                        # 数据格式不正确，跳过或使用默认值
                        logger.warning(f"name_mapping 中 chat_id {chat_id} 的数据格式不正确: {value}")
                        continue
                last_all_time_stat = last_stat["stat_data"]  # 上次完整统计的统计数据
                last_stat_timestamp = datetime.fromtimestamp(last_stat["timestamp"])  # 上次完整统计数据的时间戳
                self.stat_period = [
                    item for item in self.stat_period if item[0] != "all_time"
                ]  # 删除"所有时间"的统计时段
                self.stat_period.append(("all_time", now - last_stat_timestamp, "自部署以来的"))
        except Exception as e:
            logger.warning(f"加载上次完整统计数据失败，进行全量统计，错误信息：{e}")

        stat_start_timestamp = [(period[0], now - period[1]) for period in self.stat_period]

        stat = {item[0]: {} for item in self.stat_period}

        model_req_stat = self._collect_model_request_for_period(stat_start_timestamp)
        online_time_stat = self._collect_online_time_for_period(stat_start_timestamp, now)
        message_count_stat = self._collect_message_count_for_period(stat_start_timestamp)

        # 统计数据合并
        # 合并三类统计数据
        for period_key, _ in stat_start_timestamp:
            stat[period_key].update(model_req_stat[period_key])
            stat[period_key].update(online_time_stat[period_key])
            stat[period_key].update(message_count_stat[period_key])

        if last_all_time_stat:
            # 若存在上次完整统计数据，则将其与当前统计数据合并
            for key, val in last_all_time_stat.items():
                # 确保当前统计数据中存在该key
                if key not in stat["all_time"]:
                    continue

                if isinstance(val, dict):
                    # 是字典类型，则进行合并
                    for sub_key, sub_val in val.items():
                        # 普通的数值或字典合并
                        if sub_key in stat["all_time"][key]:
                            # 检查是否为嵌套的字典类型（如版本统计）
                            if isinstance(sub_val, dict) and isinstance(stat["all_time"][key][sub_key], dict):
                                # 合并嵌套字典
                                for nested_key, nested_val in sub_val.items():
                                    if nested_key in stat["all_time"][key][sub_key]:
                                        stat["all_time"][key][sub_key][nested_key] += nested_val
                                    else:
                                        stat["all_time"][key][sub_key][nested_key] = nested_val
                            else:
                                # 普通数值累加
                                stat["all_time"][key][sub_key] += sub_val
                        else:
                            stat["all_time"][key][sub_key] = sub_val
                else:
                    # 直接合并
                    stat["all_time"][key] += val

        # 更新上次完整统计数据的时间戳
        # 将所有defaultdict转换为普通dict以避免类型冲突
        clean_stat_data = self._convert_defaultdict_to_dict(stat["all_time"])

        # 将 name_mapping 中的元组转换为列表，因为JSON不支持元组
        json_safe_name_mapping = {}
        for chat_id, (chat_name, timestamp) in self.name_mapping.items():
            json_safe_name_mapping[chat_id] = [chat_name, timestamp]

        local_storage["last_full_statistics"] = {
            "name_mapping": json_safe_name_mapping,
            "stat_data": clean_stat_data,
            "timestamp": now.timestamp(),
        }

        return stat

    def _convert_defaultdict_to_dict(self, data):
        # sourcery skip: dict-comprehension, extract-duplicate-method, inline-immediately-returned-variable, merge-duplicate-blocks
        """递归转换defaultdict为普通dict"""
        if isinstance(data, defaultdict):
            # 转换defaultdict为普通dict
            result = {}
            for key, value in data.items():
                result[key] = self._convert_defaultdict_to_dict(value)
            return result
        elif isinstance(data, dict):
            # 递归处理普通dict
            result = {}
            for key, value in data.items():
                result[key] = self._convert_defaultdict_to_dict(value)
            return result
        else:
            # 其他类型直接返回
            return data

    # -- 以下为统计数据格式化方法 --

    @staticmethod
    def _format_total_stat(stats: Dict[str, Any]) -> str:
        """
        格式化总统计数据
        """
        # 计算总token数（从所有模型的token数中累加）
        total_tokens = sum(stats[TOTAL_TOK_BY_MODEL].values()) if stats[TOTAL_TOK_BY_MODEL] else 0

        # 计算花费/消息数量指标（每100条）
        cost_per_100_messages = (stats[TOTAL_COST] / stats[TOTAL_MSG_CNT] * 100) if stats[TOTAL_MSG_CNT] > 0 else 0.0

        # 计算花费/时间指标（花费/小时）
        online_hours = stats[ONLINE_TIME] / 3600.0 if stats[ONLINE_TIME] > 0 else 0.0
        cost_per_hour = stats[TOTAL_COST] / online_hours if online_hours > 0 else 0.0

        # 计算token/时间指标（token/小时）
        tokens_per_hour = (total_tokens / online_hours) if online_hours > 0 else 0.0

        # 计算花费/回复数量指标（每100条）
        total_replies = stats.get(TOTAL_REPLY_CNT, 0)
        cost_per_100_replies = (stats[TOTAL_COST] / total_replies * 100) if total_replies > 0 else 0.0

        # 计算花费/消息数量（排除自己回复）指标（每100条）
        total_messages_excluding_replies = stats[TOTAL_MSG_CNT] - total_replies
        cost_per_100_messages_excluding_replies = (
            (stats[TOTAL_COST] / total_messages_excluding_replies * 100)
            if total_messages_excluding_replies > 0
            else 0.0
        )

        output = [
            f"总在线时间: {_format_online_time(stats[ONLINE_TIME])}",
            f"总消息数: {_format_large_number(stats[TOTAL_MSG_CNT])}",
            f"总回复数: {_format_large_number(total_replies)}",
            f"总请求数: {_format_large_number(stats[TOTAL_REQ_CNT])}",
            f"总Token数: {_format_large_number(total_tokens)}",
            f"总花费: {stats[TOTAL_COST]:.2f}¥",
            f"花费/消息数量: {cost_per_100_messages:.4f}¥/100条" if stats[TOTAL_MSG_CNT] > 0 else "花费/消息数量: N/A",
            f"花费/接受消息数量: {cost_per_100_messages_excluding_replies:.4f}¥/100条"
            if total_messages_excluding_replies > 0
            else "花费/消息数量(排除回复): N/A",
            f"花费/回复消息数量: {cost_per_100_replies:.4f}¥/100条" if total_replies > 0 else "花费/回复数量: N/A",
            f"花费/时间: {cost_per_hour:.2f}¥/小时" if online_hours > 0 else "花费/时间: N/A",
            f"Token/时间: {_format_large_number(tokens_per_hour)}/小时" if online_hours > 0 else "Token/时间: N/A",
            "",
        ]

        return "\n".join(output)

    @staticmethod
    def _format_model_classified_stat(stats: Dict[str, Any]) -> str:
        """
        格式化按模型分类的统计数据
        """
        if stats[TOTAL_REQ_CNT] <= 0:
            return ""
        data_fmt = "{:<32}  {:>10}  {:>12}  {:>12}  {:>12}  {:>9.2f}¥  {:>10.1f}  {:>10.1f}  {:>12}  {:>12}  {:>12}"

        total_replies = stats.get(TOTAL_REPLY_CNT, 0)

        output = [
            "按模型分类统计:",
            " 模型名称                          调用次数    输入Token     输出Token     Token总量     累计花费    平均耗时(秒)  标准差(秒)  每次回复平均调用次数  每次回复平均Token数  每次调用平均Token",
        ]
        for model_name, count in sorted(stats[REQ_CNT_BY_MODEL].items()):
            name = f"{model_name[:29]}..." if len(model_name) > 32 else model_name
            in_tokens = stats[IN_TOK_BY_MODEL][model_name]
            out_tokens = stats[OUT_TOK_BY_MODEL][model_name]
            tokens = stats[TOTAL_TOK_BY_MODEL][model_name]
            cost = stats[COST_BY_MODEL][model_name]
            avg_time_cost = stats[AVG_TIME_COST_BY_MODEL][model_name]
            std_time_cost = stats[STD_TIME_COST_BY_MODEL][model_name]

            # 计算每次回复平均值
            avg_count_per_reply = count / total_replies if total_replies > 0 else 0.0
            avg_tokens_per_reply = tokens / total_replies if total_replies > 0 else 0.0

            # 计算每次调用平均token
            avg_tokens_per_call = tokens / count if count > 0 else 0.0

            # 格式化大数字
            formatted_count = _format_large_number(count)
            formatted_in_tokens = _format_large_number(in_tokens)
            formatted_out_tokens = _format_large_number(out_tokens)
            formatted_tokens = _format_large_number(tokens)
            formatted_avg_count = _format_large_number(avg_count_per_reply) if total_replies > 0 else "N/A"
            formatted_avg_tokens = _format_large_number(avg_tokens_per_reply) if total_replies > 0 else "N/A"
            formatted_avg_tokens_per_call = _format_large_number(avg_tokens_per_call) if count > 0 else "N/A"

            output.append(
                data_fmt.format(
                    name,
                    formatted_count,
                    formatted_in_tokens,
                    formatted_out_tokens,
                    formatted_tokens,
                    cost,
                    avg_time_cost,
                    std_time_cost,
                    formatted_avg_count,
                    formatted_avg_tokens,
                    formatted_avg_tokens_per_call,
                )
            )

        output.append("")
        return "\n".join(output)

    @staticmethod
    def _format_module_classified_stat(stats: Dict[str, Any]) -> str:
        """
        格式化按模块分类的统计数据
        """
        if stats[TOTAL_REQ_CNT] <= 0:
            return ""
        data_fmt = "{:<32}  {:>10}  {:>12}  {:>12}  {:>12}  {:>9.2f}¥  {:>10.1f}  {:>10.1f}  {:>12}  {:>12}  {:>12}"

        total_replies = stats.get(TOTAL_REPLY_CNT, 0)

        output = [
            "按模块分类统计:",
            " 模块名称                          调用次数    输入Token     输出Token     Token总量     累计花费    平均耗时(秒)  标准差(秒)  每次回复平均调用次数  每次回复平均Token数  每次调用平均Token",
        ]
        for module_name, count in sorted(stats[REQ_CNT_BY_MODULE].items()):
            name = f"{module_name[:29]}..." if len(module_name) > 32 else module_name
            in_tokens = stats[IN_TOK_BY_MODULE][module_name]
            out_tokens = stats[OUT_TOK_BY_MODULE][module_name]
            tokens = stats[TOTAL_TOK_BY_MODULE][module_name]
            cost = stats[COST_BY_MODULE][module_name]
            avg_time_cost = stats[AVG_TIME_COST_BY_MODULE][module_name]
            std_time_cost = stats[STD_TIME_COST_BY_MODULE][module_name]

            # 计算每次回复平均值
            avg_count_per_reply = count / total_replies if total_replies > 0 else 0.0
            avg_tokens_per_reply = tokens / total_replies if total_replies > 0 else 0.0

            # 计算每次调用平均token
            avg_tokens_per_call = tokens / count if count > 0 else 0.0

            # 格式化大数字
            formatted_count = _format_large_number(count)
            formatted_in_tokens = _format_large_number(in_tokens)
            formatted_out_tokens = _format_large_number(out_tokens)
            formatted_tokens = _format_large_number(tokens)
            formatted_avg_count = _format_large_number(avg_count_per_reply) if total_replies > 0 else "N/A"
            formatted_avg_tokens = _format_large_number(avg_tokens_per_reply) if total_replies > 0 else "N/A"
            formatted_avg_tokens_per_call = _format_large_number(avg_tokens_per_call) if count > 0 else "N/A"

            output.append(
                data_fmt.format(
                    name,
                    formatted_count,
                    formatted_in_tokens,
                    formatted_out_tokens,
                    formatted_tokens,
                    cost,
                    avg_time_cost,
                    std_time_cost,
                    formatted_avg_count,
                    formatted_avg_tokens,
                    formatted_avg_tokens_per_call,
                )
            )

        output.append("")
        return "\n".join(output)

    def _format_chat_stat(self, stats: Dict[str, Any]) -> str:
        """
        格式化聊天统计数据
        """
        if stats[TOTAL_MSG_CNT] <= 0:
            return ""
        output = ["聊天消息统计:", " 联系人/群组名称                  消息数量"]
        for chat_id, count in sorted(stats[MSG_CNT_BY_CHAT].items()):
            try:
                chat_name = self.name_mapping.get(chat_id, ("未知聊天", 0))[0]
                formatted_count = _format_large_number(count)
                output.append(f"{chat_name[:32]:<32}  {formatted_count:>10}")
            except (IndexError, TypeError) as e:
                logger.warning(f"格式化聊天统计时发生错误，chat_id: {chat_id}, 错误: {e}")
                formatted_count = _format_large_number(count)
                output.append(f"{'未知聊天':<32}  {formatted_count:>10}")
        output.append("")
        return "\n".join(output)


class AsyncStatisticOutputTask(AsyncTask):
    """完全异步的统计输出任务 - 更高性能版本"""

    def __init__(self):
        # 延迟0秒启动，运行间隔300秒
        super().__init__(task_name="Async Statistics Data Output Task", wait_before_start=0, run_interval=300)

        # 直接复用 StatisticOutputTask 的初始化逻辑
        temp_stat_task = StatisticOutputTask()
        self.name_mapping = temp_stat_task.name_mapping
        self.stat_period = temp_stat_task.stat_period

    async def run(self):
        """完全异步执行统计任务"""

        async def _async_collect_and_output():
            try:
                now = datetime.now()
                loop = asyncio.get_event_loop()

                with concurrent.futures.ThreadPoolExecutor() as executor:
                    logger.info("正在后台收集统计数据...")

                    # 数据收集任务
                    collect_task = asyncio.create_task(
                        loop.run_in_executor(executor, self._collect_all_statistics, now)  # type: ignore
                    )

                    stats = await collect_task
                    logger.info("统计数据收集完成")

                    await loop.run_in_executor(executor, self._statistic_console_output, stats, now)

                logger.info("统计数据后台输出完成")
            except Exception as e:
                logger.exception(f"后台统计数据输出过程中发生异常：{e}")

        # 创建后台任务，立即返回
        asyncio.create_task(_async_collect_and_output())

    # 复用 StatisticOutputTask 的所有方法
    def _collect_all_statistics(self, now: datetime):
        return StatisticOutputTask._collect_all_statistics(self, now)  # type: ignore

    def _statistic_console_output(self, stats: Dict[str, Any], now: datetime):
        return StatisticOutputTask._statistic_console_output(self, stats, now)  # type: ignore

    # 其他需要的方法也可以类似复用...
    @staticmethod
    def _collect_model_request_for_period(collect_period: List[Tuple[str, datetime]]) -> Dict[str, Any]:
        return StatisticOutputTask._collect_model_request_for_period(collect_period)

    @staticmethod
    def _collect_online_time_for_period(collect_period: List[Tuple[str, datetime]], now: datetime) -> Dict[str, Any]:
        return StatisticOutputTask._collect_online_time_for_period(collect_period, now)

    def _collect_message_count_for_period(self, collect_period: List[Tuple[str, datetime]]) -> Dict[str, Any]:
        return StatisticOutputTask._collect_message_count_for_period(self, collect_period)  # type: ignore

    @staticmethod
    def _format_total_stat(stats: Dict[str, Any]) -> str:
        return StatisticOutputTask._format_total_stat(stats)

    @staticmethod
    def _format_model_classified_stat(stats: Dict[str, Any]) -> str:
        return StatisticOutputTask._format_model_classified_stat(stats)

    def _format_chat_stat(self, stats: Dict[str, Any]) -> str:
        return StatisticOutputTask._format_chat_stat(self, stats)  # type: ignore

    def _convert_defaultdict_to_dict(self, data):
        return StatisticOutputTask._convert_defaultdict_to_dict(self, data)  # type: ignore
