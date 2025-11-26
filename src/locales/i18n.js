import { createI18n } from 'vue-i18n'
import en from './en.json'
import zh from './zh.json'
import ja from './ja.json'
import zhTw from './zh-TW.json'
import es from './es.json'
import ru from './ru.json'

import { bitable } from '@lark-base-open/js-sdk'

const messages = {
  en,
  zh,
  ja,
  'zh-TW': zhTw,
  es,
  ru
}

/**
 * 统一语言代码，兼容形如 zh-TW、es-ES 的返回值并回落到已支持的语言。
 * @param {string} lang 来自外部的语言代码
 * @returns {string} i18n 可用的语言键
 */
const normalizeLang = (lang) => {
  if (!lang) {
    return 'zh'
  }
  const lowerLang = lang.toLowerCase()
  const direct = Object.keys(messages).find((key) => key.toLowerCase() === lowerLang)
  if (direct) {
    return direct
  }
  const base = lowerLang.split(/[-_]/)[0]
  const baseMatch = Object.keys(messages).find(
    (key) => key.toLowerCase().split(/[-_]/)[0] === base
  )
  return baseMatch || 'zh'
}

export const i18n = createI18n({
  locale: 'zh',
  allowComposition: true, // 占位符支持
  fallbackLocale: 'en',
  messages
})

bitable.bridge.getLanguage().then((lang) => {
  i18n.global.locale = normalizeLang(lang)
})

