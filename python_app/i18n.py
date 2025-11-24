"""
简单国际化工具，支持桌面程序的多语言界面。
"""
from dataclasses import dataclass

TRANSLATIONS = {
  'zh': {
    'title': '飞书附件下载桌面端',
    'language_label': '界面语言',
    'server_config': '服务配置',
    'stats_title': '下载状态',
    'host': '主机',
    'port': '端口',
    'output_dir': '保存目录',
    'browse': '选择…',
    'advanced_settings': '高级设置',
    'advanced_settings_desc': '如需自定义本地客户端下载地址，请展开设置主机和端口。',
    'advanced_toggle_show': '展开高级设置',
    'advanced_toggle_hide': '收起高级设置',
    'btn_show_logs': '显示日志',
    'btn_hide_logs': '隐藏日志',
    'stat_connection_connected': '连接状态：已连接',
    'stat_connection_disconnected': '连接状态：未连接',
    'stat_current': '当前下载：{count}',
    'stat_completed': '已完成：{count}',
    'stat_pending': '待下载：{count}',
    'download_concurrency': 'Python下载并发',
    'msg_invalid_download_concurrency': 'Python下载并发数需在1-50之间',
    'btn_start': '启动服务',
    'btn_stop': '停止服务',
    'logs': '日志',
    'status_idle': '状态：空闲',
    'status_running': '状态：运行中 ws://{host}:{port}',
    'status_stopped': '状态：已停止',
    'dialog_info_title': '提示',
    'dialog_error_title': '错误',
    'dialog_confirm_title': '确认',
    'msg_server_running': '服务已经在运行。',
    'msg_invalid_port': '端口必须为整数。',
    'msg_start_failed': '启动失败：{error}',
    'msg_stop_failed': '停止失败：{error}',
    'msg_exit_running': '服务仍在运行，确定停止并退出吗？',
    'language_option_zh': '简体中文',
    'language_option_en': 'English'
  },
  'en': {
    'title': 'Feishu Attachment Downloader',
    'language_label': 'Language',
    'server_config': 'Server Configuration',
    'stats_title': 'Download Status',
    'host': 'Host',
    'port': 'Port',
    'output_dir': 'Output Directory',
    'browse': 'Browse…',
    'advanced_settings': 'Advanced Settings',
    'advanced_settings_desc': 'Expand to customize the local client host and port.',
    'advanced_toggle_show': 'Show Advanced Settings',
    'advanced_toggle_hide': 'Hide Advanced Settings',
    'btn_show_logs': 'Show Logs',
    'btn_hide_logs': 'Hide Logs',
    'stat_connection_connected': 'Connection: Connected',
    'stat_connection_disconnected': 'Connection: Disconnected',
    'stat_current': 'Downloading: {count}',
    'stat_completed': 'Completed: {count}',
    'stat_pending': 'Pending: {count}',
    'download_concurrency': 'Python Download Concurrency',
    'msg_invalid_download_concurrency': 'Python download concurrency must be between 1 and 50.',
    'btn_start': 'Start Server',
    'btn_stop': 'Stop Server',
    'logs': 'Logs',
    'status_idle': 'Status: Idle',
    'status_running': 'Status: Running ws://{host}:{port}',
    'status_stopped': 'Status: Stopped',
    'dialog_info_title': 'Info',
    'dialog_error_title': 'Error',
    'dialog_confirm_title': 'Confirm',
    'msg_server_running': 'Server is already running.',
    'msg_invalid_port': 'Port must be an integer.',
    'msg_start_failed': 'Failed to start: {error}',
    'msg_stop_failed': 'Failed to stop: {error}',
    'msg_exit_running': 'Server is running. Stop and exit?',
    'language_option_zh': '简体中文',
    'language_option_en': 'English'
  }
}

SUPPORTED_LANGUAGES = [
  ('简体中文', 'zh'),
  ('English', 'en')
]

DEFAULT_LANGUAGE = 'zh'


@dataclass
class Localizer:
  """简单的多语言文本提供器。"""

  locale: str = DEFAULT_LANGUAGE

  def set_locale(self, locale: str) -> None:
    """更新当前语言。"""
    if locale in TRANSLATIONS:
      self.locale = locale
    else:
      self.locale = DEFAULT_LANGUAGE

  def translate(self, key: str, **kwargs) -> str:
    """按 key 获取文本并执行格式化。"""
    template = TRANSLATIONS.get(self.locale, {}).get(
      key,
      TRANSLATIONS[DEFAULT_LANGUAGE].get(key, key)
    )
    try:
      return template.format(**kwargs)
    except Exception:
      return template
