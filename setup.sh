#!/usr/bin/env bash
# 安装依赖并添加开机自启（systemd 用户服务）
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

SERVICE_NAME="opencodebot"
UNIT_DIR="$HOME/.config/systemd/user"
UNIT_FILE="$UNIT_DIR/${SERVICE_NAME}.service"
VENV_DIR="$SCRIPT_DIR/.venv"
VENV_PYTHON="$VENV_DIR/bin/python"
PYTHON="$(command -v python3 || true)"

echo "请选择操作:"
echo "  1) 安装/配置开机自启（首次或重写 unit）"
echo "  2) 更新（更新依赖并重启服务）"
echo "  3) 删除开机自启"
echo "  4) 退出"
read -r choice
echo ""

require_python() {
    [[ -n "$PYTHON" ]] && return
    echo "未找到 python3"
    exit 1
}

ensure_venv() {
    require_python
    if [[ ! -x "$VENV_PYTHON" ]]; then
        echo "创建 Python 虚拟环境: $VENV_DIR"
        if ! "$PYTHON" -m venv "$VENV_DIR"; then
            echo "创建 venv 失败。请先安装 python3-venv，例如:"
            echo "  sudo apt install python3-venv"
            exit 1
        fi
    fi
}

install_deps() {
    ensure_venv
    echo "安装/更新依赖 ..."
    "$VENV_PYTHON" -m pip install -q --upgrade pip setuptools wheel
    "$VENV_PYTHON" -m pip install -q -r requirements.txt
}

build_service_path() {
    local service_path=""
    local npm_prefix=""

    [[ -d "$HOME/.opencode/bin" ]] && service_path="$HOME/.opencode/bin:"
    if command -v npm &>/dev/null; then
        npm_prefix="$(npm config get prefix 2>/dev/null || true)"
        [[ -n "$npm_prefix" && -d "$npm_prefix/bin" ]] && service_path="${service_path}${npm_prefix}/bin:"
    fi
    service_path="${service_path}${HOME}/.local/bin:/usr/local/bin:/usr/bin:/bin"
    printf '%s' "$service_path"
}

maybe_enable_linger() {
    if ! command -v loginctl &>/dev/null; then
        return
    fi
    local linger
    linger="$(loginctl show-user "$USER" -p Linger 2>/dev/null | cut -d= -f2 || true)"
    if [[ "$linger" == "yes" ]]; then
        return
    fi
    echo ""
    echo "当前未启用 linger。若希望未登录时也能开机自启，请启用 linger。"
    echo "是否现在执行: sudo loginctl enable-linger $USER ? [y/N]"
    read -r ans
    if [[ "$ans" =~ ^[yY] ]]; then
        sudo loginctl enable-linger "$USER"
        echo "已启用 linger: $USER"
    else
        echo "可稍后手动执行: sudo loginctl enable-linger $USER"
    fi
}

write_unit() {
    local service_path opencode_path opencode_dir
    service_path="$(build_service_path)"
    opencode_path="$(PATH="$service_path" command -v opencode 2>/dev/null || true)"
    if [[ -z "$opencode_path" ]]; then
        echo "未找到 opencode（已按服务将使用的 PATH 检测）。请先安装:"
        echo "  curl -fsSL https://opencode.ai/install | bash"
        exit 1
    fi
    opencode_dir="$(dirname "$opencode_path")"
    service_path="${opencode_dir}:$service_path"
    echo "已找到 opencode，启动路径: $opencode_path"

    mkdir -p "$UNIT_DIR"
    cat > "$UNIT_FILE" << EOF
[Unit]
Description=OpenCode Bot (Telegram/Matrix)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$SCRIPT_DIR
Environment=PATH=$service_path
ExecStart=$VENV_PYTHON $SCRIPT_DIR/main.py
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
EOF
    echo "已写入: $UNIT_FILE"
}

case "$choice" in
    2)
        if [[ -d "$SCRIPT_DIR/.git" ]]; then
            echo "拉取代码 ..."
            git -C "$SCRIPT_DIR" pull
            echo ""
        fi
        install_deps
        write_unit
        systemctl --user daemon-reload
        systemctl --user restart "$SERVICE_NAME"
        systemctl --user status --no-pager "$SERVICE_NAME"
        echo ""
        echo "本次操作：更新（已拉取代码、更新依赖、更新 unit 并重启服务）"
        exit 0
        ;;
    3)
        systemctl --user stop "$SERVICE_NAME" 2>/dev/null || true
        systemctl --user disable "$SERVICE_NAME" 2>/dev/null || true
        [[ -f "$UNIT_FILE" ]] && rm -f "$UNIT_FILE" && echo "已删除 unit: $UNIT_FILE"
        systemctl --user daemon-reload
        echo "本次操作：已删除开机自启并停止服务"
        exit 0
        ;;
    4)
        exit 0
        ;;
    1|*)
        if [[ "$choice" != "1" ]]; then
            echo "已默认执行：安装/配置开机自启"
            echo ""
        fi
        ;;
esac

echo "项目目录: $SCRIPT_DIR"
install_deps

if [[ ! -f "config.json" ]]; then
    echo "未找到 config.json，请从 config.json.example 复制并填写后重试。"
    exit 1
fi

if [[ -f "$UNIT_FILE" ]]; then
    echo "检测到已存在开机自启服务，将更新 unit 并重载"
    INSTALL_ACTION="更新开机自启配置（已重写 unit 并启用）"
else
    INSTALL_ACTION="安装并启用开机自启"
fi

write_unit
systemctl --user daemon-reload
systemctl --user enable "$SERVICE_NAME"
echo "已启用开机自启: $SERVICE_NAME"
maybe_enable_linger

echo ""
echo "常用命令:"
echo "  启动:   systemctl --user start $SERVICE_NAME"
echo "  停止:   systemctl --user stop $SERVICE_NAME"
echo "  状态:   systemctl --user status $SERVICE_NAME"
echo "  日志:   journalctl --user -u $SERVICE_NAME -n 100 --no-pager"
echo "  取消自启: systemctl --user disable $SERVICE_NAME"
echo ""
echo "是否现在启动服务? [y/N]"
read -r ans
if [[ "$ans" =~ ^[yY] ]]; then
    systemctl --user start "$SERVICE_NAME"
    systemctl --user status --no-pager "$SERVICE_NAME"
fi
echo ""
echo "本次操作：$INSTALL_ACTION"
