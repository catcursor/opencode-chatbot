"""
OpenCode HTTP client.

Only visible text parts are returned to chat clients. Tool calls, tool results,
reasoning/thinking parts, and other non-text parts are deliberately skipped.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Optional, Tuple

import httpx

DEFAULT_BASE_URL = "http://127.0.0.1:4096"


def _parse_json(r: httpx.Response) -> dict | list:
    text = (r.text or "").strip()
    if not text:
        raise ValueError(
            f"OpenCode returned an empty response (HTTP {r.status_code}); "
            f"check that the service is running at {_get_base_url()}"
        )
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        preview = text[:200].replace("\n", " ")
        raise ValueError(
            f"OpenCode returned non-JSON content (HTTP {r.status_code}): {preview}. Error: {e}"
        ) from e


def _message_timeout() -> float:
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


def _extract_text_results(data: dict) -> list[str]:
    parts = data.get("parts") or []
    results: list[str] = []
    for part in parts:
        if part.get("type") != "text" or "text" not in part:
            continue
        text = (part.get("text") or "").strip()
        if text:
            results.append(text)
    return results


def _message_id(msg: dict) -> str:
    info = msg.get("info") or {}
    return str(info.get("id") or msg.get("id") or "")


def _message_role(msg: dict) -> str:
    info = msg.get("info") or {}
    return str(info.get("role") or msg.get("role") or "").lower()


def _is_user_message(msg: dict) -> bool:
    return _message_role(msg) == "user"


async def health() -> dict:
    async with httpx.AsyncClient(
        base_url=_get_base_url(), auth=_auth(), timeout=10.0
    ) as client:
        r = await client.get("/global/health")
        r.raise_for_status()
        return _parse_json(r)


async def list_sessions() -> list:
    async with httpx.AsyncClient(
        base_url=_get_base_url(), auth=_auth(), timeout=10.0
    ) as client:
        r = await client.get("/session")
        r.raise_for_status()
        return _parse_json(r)


async def create_session(title: Optional[str] = None) -> dict:
    async with httpx.AsyncClient(
        base_url=_get_base_url(), auth=_auth(), timeout=10.0
    ) as client:
        r = await client.post("/session", json={"title": title} if title else {})
        r.raise_for_status()
        return _parse_json(r)


async def _get_messages(session_id: str, limit: int = 5) -> list:
    async with httpx.AsyncClient(
        base_url=_get_base_url(), auth=_auth(), timeout=15.0
    ) as client:
        r = await client.get(f"/session/{session_id}/message", params={"limit": limit})
        r.raise_for_status()
        return _parse_json(r)


async def get_session_messages(session_id: str, limit: int = 500) -> list:
    return await _get_messages(session_id, limit=limit)


async def send_message_async_poll(session_id: str, text: str) -> list[str]:
    timeout = _message_timeout()
    messages_before = await _get_messages(session_id, limit=50)
    seen_ids = {_message_id(m) for m in messages_before if _message_id(m)}

    async with httpx.AsyncClient(
        base_url=_get_base_url(), auth=_auth(), timeout=15.0
    ) as client:
        r = await client.post(
            f"/session/{session_id}/prompt_async",
            json={"parts": [{"type": "text", "text": text}]},
        )
        r.raise_for_status()

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        await asyncio.sleep(3)
        messages = await _get_messages(session_id, limit=50)
        for msg in messages:
            msg_id = _message_id(msg)
            if msg_id and msg_id in seen_ids:
                continue
            if _is_user_message(msg):
                if msg_id:
                    seen_ids.add(msg_id)
                continue
            results = _extract_text_results(msg)
            if len(results) == 1 and results[0] == text.strip():
                if msg_id:
                    seen_ids.add(msg_id)
                continue
            if results:
                return results
            if msg_id:
                seen_ids.add(msg_id)
    raise httpx.TimeoutException("polling OpenCode result timed out")


async def send_message(session_id: str, text: str) -> list[str]:
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
        return _extract_text_results(data)
