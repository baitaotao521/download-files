"""
简单国际化工具，支持桌面程序的多语言界面。
"""
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Dict

LOCALES_DIR = Path(__file__).with_name('locales')
TRANSLATION_FILES = {
  'zh': 'zh.json',
  'en': 'en.json',
  'ja': 'ja.json'
}


def _load_translations() -> Dict[str, Dict[str, str]]:
  """从 JSON 文件中加载全部语言映射。"""
  translations: Dict[str, Dict[str, str]] = {}
  for locale, file_name in TRANSLATION_FILES.items():
    file_path = LOCALES_DIR / file_name
    try:
      data = json.loads(file_path.read_text(encoding='utf-8'))
    except FileNotFoundError:
      data = {}
    except json.JSONDecodeError:
      data = {}
    translations[locale] = data
  return translations


TRANSLATIONS = _load_translations()

SUPPORTED_LANGUAGES = [
  ('简体中文', 'zh'),
  ('English', 'en'),
  ('日本語', 'ja')
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
      TRANSLATIONS.get(DEFAULT_LANGUAGE, {}).get(key, key)
    )
    try:
      return template.format(**kwargs)
    except Exception:
      return template
