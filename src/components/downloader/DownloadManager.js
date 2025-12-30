import { bitable } from '@lark-base-open/js-sdk'
import { i18n } from '@/locales/i18n.js'
import EventEmitter from './EventEmitter.js'
import FileProcessor from './FileProcessor.js'
import BrowserDownloader from './BrowserDownloader.js'
import WebSocketDownloader from './WebSocketDownloader.js'

const $t = i18n.global.t

/**
 * 下载管理器
 * 职责:
 * - 统一的下载入口
 * - 根据配置选择下载策略
 * - 协调各个下载器模块
 * - 暴露事件监听接口
 */
class DownloadManager {
  /**
   * 基于表单配置初始化下载器
   * @param {Object} formData - 表单配置数据
   */
  constructor(formData) {
    this.config = { ...formData }
    this.oTable = null
    this.cellList = []

    // 初始化事件发射器
    this.emitter = new EventEmitter()

    // 初始化文件预处理器
    this.fileProcessor = new FileProcessor(this.config, this.emitter)

    // 初始化浏览器下载器
    this.browserDownloader = new BrowserDownloader(this.emitter, this.fileProcessor)

    // 初始化 WebSocket 下载器
    this.webSocketDownloader = new WebSocketDownloader(
      this.emitter,
      this.fileProcessor,
      this.browserDownloader
    )
  }

  /**
   * 判断当前是否需要通过 WebSocket 推送文件链接
   */
  _isWebSocketChannel() {
    return this.config.downloadChannel === 'websocket' || this.config.downloadChannel === 'websocket_auth'
  }

  /**
   * 注册进度事件监听器
   * @param {string} event - 事件名称
   * @param {Function} callback - 回调函数
   * @returns {DownloadManager} this
   */
  on(event, callback) {
    this.emitter.on(event, callback)
    return this
  }

  /**
   * 按通道选择下载策略并串行执行
   */
  async startDownload() {
    this.oTable = await bitable.base.getTableById(this.config.tableId)

    // 获取所有附件信息
    this.cellList = await this.fileProcessor.getCellsList(this.oTable)

    if (!this.cellList.length) {
      this.emitter.emit('info', $t('no_files_to_download_message'))
      this.emitter.emit('finshed')
      return ''
    }

    try {
      if (this._isWebSocketChannel()) {
        // 桌面端需要稳定的元信息(文件名/路径),维持原有批量预处理逻辑
        await this.fileProcessor.batchPrepareAllFiles(this.cellList, this.oTable)
        await this.webSocketDownloader.download(this.cellList, this.config, this.oTable)
      } else {
        // 浏览器下载:按需准备(改名/分目录/唯一名),做到边获取边下载
        await this.browserDownloader.download(this.cellList, this.config, this.oTable)
      }
    } catch (error) {
      console.error('download failed', error)
      const message = error?.message || $t('file_download_failed')
      this.emitter.emit('warn', message)
    } finally {
      this.emitter.emit('finshed')
    }
  }

  /**
   * 清理资源
   */
  destroy() {
    this.emitter.clear()
    this.fileProcessor.clearCache()
    this.cellList = []
    this.oTable = null
  }
}

export default DownloadManager
