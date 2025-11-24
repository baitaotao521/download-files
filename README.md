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

### 桌面程序

```bash
python scripts/ws_desktop.py
```

桌面程序提供启动/停止按钮、配置输入（主机、端口、保存目录）与实时日志，并内置中英文界面切换（默认简体中文），适合在 macOS / Windows / Linux 上运行。

### 前端插件配置

1. 在插件表单中将“下载执行方式”切换为“WebSocket 推送至 Python 服务”。
2. 填写 Python 服务监听的主机和端口（默认为 `127.0.0.1:11548`）。
3. 点击下载后，前端会通过 WebSocket 依次推送附件临时链接，由本地 Python 端负责落地保存/打包。

---

插件在下载过程中会按以下顺序向 Python 服务推送 JSON：

1. `feishu_attachment_config`：包含并发数、是否打包、任务名称等关键信息。服务端只有收到该配置才会接受后续文件消息。
2. `feishu_attachment_link`：携带每个附件的临时下载链接、命名及分类路径。Python 端会基于该信息执行并发下载。
3. `feishu_attachment_complete`：通知 Python 端开始汇总；若配置了“打包下载”，此时会生成 ZIP 并回传完成状态。

所有阶段的结果（单文件成功/失败、打包完成等）都会通过 `feishu_attachment_ack` 返回给前端，方便 UI 实时展示。
