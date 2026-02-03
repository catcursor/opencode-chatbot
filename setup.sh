#!/usr/bin/env bash
# 安装依赖并添加开机自启（systemd 用户服务）
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
SERVICE_NAME="opencodebot"
VENV_BIN="$SCRIPT_DIR/venv/bin"
UNIT_DIR="$HOME/.config/systemd/user"
UNIT_FILE="$UNIT_DIR/${SERVICE_NAME}.service"

echo "请选择操作:"
echo "  1) 安装/配置开机自启（首次或重写 unit）"
echo "  2) 更新（更新依赖并重启服务）"
echo "  3) 删除开机自启"
echo "  4) 退出"
read -r choice
echo ""

case "$choice" in
    2)
        [[ ! -d "$SCRIPT_DIR/venv" ]] && { echo "未找到 venv，请先选择 1 完成安装"; exit 1; }
        if [[ -d "$SCRIPT_DIR/.git" ]]; then
            echo "拉取代码 ..."
            git -C "$SCRIPT_DIR" pull
            echo ""
        fi
        echo "更新依赖并重启服务 ..."
        "$VENV_BIN/pip" install -q -r requirements.txt
        systemctl --user daemon-reload
        systemctl --user restart "$SERVICE_NAME"
        systemctl --user status --no-pager "$SERVICE_NAME"
        echo ""
        echo "本次操作：更新（已拉取代码、更新依赖并重启服务）"
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

# 1. 检查/创建 venv 并安装依赖
if [[ ! -d "venv" ]]; then
    echo "创建虚拟环境 venv ..."
    python3 -m venv venv
fi
echo "安装依赖 ..."
"$VENV_BIN/pip" install -q -r requirements.txt

# 2. 检查 config
if [[ ! -f "config.json" ]]; then
    echo "未找到 config.json，请从 config.json.example 复制并填写后重试。"
    exit 1
fi

# 3. 生成并安装 systemd 用户服务
mkdir -p "$UNIT_DIR"
# 保证 systemd 启动时能找到 opencode（npm -g 在 npm prefix/bin，pip --user 在 ~/.local/bin）
EXTRA_PATH=""
if command -v npm &>/dev/null; then
    NPM_PREFIX="$(npm config get prefix 2>/dev/null)"
    [[ -n "$NPM_PREFIX" && -d "${NPM_PREFIX}/bin" ]] && EXTRA_PATH="${NPM_PREFIX}/bin:"
fi
EXTRA_PATH="${EXTRA_PATH}${HOME}/.local/bin:"
SERVICE_PATH="${EXTRA_PATH}/usr/local/bin:/usr/bin:/bin"

# 用与 systemd 服务相同的 PATH 检测 opencode，避免开机后找不到命令
OPENCODE_PATH="$(PATH="$SERVICE_PATH" command -v opencode 2>/dev/null)"
if [[ -z "$OPENCODE_PATH" ]]; then
    echo "未找到 opencode（已按服务将使用的 PATH 检测）。请先安装:"
    echo "  curl -fsSL https://opencode.ai/install | bash"
    exit 1
fi
OPENCODE_DIR="$(dirname "$OPENCODE_PATH")"
echo "已找到 opencode，启动路径: $OPENCODE_PATH"

# 检测是否已有开机自启服务，有则更新
if [[ -f "$UNIT_FILE" ]]; then
    echo "检测到已存在开机自启服务，将更新 unit 并重载"
    INSTALL_ACTION="更新开机自启配置（已重写 unit 并启用）"
else
    INSTALL_ACTION="安装并启用开机自启"
fi

# 将找到的 opencode 所在目录置于 PATH 最前，确保服务使用该路径
cat > "$UNIT_FILE" << EOF
[Unit]
Description=OpenCode Bot (Telegram/Matrix)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$SCRIPT_DIR
Environment=PATH=${OPENCODE_DIR}:${EXTRA_PATH}/usr/local/bin:/usr/bin:/bin
ExecStart=$VENV_BIN/python $SCRIPT_DIR/main.py
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
EOF

echo "已写入: $UNIT_FILE"

# 4. 重载并启用
systemctl --user daemon-reload
systemctl --user enable "$SERVICE_NAME"
echo "已启用开机自启: $SERVICE_NAME"

echo ""
echo "常用命令:"
echo "  启动:   systemctl --user start $SERVICE_NAME"
echo "  停止:   systemctl --user stop $SERVICE_NAME"
echo "  状态:   systemctl --user status $SERVICE_NAME"
echo "  取消自启: systemctl --user disable $SERVICE_NAME"
echo ""
echo "若需在未登录时也开机自启，执行: sudo loginctl enable-linger \$USER"
echo ""
echo "是否现在启动服务? [y/N]"
read -r ans
if [[ "$ans" =~ ^[yY] ]]; then
    systemctl --user start "$SERVICE_NAME"
    systemctl --user status --no-pager "$SERVICE_NAME"
fi
echo ""
echo "本次操作：$INSTALL_ACTION"
