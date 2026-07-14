"""数据库统计数据 API 路由。"""

from datetime import datetime, timedelta
from typing import Any, Literal, Optional

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Query
from peewee import Case, fn
from pydantic import BaseModel, Field

from src.common.database.database_model import ActionRecords, LLMUsage, Messages, OnlineTime
from src.common.logger import get_logger
from src.webui.auth import verify_auth_token_from_cookie_or_header

logger = get_logger("webui.statistics")

router = APIRouter(prefix="/statistics", tags=["statistics"])


def require_auth(
    maibot_session: Optional[str] = Cookie(None),
    authorization: Optional[str] = Header(None),
) -> bool:
    """认证依赖：验证用户是否已登录。"""
    return verify_auth_token_from_cookie_or_header(maibot_session, authorization)


class StatisticsSummary(BaseModel):
    """统计数据摘要。"""

    total_requests: int = Field(0, description="总请求数")
    total_cost: float = Field(0.0, description="总花费")
    total_tokens: int = Field(0, description="总 token 数")
    online_time: float = Field(0.0, description="在线时间（秒）")
    total_messages: int = Field(0, description="总消息数")
    total_replies: int = Field(0, description="总回复数")
    avg_response_time: float = Field(0.0, description="平均响应时间")
    cost_per_hour: float = Field(0.0, description="每小时花费")
    tokens_per_hour: float = Field(0.0, description="每小时 token 数")


class LLMStatisticsBase(BaseModel):
    """LLM 聚合统计的公共字段。"""

    request_count: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    total_cost: float = 0.0
    avg_response_time: float = 0.0


class ModelStatistics(LLMStatisticsBase):
    """模型统计。"""

    model_name: str


class CategoryStatistics(LLMStatisticsBase):
    """模块或请求类型统计。"""

    name: str


class ChatStatistics(BaseModel):
    """聊天维度统计。"""

    chat_id: str
    chat_name: str
    message_count: int = 0


class TimeSeriesData(BaseModel):
    """时间序列数据。"""

    timestamp: str
    requests: int = 0
    cost: float = 0.0
    tokens: int = 0


class RecentActivity(BaseModel):
    """最近一次 LLM 请求。"""

    timestamp: str
    model: str
    request_type: str
    tokens: int = 0
    cost: float = 0.0
    time_cost: float = 0.0
    status: str


class StatisticsPeriod(BaseModel):
    """报表时间范围。"""

    start_time: str
    end_time: str
    hours: int


class DashboardData(BaseModel):
    """首页仪表盘数据。"""

    summary: StatisticsSummary
    model_stats: list[ModelStatistics]
    hourly_data: list[TimeSeriesData]
    daily_data: list[TimeSeriesData]
    recent_activity: list[RecentActivity]


class StatisticsReport(BaseModel):
    """完整统计报表。"""

    period: StatisticsPeriod
    summary: StatisticsSummary
    model_stats: list[ModelStatistics]
    module_stats: list[CategoryStatistics]
    request_type_stats: list[CategoryStatistics]
    chat_stats: list[ChatStatistics]
    time_series: list[TimeSeriesData]
    time_series_granularity: Literal["hour", "day"]
    recent_activity: list[RecentActivity]


def _llm_time_range(start_time: datetime, end_time: datetime):
    return (LLMUsage.timestamp >= start_time) & (LLMUsage.timestamp <= end_time)


def _normalized_model_name():
    return fn.COALESCE(
        fn.NULLIF(LLMUsage.model_assign_name, ""),
        fn.NULLIF(LLMUsage.model_name, ""),
        "unknown",
    )


def _normalized_request_type():
    return fn.COALESCE(fn.NULLIF(LLMUsage.request_type, ""), "unknown")


def _module_name():
    request_type = _normalized_request_type()
    separator_index = fn.INSTR(request_type, ".")
    return Case(
        None,
        ((separator_index > 0, fn.SUBSTR(request_type, 1, separator_index - 1)),),
        request_type,
    )


def _aggregate_llm_query(group_expression, start_time: datetime, end_time: datetime, limit: int):
    return (
        LLMUsage.select(
            group_expression.alias("name"),
            fn.COUNT(LLMUsage.id).alias("request_count"),
            fn.COALESCE(fn.SUM(LLMUsage.prompt_tokens), 0).alias("prompt_tokens"),
            fn.COALESCE(fn.SUM(LLMUsage.completion_tokens), 0).alias("completion_tokens"),
            fn.COALESCE(fn.SUM(LLMUsage.prompt_tokens + LLMUsage.completion_tokens), 0).alias("total_tokens"),
            fn.COALESCE(fn.SUM(LLMUsage.cost), 0).alias("total_cost"),
            fn.COALESCE(fn.AVG(LLMUsage.time_cost), 0).alias("avg_response_time"),
        )
        .where(_llm_time_range(start_time, end_time))
        .group_by(group_expression)
        .order_by(fn.COUNT(LLMUsage.id).desc(), group_expression.asc())
        .limit(limit)
    )


def _statistics_values(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "request_count": row["request_count"] or 0,
        "prompt_tokens": row["prompt_tokens"] or 0,
        "completion_tokens": row["completion_tokens"] or 0,
        "total_tokens": row["total_tokens"] or 0,
        "total_cost": row["total_cost"] or 0.0,
        "avg_response_time": row["avg_response_time"] or 0.0,
    }


async def _get_summary_statistics(start_time: datetime, end_time: datetime) -> StatisticsSummary:
    """从数据库聚合统计摘要。"""
    result = (
        LLMUsage.select(
            fn.COUNT(LLMUsage.id).alias("total_requests"),
            fn.COALESCE(fn.SUM(LLMUsage.cost), 0).alias("total_cost"),
            fn.COALESCE(fn.SUM(LLMUsage.prompt_tokens + LLMUsage.completion_tokens), 0).alias("total_tokens"),
            fn.COALESCE(fn.AVG(LLMUsage.time_cost), 0).alias("avg_response_time"),
        )
        .where(_llm_time_range(start_time, end_time))
        .dicts()
        .get()
    )
    summary = StatisticsSummary(
        total_requests=result["total_requests"] or 0,
        total_cost=result["total_cost"] or 0.0,
        total_tokens=result["total_tokens"] or 0,
        avg_response_time=result["avg_response_time"] or 0.0,
    )

    online_records = OnlineTime.select().where(
        (OnlineTime.start_timestamp <= end_time) & (OnlineTime.end_timestamp >= start_time)
    )
    for record in online_records:
        overlap_start = max(record.start_timestamp, start_time)
        overlap_end = min(record.end_timestamp, end_time)
        if overlap_end > overlap_start:
            summary.online_time += (overlap_end - overlap_start).total_seconds()

    summary.total_messages = (
        Messages.select(fn.COUNT(Messages.id))
        .where((Messages.time >= start_time.timestamp()) & (Messages.time <= end_time.timestamp()))
        .scalar()
        or 0
    )
    summary.total_replies = (
        ActionRecords.select(fn.COUNT(ActionRecords.id))
        .where(
            (ActionRecords.time >= start_time.timestamp())
            & (ActionRecords.time <= end_time.timestamp())
            & (ActionRecords.action_name == "reply")
            & ActionRecords.action_done
        )
        .scalar()
        or 0
    )

    if summary.online_time > 0:
        online_hours = summary.online_time / 3600.0
        summary.cost_per_hour = summary.total_cost / online_hours
        summary.tokens_per_hour = summary.total_tokens / online_hours

    return summary


async def _get_model_statistics(
    start_time: datetime,
    end_time: datetime,
    limit: int = 10,
) -> list[ModelStatistics]:
    """按模型聚合数据库中的 LLM 使用记录。"""
    result: list[ModelStatistics] = []
    for row in _aggregate_llm_query(_normalized_model_name(), start_time, end_time, limit).dicts():
        result.append(ModelStatistics(model_name=row["name"], **_statistics_values(row)))
    return result


async def _get_llm_breakdown_statistics(
    start_time: datetime,
    end_time: datetime,
    group_by: Literal["module", "request_type"],
    limit: int = 50,
) -> list[CategoryStatistics]:
    """按模块或完整请求类型聚合 LLM 使用记录。"""
    group_expression = _module_name() if group_by == "module" else _normalized_request_type()
    result: list[CategoryStatistics] = []
    for row in _aggregate_llm_query(group_expression, start_time, end_time, limit).dicts():
        result.append(CategoryStatistics(name=row["name"], **_statistics_values(row)))
    return result


async def _get_chat_statistics(start_time: datetime, end_time: datetime, limit: int = 50) -> list[ChatStatistics]:
    """按聊天会话聚合消息数量。"""
    has_group = Messages.chat_info_group_id.is_null(False) & (Messages.chat_info_group_id != "")
    chat_id = Case(
        None,
        ((has_group, fn.printf("g%s", Messages.chat_info_group_id)),),
        fn.COALESCE(fn.NULLIF(Messages.chat_id, ""), "unknown"),
    )
    group_name = fn.COALESCE(
        fn.NULLIF(Messages.chat_info_group_name, ""),
        fn.printf("群聊%s", Messages.chat_info_group_id),
    )
    private_name = fn.COALESCE(
        fn.NULLIF(Messages.chat_info_user_nickname, ""),
        fn.NULLIF(Messages.user_nickname, ""),
        fn.NULLIF(Messages.chat_id, ""),
        "未知聊天",
    )
    chat_name = Case(None, ((has_group, group_name),), private_name)

    query = (
        Messages.select(
            chat_id.alias("chat_id"),
            fn.MAX(chat_name).alias("chat_name"),
            fn.COUNT(Messages.id).alias("message_count"),
        )
        .where((Messages.time >= start_time.timestamp()) & (Messages.time <= end_time.timestamp()))
        .group_by(chat_id)
        .order_by(fn.COUNT(Messages.id).desc(), chat_id.asc())
        .limit(limit)
    )
    return [
        ChatStatistics(
            chat_id=row["chat_id"],
            chat_name=row["chat_name"] or row["chat_id"],
            message_count=row["message_count"] or 0,
        )
        for row in query.dicts()
    ]


async def _get_hourly_statistics(start_time: datetime, end_time: datetime) -> list[TimeSeriesData]:
    """获取小时级统计数据。"""
    bucket = fn.strftime("%Y-%m-%dT%H:00:00", LLMUsage.timestamp)
    query = (
        LLMUsage.select(
            bucket.alias("bucket"),
            fn.COUNT(LLMUsage.id).alias("requests"),
            fn.COALESCE(fn.SUM(LLMUsage.cost), 0).alias("cost"),
            fn.COALESCE(fn.SUM(LLMUsage.prompt_tokens + LLMUsage.completion_tokens), 0).alias("tokens"),
        )
        .where(_llm_time_range(start_time, end_time))
        .group_by(bucket)
    )
    data_by_bucket = {row["bucket"]: row for row in query.dicts()}

    result: list[TimeSeriesData] = []
    current = start_time.replace(minute=0, second=0, microsecond=0)
    while current <= end_time:
        bucket_name = current.strftime("%Y-%m-%dT%H:00:00")
        row = data_by_bucket.get(bucket_name)
        result.append(
            TimeSeriesData(
                timestamp=bucket_name,
                requests=(row or {}).get("requests", 0),
                cost=(row or {}).get("cost", 0.0),
                tokens=(row or {}).get("tokens", 0),
            )
        )
        current += timedelta(hours=1)
    return result


async def _get_daily_statistics(start_time: datetime, end_time: datetime) -> list[TimeSeriesData]:
    """获取日级统计数据。"""
    bucket = fn.strftime("%Y-%m-%dT00:00:00", LLMUsage.timestamp)
    query = (
        LLMUsage.select(
            bucket.alias("bucket"),
            fn.COUNT(LLMUsage.id).alias("requests"),
            fn.COALESCE(fn.SUM(LLMUsage.cost), 0).alias("cost"),
            fn.COALESCE(fn.SUM(LLMUsage.prompt_tokens + LLMUsage.completion_tokens), 0).alias("tokens"),
        )
        .where(_llm_time_range(start_time, end_time))
        .group_by(bucket)
    )
    data_by_bucket = {row["bucket"]: row for row in query.dicts()}

    result: list[TimeSeriesData] = []
    current = start_time.replace(hour=0, minute=0, second=0, microsecond=0)
    while current <= end_time:
        bucket_name = current.strftime("%Y-%m-%dT00:00:00")
        row = data_by_bucket.get(bucket_name)
        result.append(
            TimeSeriesData(
                timestamp=bucket_name,
                requests=(row or {}).get("requests", 0),
                cost=(row or {}).get("cost", 0.0),
                tokens=(row or {}).get("tokens", 0),
            )
        )
        current += timedelta(days=1)
    return result


async def _get_recent_activity(
    start_time: datetime,
    end_time: datetime,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """获取所选时间范围内最近的 LLM 请求。"""
    records = (
        LLMUsage.select().where(_llm_time_range(start_time, end_time)).order_by(LLMUsage.timestamp.desc()).limit(limit)
    )
    return [
        {
            "timestamp": record.timestamp.isoformat(),
            "model": record.model_assign_name or record.model_name or "unknown",
            "request_type": record.request_type or "unknown",
            "tokens": (record.prompt_tokens or 0) + (record.completion_tokens or 0),
            "cost": record.cost or 0.0,
            "time_cost": record.time_cost or 0.0,
            "status": record.status,
        }
        for record in records
    ]


@router.get("/dashboard", response_model=DashboardData)
async def get_dashboard_data(
    hours: int = Query(24, ge=1, le=8760),
    _auth: bool = Depends(require_auth),
) -> DashboardData:
    """获取首页仪表盘统计数据。"""
    try:
        now = datetime.now()
        start_time = now - timedelta(hours=hours)
        return DashboardData(
            summary=await _get_summary_statistics(start_time, now),
            model_stats=await _get_model_statistics(start_time, now),
            hourly_data=await _get_hourly_statistics(start_time, now),
            daily_data=await _get_daily_statistics(now - timedelta(days=7), now),
            recent_activity=await _get_recent_activity(start_time, now, limit=10),
        )
    except Exception as exc:
        logger.exception("获取仪表盘数据失败")
        raise HTTPException(status_code=500, detail="获取统计数据失败") from exc


@router.get("/report", response_model=StatisticsReport)
async def get_statistics_report(
    hours: int = Query(24, ge=1, le=8760),
    recent_limit: int = Query(20, ge=1, le=100),
    _auth: bool = Depends(require_auth),
) -> StatisticsReport:
    """获取 WebUI 统计页面使用的完整数据库报表。"""
    try:
        now = datetime.now()
        start_time = now - timedelta(hours=hours)
        if hours <= 48:
            time_series = await _get_hourly_statistics(start_time, now)
            granularity: Literal["hour", "day"] = "hour"
        else:
            time_series = await _get_daily_statistics(start_time, now)
            granularity = "day"

        return StatisticsReport(
            period=StatisticsPeriod(start_time=start_time.isoformat(), end_time=now.isoformat(), hours=hours),
            summary=await _get_summary_statistics(start_time, now),
            model_stats=await _get_model_statistics(start_time, now, limit=50),
            module_stats=await _get_llm_breakdown_statistics(start_time, now, group_by="module"),
            request_type_stats=await _get_llm_breakdown_statistics(start_time, now, group_by="request_type"),
            chat_stats=await _get_chat_statistics(start_time, now),
            time_series=time_series,
            time_series_granularity=granularity,
            recent_activity=await _get_recent_activity(start_time, now, limit=recent_limit),
        )
    except Exception as exc:
        logger.exception("获取完整统计报表失败")
        raise HTTPException(status_code=500, detail="获取统计报表失败") from exc


@router.get("/summary", response_model=StatisticsSummary)
async def get_summary(
    hours: int = Query(24, ge=1, le=8760),
    _auth: bool = Depends(require_auth),
) -> StatisticsSummary:
    """获取统计摘要。"""
    try:
        now = datetime.now()
        return await _get_summary_statistics(now - timedelta(hours=hours), now)
    except Exception as exc:
        logger.exception("获取统计摘要失败")
        raise HTTPException(status_code=500, detail="获取统计摘要失败") from exc


@router.get("/models", response_model=list[ModelStatistics])
async def get_model_stats(
    hours: int = Query(24, ge=1, le=8760),
    _auth: bool = Depends(require_auth),
) -> list[ModelStatistics]:
    """获取模型统计。"""
    try:
        now = datetime.now()
        return await _get_model_statistics(now - timedelta(hours=hours), now)
    except Exception as exc:
        logger.exception("获取模型统计失败")
        raise HTTPException(status_code=500, detail="获取模型统计失败") from exc
