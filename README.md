附件批量下载

## WebSocket 下载服务

如果在前端插件中选择“WebSocket 推送下载”，需要先在本地启动 Python 服务。

### 安装依赖

```bash
pip install -r scripts/requirements.txt
```

> 注：桌面程序依赖系统自带的 Tk，macOS / Windows 默认已提供；Linux 发行版如缺少可通过 `sudo apt install python3-tk` 等方式安装。

### 命令行服务（原 CLI 脚本）

```bash
python scripts/ws_downloader.py \
  --host 127.0.0.1 \
  --port 11548 \
  --output ./downloads \
  --download-concurrency 10
```

所有参数均可省略以使用默认值。终端按 `Ctrl+C` 即可退出服务。

可选参数说明：

- `--host`：服务监听地址，默认 `127.0.0.1`。可改为 `0.0.0.0` 让局域网内其他设备访问。
- `--port`：WebSocket 端口，默认 `11548`。若被占用可指定其他端口，并在前端“高级设置”中同步修改。
- `--output`：文件保存目录，默认 `./downloads`。相对路径会以当前工作目录为基准。
- `--log-level`：日志级别，可选 `DEBUG/INFO/WARNING/ERROR`，默认 `INFO`。
- `--download-concurrency`：Python 端下载并发数，默认 `5`。不建议设置过大以免触发限流。
- `--http-connect-timeout`：HTTP 连接超时秒数，默认 `30`。
- `--download-read-timeout`：下载读取超时秒数（超过该时间未收到数据将超时），默认 `3600`；设置为 `0` 表示不限制。

### 桌面程序

```bash
python scripts/ws_desktop.py
```

桌面程序提供启动/停止按钮、配置输入（主机、端口、保存目录）与实时日志，并内置中英文界面切换（默认简体中文），适合在 macOS / Windows / Linux 上运行。
> 最新界面中，主机/端口位于“高级设置”折叠面板，日志默认隐藏，可在状态卡片中实时查看“已连接/未连接”“当前下载/已完成/待下载”数量。

### 前端插件配置

1. 在插件表单中将“下载执行方式”切换为“本地客户端下载”。
2. 展开“高级设置”后填写 Python 服务监听的主机和端口（默认为 `127.0.0.1:11548`）。
3. 点击下载后，前端会通过 WebSocket 推送附件元信息（token/字段/记录/文件名/路径等），由本地 Python 端按需向前端请求临时下载链接并落地保存/打包（下载链接有效期约 10 分钟，服务端遇到 `HTTP 400` 会自动触发刷新）。

### 授权码 + 本地客户端下载模式

新增的“本地客户端下载（授权码）”会将附件 token、字段与记录信息发送给桌面端，由 Python 通过 Base OpenSDK 拉取文件：

1. 确保执行 `pip install -r scripts/requirements.txt` 安装 `baseopensdk` 及 `python-dotenv`，并在 `.env` 或桌面程序的高级设置中填入 `PERSONAL_BASE_TOKEN`。
2. 前端选择该下载方式后，会自动携带当前 Base 的 `appToken` 与数据表 ID。若桌面端未配置授权码，将返回明确错误并拒绝执行下载。

---

插件在下载过程中会按以下顺序向 Python 服务推送 JSON：

1. `feishu_attachment_config`：包含并发数、是否打包、任务名称等关键信息。服务端只有收到该配置才会接受后续文件消息。
2. `feishu_attachment_link`：携带每个附件的 token/字段/记录信息、命名及分类路径（`downloadUrl` 可为空）。Python 端会在需要下载时向前端请求临时链接。
3. `feishu_attachment_refresh`：当 Python 端返回 `feishu_attachment_ack.status=refresh` 时，前端应回传 `{ order, downloadUrl }`，用于刷新临时下载链接（或回传 `{ order, error }`）。
4. `feishu_attachment_complete`：通知 Python 端开始汇总；若配置了“打包下载”，此时会生成 ZIP 并回传完成状态。

所有阶段的结果（单文件成功/失败、打包完成等）都会通过 `feishu_attachment_ack` 返回给前端，方便 UI 实时展示。
