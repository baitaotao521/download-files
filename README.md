# Feishu Downloader · 飞书附件批量下载

配合飞书多维表格附件批量下载插件，把表格中的附件和网络链接批量保存到电脑。适合文件较多、文件较大，或需要按字段整理文件名与文件夹的场景，也支持导出带图片的 Excel 表格。

[插件安装与使用说明](https://p6bgwki4n6.feishu.cn/docx/Pn7Kdw2rPocwPZxVfF5cMsAcnle) · [下载最新稳定版](https://github.com/baitaotao521/download-files/releases/latest) · [反馈问题](https://github.com/baitaotao521/download-files/issues)

使用说明为飞书文档，打开时需要登录飞书账号。

## 下载客户端

选择与你的电脑系统和处理器匹配的版本。Windows 推荐安装器，macOS 使用 DMG，Debian/Ubuntu 推荐 DEB。

| 你的电脑 | 推荐下载 | 便携版 |
| --- | --- | --- |
| Windows，Intel / AMD 处理器 | [Windows x64 安装器](https://github.com/baitaotao521/download-files/releases/latest/download/feishu-downloader-setup-windows-x64.exe) | [ZIP](https://github.com/baitaotao521/download-files/releases/latest/download/feishu-downloader-windows-x64.zip) |
| Windows，ARM 处理器 | [Windows ARM64 安装器](https://github.com/baitaotao521/download-files/releases/latest/download/feishu-downloader-setup-windows-arm64.exe) | [ZIP](https://github.com/baitaotao521/download-files/releases/latest/download/feishu-downloader-windows-arm64.zip) |
| Mac，Apple 芯片（M 系列） | [macOS Apple Silicon DMG](https://github.com/baitaotao521/download-files/releases/latest/download/feishu-downloader-macos-arm64.dmg) | — |
| Mac，Intel 处理器 | [macOS Intel DMG](https://github.com/baitaotao521/download-files/releases/latest/download/feishu-downloader-macos-x64.dmg) | — |
| Linux，Intel / AMD 64 位处理器 | [Debian / Ubuntu DEB](https://github.com/baitaotao521/download-files/releases/latest/download/feishu-downloader-linux-x64.deb) | [tar.gz](https://github.com/baitaotao521/download-files/releases/latest/download/feishu-downloader-linux-x64.tar.gz) |

不确定选哪个？Mac 可在“关于本机”查看芯片或处理器；Windows 可在系统设置中查看“系统类型”。[全部版本与更新说明](https://github.com/baitaotao521/download-files/releases)中也能找到各平台安装包。

## 安装

**Windows**：运行安装器，按提示完成安装。安装器包含 Microsoft WebView2 的安装引导；使用 ZIP 便携版时，需要电脑已安装 WebView2 Runtime，解压后双击 `feishu-downloader.exe`。

**macOS**：打开 DMG，把 Feishu Downloader 拖入 Applications（应用程序），然后启动。首次打开若被系统拦截，可在“系统设置 → 隐私与安全性”中确认允许打开。

**Linux**：Debian/Ubuntu 可在下载目录执行：

```bash
sudo apt install ./feishu-downloader-linux-x64.deb
```

安装后从应用菜单启动。使用 tar.gz 便携版时，解压后启动其中的 `feishu-downloader`；系统需安装 GTK 3、WebKitGTK 4.1、libsoup 3 和 CA 证书。

当前 macOS 和 Windows 安装包尚未使用受信任的代码签名，系统可能显示安全提示。每个版本提供 `SHA256SUMS` 校验文件；安装前可按[对应版本的发布说明](https://github.com/baitaotao521/download-files/releases/latest)核对文件。

## 开始第一次下载

1. **打开客户端**，确认默认保存目录，并检查本地服务已就绪。下载期间保持客户端运行。
2. **在同一台电脑的飞书多维表格中打开插件**。尚未安装插件时，请按[使用说明](https://p6bgwki4n6.feishu.cn/docx/Pn7Kdw2rPocwPZxVfF5cMsAcnle)操作，或联系工作区管理员。
3. **选择数据表、视图和下载字段**：附件字段用于已有附件，URL 字段用于网络链接。需要分类整理时，可设置字段命名和文件夹层级。
4. **选择“本地客户端下载”**。首次使用普通客户端方式即可；默认连接地址为 `127.0.0.1:11548`。
5. **点击“下载所选记录”或“下载全部记录”**，核对预览后确认。建议先用少量记录检查文件名、目录和保存位置。
6. **在客户端查看任务进度**。完成后查看任务的输出目录；失败项可单独重试。

你需要拥有目标表格、记录和附件的读取权限。下载额度与会员权益可在飞书插件的“我的”页面查看。

## 可以怎样整理文件

- **批量下载**：下载附件及网络链接，无需逐个另存。
- **字段命名与文件夹分类**：用客户、项目、日期等字段组合文件名和目录层级。
- **ZIP 打包**：下载完成后压缩，便于交付或归档。
- **Excel 图片导出**：在插件中选择“表格照片内嵌模式”，选择导出字段并调整列顺序。客户端生成 XLSX，将图片嵌入表格，其他附件保存在“附件”目录。移动或分享结果时，请一并保留附件目录，避免表格中的附件链接失效。
- **进度与重试**：查看文件下载、图片下载和表格生成进度，取消任务或重试失败项。

普通的“本地客户端下载”方式需要保持插件打开。需要在关闭插件后继续下载飞书附件时，可选择“本地客户端下载（授权码）”或“本地客户端下载（开放平台鉴权）”：先在客户端配置相应凭证，待任务数据传输完成后再关闭插件。配置步骤见[完整使用说明](https://p6bgwki4n6.feishu.cn/docx/Pn7Kdw2rPocwPZxVfF5cMsAcnle)。

## 常见问题

**只安装客户端就能下载吗？**  
需要配合飞书多维表格中的插件使用。数据范围、下载字段和命名规则在插件中选择，客户端负责把文件保存到电脑。

**插件提示无法连接客户端怎么办？**  
确认客户端与飞书在同一台电脑上，客户端正在运行、本地服务已启动。检查插件连接设置是否为 `127.0.0.1:11548`；仍失败时，检查系统防火墙或安全软件是否拦截本机连接，并按插件提示更新客户端。

**文件保存在哪里？**  
查看客户端的默认保存目录和任务详情中的输出目录。修改目录后，请确认该目录存在、可写且磁盘空间充足。

**提示没有权限或下载额度不足怎么办？**  
表格读取权限请联系表格管理员；会员权益和剩余额度请在插件“我的”页面查看。

**部分文件失败怎么办？**  
查看失败提示，确认网络、磁盘空间和文件权限，再重试失败项。URL 下载还可能受目标网站登录要求或链接有效期限制。

## 获取帮助

[完整使用说明](https://p6bgwki4n6.feishu.cn/docx/Pn7Kdw2rPocwPZxVfF5cMsAcnle) · [版本更新说明](https://github.com/baitaotao521/download-files/releases) · [提交问题反馈](https://github.com/baitaotao521/download-files/issues/new)

反馈时请提供操作系统、客户端版本、下载方式、操作步骤和错误提示。截图与日志中请遮盖 Personal Base Token、App Secret 和其他凭证。
