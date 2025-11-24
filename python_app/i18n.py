"""
简单国际化工具，支持桌面程序的多语言界面。
"""
from dataclasses import dataclass

TRANSLATIONS = {
  'zh': {
    'title': '飞书附件下载桌面端',
    'language_label': '界面语言',
    'server_config': '服务配置',
    'host': '主机',
    'port': '端口',
    'output_dir': '保存目录',
    'browse': '选择…',
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
    'host': 'Host',
    'port': 'Port',
    'output_dir': 'Output Directory',
    'browse': 'Browse…',
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
