"""
OpenCode HTTP 客户端：健康检查、会话列表/创建、发消息。
解析 POST /session/:id/message 响应时只提取最终结果（最后一条 text part）。
支持 OPENCODE_USE_ASYNC=1 时用 prompt_async + 轮询，避免长任务单次 HTTP 超时。
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Optional, Tuple

import httpx


def _parse_json(r: httpx.Response) -> dict | list:
    """解析响应为 JSON，若为空或非 JSON 则抛出带状态码和内容预览的异常。"""
    text = (r.text or "").strip()
    if not text:
        raise ValueError(
            f"OpenCode 返回空内容 (HTTP {r.status_code})，请确认服务已启动且地址正确: {_get_base_url()}"
        )
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        preview = text[:200].replace("\n", " ")
        raise ValueError(
            f"OpenCode 返回非 JSON (HTTP {r.status_code})，内容预览: {preview}。错误: {e}"
        ) from e

DEFAULT_BASE_URL = "http://127.0.0.1:4096"


def _message_timeout() -> float:
    """可配置：环境变量 OPENCODE_MESSAGE_TIMEOUT（秒），默认 600（10 分钟）。"""
    try:
        t = os.environ.get("OPENCODE_MESSAGE_TIMEOUT", "")
        if t:
            return max(60.0, float(t))
    except ValueError:
        pass
    return 600.0


def _auth() -> Optional[Tuple[str, str]]:
    password = os.environ.get("OPENCODE_SERVER_PASSWORD", "")
    if not password:
        return None
    user = os.environ.get("OPENCODE_SERVER_USERNAME", "opencode")
    return (user, password)


def _get_base_url() -> str:
    return os.environ.get("OPENCODE_BASE_URL", DEFAULT_BASE_URL)


def _extract_final_result(data: dict) -> str:
    """从 POST /session/:id/message 的响应中只取最终结果（最后一个 text part）。"""
    parts = data.get("parts") or []
    text_parts = [p.get("text") for p in parts if p.get("type") == "text" and "text" in p]
    if not text_parts:
        return ""
    return text_parts[-1].strip()


async def health() -> dict:
    """GET /global/health"""
    async with httpx.AsyncClient(
        base_url=_get_base_url(), auth=_auth(), timeout=10.0
    ) as client:
        r = await client.get("/global/health")
        r.raise_for_status()
        return _parse_json(r)


async def list_sessions() -> list:
    """GET /session"""
    async with httpx.AsyncClient(
        base_url=_get_base_url(), auth=_auth(), timeout=10.0
    ) as client:
        r = await client.get("/session")
        r.raise_for_status()
        return _parse_json(r)


async def create_session(title: Optional[str] = None) -> dict:
    """POST /session"""
    async with httpx.AsyncClient(
        base_url=_get_base_url(), auth=_auth(), timeout=10.0
    ) as client:
        r = await client.post("/session", json={"title": title} if title else {})
        r.raise_for_status()
        return _parse_json(r)


async def _get_messages(session_id: str, limit: int = 5) -> list:
    """GET /session/:id/message?limit=N"""
    async with httpx.AsyncClient(
        base_url=_get_base_url(), auth=_auth(), timeout=15.0
    ) as client:
        r = await client.get(f"/session/{session_id}/message", params={"limit": limit})
        r.raise_for_status()
        return _parse_json(r)


async def get_session_messages(session_id: str, limit: int = 500) -> list:
    """GET /session/:id/message?limit=N，获取当前会话所有消息（用于导出）。"""
    return await _get_messages(session_id, limit=limit)


async def send_message_async_poll(session_id: str, text: str) -> str:
    """
    POST /session/:id/prompt_async 提交后轮询 GET message，避免单次长连接超时。
    总等待时间受 OPENCODE_MESSAGE_TIMEOUT 限制，轮询间隔 3 秒。
    """
    timeout = _message_timeout()
    async with httpx.AsyncClient(
        base_url=_get_base_url(), auth=_auth(), timeout=15.0
    ) as client:
        r = await client.post(
            f"/session/{session_id}/prompt_async",
            json={"parts": [{"type": "text", "text": text}]},
        )
        r.raise_for_status()
    n_before = len(await _get_messages(session_id, limit=10))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        await asyncio.sleep(3)
        messages = await _get_messages(session_id, limit=10)
        if len(messages) > n_before:
            last = messages[-1]
            result = _extract_final_result(last)
            if result:
                return result
    raise httpx.TimeoutException("轮询等待结果超时")


async def send_message(session_id: str, text: str) -> str:
    """
    POST /session/:id/message，只返回解析出的最终结果（最后一条 text part）。
    若 OPENCODE_USE_ASYNC=1 则改用 prompt_async + 轮询，适合长任务。
    长任务可能超时；可设置 OPENCODE_MESSAGE_TIMEOUT（秒）增大超时。
    """
    if os.environ.get("OPENCODE_USE_ASYNC", "").strip() in ("1", "true", "yes"):
        return await send_message_async_poll(session_id, text)
    timeout = _message_timeout()
    async with httpx.AsyncClient(
        base_url=_get_base_url(), auth=_auth(), timeout=timeout
    ) as client:
        r = await client.post(
            f"/session/{session_id}/message",
            json={"parts": [{"type": "text", "text": text}]},
        )
        r.raise_for_status()
        data = _parse_json(r)
        return _extract_final_result(data)
