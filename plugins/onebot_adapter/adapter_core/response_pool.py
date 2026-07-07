import asyncio
import time
from typing import Dict
from .config import global_config
from .logger import logger

response_dict: Dict = {}
response_time_dict: Dict = {}


async def get_response(request_id: str, timeout: int = 10) -> dict:
    response = await asyncio.wait_for(_get_response(request_id), timeout)
    _ = response_time_dict.pop(request_id)
    logger.debug(f"响应信息已取出: echo_id={request_id}")
    return response


async def _get_response(request_id: str) -> dict:
    """
    内部使用的获取响应函数，主要用于在需要时获取响应
    """
    while request_id not in response_dict:
        await asyncio.sleep(0.2)
    return response_dict.pop(request_id)


async def put_response(response: dict):
    echo_id = response.get("echo")
    now_time = time.time()
    response_dict[echo_id] = response
    response_time_dict[echo_id] = now_time
    logger.debug(f"响应信息已存入: echo_id={echo_id}")


async def check_timeout_response() -> None:
    while True:
        cleaned_message_count: int = 0
        now_time = time.time()
        for echo_id, response_time in list(response_time_dict.items()):
            if now_time - response_time > global_config.napcat_server.heartbeat_interval:
                cleaned_message_count += 1
                response_dict.pop(echo_id)
                response_time_dict.pop(echo_id)
                logger.debug(f"响应消息超时并移除: echo_id={echo_id}")
        if cleaned_message_count:
            logger.warning(f"已移除超时响应消息: count={cleaned_message_count}")
        await asyncio.sleep(global_config.napcat_server.heartbeat_interval)
