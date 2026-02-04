# opencode-chatbot

用 Telegram 或 Matrix Bot 控制本地 [OpenCode](https://opencode.ai)（发消息、切会话、查状态、可选启动 opencode serve）。

- 仓库：<https://github.com/catcursor/opencode-chatbot>
- 依赖：Python 3，`opencode serve` 已安装且在 PATH

## 配置

1. 复制 `config.json.example` 为 `config.json`
2. **Telegram**：填写 `telegram_token`（Bot Token）和 `allowed_chat_ids`（留空则所有人可用）
3. **Matrix**（可选）：填写 `matrix_homeserver`、`matrix_user_id`（@bot:domain）、`matrix_password`（**仅首次登录**；成功后程序会删除该字段并仅用 token 文件登录）。`allowed_room_ids` 留空即不限制房间。E2EE 与 token 存于 `matrix_store/`、`matrix_credentials.json`，不提交。

## 运行

```bash
pip install -r requirements.txt
python main.py
```

仅 Telegram 时也可 `python telegram_bot.py`；仅 Matrix 时 `python matrix_bot.py`。

需先启动 `opencode serve`（默认 `http://127.0.0.1:4096`），或发送 `/opencode` 点「启动 OpenCode」。

**长任务超时**：发消息给 OpenCode 时，默认等待 10 分钟；超时后提示「请求超时（OpenCode 可能仍在执行）」。可设置环境变量 `OPENCODE_MESSAGE_TIMEOUT`（秒）增大超时；或设置 `OPENCODE_USE_ASYNC=1` 使用异步提交+轮询，避免单次长连接超时。

## 开机自启（Linux systemd）

在项目目录执行 `./setup.sh`，按提示选择：

- **1** 安装/配置开机自启（创建 venv、安装依赖、检测 opencode、写入用户级 systemd 服务并 enable）
- **2** 更新（git pull、更新依赖、重启服务）
- **3** 删除开机自启并停止服务
- **4** 退出

未安装 opencode 时会提示使用：`curl -fsSL https://opencode.ai/install | bash`。若需在未登录时也开机自启，执行：`sudo loginctl enable-linger $USER`。

## 命令

首字符为 `/` 会当作命令处理（会先去掉首部空格与不可见字符再判断）；未知命令回复「命令不存在」，不会当普通内容发给 OpenCode。

- `/start` 说明与欢迎
- `/session` 会话列表（Telegram 可点按钮切换；Matrix 用 `/use <session_id>` 切换）
- `/new` 新建会话（不换目录、不重启）
- `/newproj` 新建项目目录：用**日期目录** `~/bots/年-月-日` 重启 OpenCode 并新建会话
- `/newproj <名>` 新建项目目录：用 `~/bots/<名>` 重启并新建会话（`<名>` 仅允许可见字符、无路径符号，1～64 字）
- `/export` 导出当前会话全部内容为 .md 文件
- `/restart` 用**上次使用的目录**重启 OpenCode，并自动选该目录下最近的会话
- `/opencode` 查看/启动 OpenCode
- `/use <session_id>`（Matrix）切换当前会话

**目录**：首次启动或未设置时使用 `~/bots/年-月-日`；可通过环境变量 `OPENCODE_CWD` 覆盖默认目录。`/newproj` 或 `/newproj <名>` 会记录「上次目录」，`/restart` 会回到该目录。

