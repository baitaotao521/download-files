# Feishu Downloader

飞书多维表格附件批量下载桌面客户端，支持 URL、Personal Base Token、Open API 下载与带图片的 XLSX 导出。

本仓库用于分发桌面安装包、发布说明和校验文件；开发源码在私有仓库维护。

## 下载最新稳定版

[全部版本与发布说明](https://github.com/baitaotao521/download-files/releases) · [最新稳定版](https://github.com/baitaotao521/download-files/releases/latest)

| 平台 | 安装包 | 便携包 |
| --- | --- | --- |
| macOS Apple Silicon | [DMG](https://github.com/baitaotao521/download-files/releases/latest/download/feishu-downloader-macos-arm64.dmg) | — |
| macOS Intel | [DMG](https://github.com/baitaotao521/download-files/releases/latest/download/feishu-downloader-macos-x64.dmg) | — |
| Windows x64 | [安装器](https://github.com/baitaotao521/download-files/releases/latest/download/feishu-downloader-setup-windows-x64.exe) | [ZIP](https://github.com/baitaotao521/download-files/releases/latest/download/feishu-downloader-windows-x64.zip) |
| Windows ARM64 | [安装器](https://github.com/baitaotao521/download-files/releases/latest/download/feishu-downloader-setup-windows-arm64.exe) | [ZIP](https://github.com/baitaotao521/download-files/releases/latest/download/feishu-downloader-windows-arm64.zip) |
| Linux x64 | [DEB](https://github.com/baitaotao521/download-files/releases/latest/download/feishu-downloader-linux-x64.deb) | [tar.gz](https://github.com/baitaotao521/download-files/releases/latest/download/feishu-downloader-linux-x64.tar.gz) |

每个版本附带 `SHA256SUMS` 和 `release-metadata.json`，用于核对下载文件与构建身份。请阅读对应 Release 的安装说明和系统要求。

当前安装包未使用受信任的代码签名；macOS 和 Windows 可能显示系统安全提示。Windows 需要 WebView2 Runtime，Linux 需要 GTK 3、WebKitGTK 4.1 与 libsoup 3。
