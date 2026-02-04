"""
与协议无关的 OpenCode 控制逻辑，供 Telegram 与 Matrix 共用。
"""
from __future__ import annotations

import os

import httpx
import opencode_client as opencode
import opencode_runner as runner

MAX_MESSAGE_LENGTH = 4096
current_session_id: str | None = None
_last_opencode_cwd: str | None = None  # 上次启动/重启 opencode 时使用的目录，/restart 时用其恢复


async def get_or_create_session() -> str:
    global current_session_id
    if current_session_id:
        try:
            sessions = await opencode.list_sessions()
            ids = [s.get("id") for s in (sessions or []) if s.get("id")]
            if current_session_id in ids:
                return current_session_id
        except Exception:
            pass
        current_session_id = None
    sessions = await opencode.list_sessions()
    if not sessions:
        session = await opencode.create_session()
        current_session_id = session["id"]
    else:
        current_session_id = sessions[0]["id"]
    return current_session_id


def switch_session(session_id: str) -> None:
    global current_session_id
    current_session_id = session_id


def set_last_opencode_cwd(cwd: str) -> None:
    """记录上次启动 opencode 的目录，供 /restart 使用。"""
    global _last_opencode_cwd
    _last_opencode_cwd = cwd


def strip_leading_for_command(s: str) -> str:
    """去掉首位的空格与不可见字符，用于判断首个可见字符是否为 /。"""
    s = (s or "").lstrip()
    while s and not s[0].isprintable():
        s = s[1:]
    return s


def chunk_text(text: str, size: int = MAX_MESSAGE_LENGTH) -> list[str]:
    if len(text) <= size:
        return [text] if text else []
    out = []
    for i in range(0, len(text), size):
        out.append(text[i : i + size])
    return out


async def get_sessions() -> list[dict]:
    return await opencode.list_sessions()


def _format_session_messages(messages: list) -> str:
    """将 session 消息列表格式化为 Markdown（用于导出 .md 文件）。"""
    blocks = []
    for i, msg in enumerate(messages or []):
        parts = msg.get("parts") or []
        blocks.append(f"## Message {i + 1}\n")
        for p in parts:
            if p.get("type") == "text" and "text" in p:
                text = (p.get("text") or "").strip()
                if text:
                    blocks.append(text)
                    blocks.append("")
        blocks.append("")
    return "\n".join(blocks).strip() or "(无内容)"


async def handle_export_session() -> tuple[bytes | None, str]:
    """
    获取当前 session 全部内容并格式化为 Markdown 文件。
    返回 (content_bytes, filename) 成功；(None, error_message) 失败。
    """
    try:
        session_id = await get_or_create_session()
        messages = await opencode.get_session_messages(session_id, limit=500)
        text = _format_session_messages(messages)
        filename = f"session_{session_id[:8]}.md"
        return (text.encode("utf-8"), filename)
    except Exception as e:
        return (None, f"导出失败: {e}")


def handle_start() -> str:
    return (
        "直接发消息即会转发给 OpenCode 执行，仅回复最终结果。"
        " /session 查看会话，/new 新建会话，/newproj 新建项目目录，/opencode 查看并启动 OpenCode。"
    )


async def handle_session_list() -> str:
    try:
        sessions = await opencode.list_sessions()
    except Exception as e:
        return f"获取会话失败: {e}"
    if not sessions:
        return "当前无会话，发送任意消息将自动创建。"
    lines = []
    for s in sessions:
        sid = s.get("id", "")
        title = s.get("title") or "(无标题)"
        mark = " [当前]" if sid == current_session_id else ""
        lines.append(f"• {sid[:8]}… {title}{mark}")
    return "会话列表（点击下方按钮切换当前会话）:\n" + "\n".join(lines)


def _validate_proj_subdir(name: str) -> str | None:
    """校验 /newproj xxxx 的 xxxx：仅允许可见字符、无路径成分。返回错误说明或 None 表示通过。"""
    if not name or len(name) > 64:
        return "子目录名长度须 1～64"
    for c in name:
        if c in "/\\\0\t\n\r" or ord(c) < 32:
            return "子目录名不可含不可见字符或路径符号"
    if name.startswith(".") or ".." in name:
        return "子目录名不可含 .. 或以 . 开头"
    return None


async def handle_new_session() -> str:
    """/new：仅新建 session，不重启。"""
    global current_session_id
    try:
        session = await opencode.create_session()
        current_session_id = session["id"]
        return "已切换到新会话。"
    except Exception as e:
        return f"创建会话失败: {e}"


async def handle_new_project(
    subdir: str | None = None,
    log_path: str | None = None,
) -> str:
    """
    /newproj：用日期目录 ~/bots/年-月-日 重启并新建 session。
    /newproj xxxx：用 ~/bots/xxxx 重启并新建 session。
    """
    global current_session_id, _last_opencode_cwd
    if subdir is not None:
        err = _validate_proj_subdir(subdir)
        if err:
            return err
        cwd = os.path.expanduser("~/bots/" + subdir.strip())
    else:
        cwd = runner._default_cwd()
    ok, msg = runner.restart_opencode(log_path=log_path, cwd=cwd)
    if not ok:
        return f"重启 OpenCode 失败: {msg}"
    _last_opencode_cwd = cwd
    current_session_id = None
    try:
        session = await opencode.create_session()
        current_session_id = session["id"]
        return f"已切换到新项目目录并新建会话: {cwd}"
    except Exception as e:
        return f"创建会话失败: {e}"


def handle_opencode_status() -> str:
    base = runner.get_base_url()
    port = runner._parse_port_from_base_url(base)
    if port in (80, 443):
        port = runner.DEFAULT_PORT
    in_use, pid, cmd = runner.check_port(port)
    healthy = runner.is_opencode_healthy()
    lines = [
        f"端口: {port}",
        f"占用: {'是' if in_use else '否'}",
        f"健康: {'是' if healthy else '否'}",
    ]
    if pid:
        lines.append(f"进程: pid={pid}")
    if cmd:
        lines.append(f"命令: {cmd}")
    return "OpenCode 状态:\n" + "\n".join(lines)


def is_opencode_healthy() -> bool:
    return runner.is_opencode_healthy()


def handle_start_opencode(log_path: str) -> tuple[bool, str]:
    global _last_opencode_cwd
    ok, msg = runner.ensure_opencode_running(log_path=log_path)
    if ok and _last_opencode_cwd is None:
        _last_opencode_cwd = runner._default_cwd()
    return ok, msg


async def handle_restart_opencode(log_path: str) -> tuple[bool, str]:
    """用上次的目录重启 OpenCode，并将当前 session 设为该目录下最近的一个。"""
    global current_session_id, _last_opencode_cwd
    cwd = _last_opencode_cwd or runner._default_cwd()
    _last_opencode_cwd = cwd
    ok, msg = runner.restart_opencode(log_path=log_path, cwd=cwd)
    if not ok:
        return ok, msg
    current_session_id = None
    try:
        sessions = await opencode.list_sessions()
        if sessions:
            def sort_key(s: dict) -> tuple:
                t = s.get("time") or ""
                return (1 if t else 0, t)
            sessions = sorted(sessions, key=sort_key, reverse=True)
            current_session_id = sessions[0].get("id")
    except Exception:
        pass
    return ok, msg


async def handle_switch_session(session_id: str) -> str:
    try:
        sessions = await opencode.list_sessions()
        title = "(无标题)"
        for s in sessions:
            if s.get("id") == session_id:
                title = s.get("title") or title
                break
        switch_session(session_id)
        return f"已切换到会话: {title}"
    except Exception as e:
        return f"切换失败: {e}"


async def handle_message(text: str) -> str:
    try:
        session_id = await get_or_create_session()
        result = await opencode.send_message(session_id, text)
    except httpx.TimeoutException:
        return "请求超时（OpenCode 可能仍在执行），可稍后重试或发 /session 查看。可设置环境变量 OPENCODE_MESSAGE_TIMEOUT（秒）增大超时。"
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            global current_session_id
            current_session_id = None
            try:
                session_id = await get_or_create_session()
                result = await opencode.send_message(session_id, text)
            except Exception as retry_e:
                return f"调用 OpenCode 失败: {retry_e}"
            if not result:
                return "(无文本结果)"
            return result
        return f"调用 OpenCode 失败: {e}"
    except Exception as e:
        return f"调用 OpenCode 失败: {e}"
    if not result:
        return "(无文本结果)"
    return result
