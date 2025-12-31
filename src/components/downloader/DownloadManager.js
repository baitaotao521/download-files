import { bitable } from '@lark-base-open/js-sdk'
import { i18n } from '@/locales/i18n.js'
import EventEmitter from './EventEmitter.js'
import FileProcessor from './FileProcessor.js'
import BrowserDownloader from './BrowserDownloader.js'
import WebSocketDownloader from './WebSocketDownloader.js'
import UmamiTracker from './UmamiTracker.js'

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
    this.startTime = 0
    this.successCount = 0
    this.failedCount = 0

    // 初始化事件发射器
    this.emitter = new EventEmitter()

    // 初始化 Umami 统计追踪器
    this.umamiTracker = new UmamiTracker()

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

    // 绑定下载统计事件
    this._bindStatisticsEvents()
  }

  /**
   * 判断当前是否需要通过 WebSocket 推送文件链接
   */
  _isWebSocketChannel() {
    return this.config.downloadChannel === 'websocket' || this.config.downloadChannel === 'websocket_auth'
  }

  /**
   * 绑定下载统计事件监听
   */
  _bindStatisticsEvents() {
    // 监听下载进度 - 统计成功/失败数量
    this.emitter.on('progress', (progressInfo) => {
      if (progressInfo.percentage === 100) {
        this.successCount++
      }
    })

    this.emitter.on('error', () => {
      this.failedCount++
    })

    // 监听 ZIP 打包完成
    this.emitter.on('zip_progress', (payload) => {
      if (payload && typeof payload === 'object' && payload.stage === 'job_complete') {
        this.umamiTracker.trackZipProgress({
          stage: 'complete',
          fileCount: this.cellList.length
        })
      }
    })
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

    // 计算总大小
    const totalSize = this.cellList.reduce((sum, file) => sum + (file.size || 0), 0)

    // 统计用户配置
    this.umamiTracker.trackUserConfig({
      fileNameType: this.config.fileNameType,
      downloadTypeByFolders: this.config.downloadTypeByFolders,
      attachmentFieldsCount: this.config.attachmentFileds?.length || 0
    })

    // 统计下载开始
    this.umamiTracker.trackDownloadStart({
      downloadChannel: this.config.downloadChannel,
      downloadType: this.config.downloadType,
      fileCount: this.cellList.length,
      totalSize
    })

    this.startTime = Date.now()
    this.successCount = 0
    this.failedCount = 0

    try {
      if (this._isWebSocketChannel()) {
        // 桌面端需要稳定的元信息(文件名/路径),维持原有批量预处理逻辑
        await this.fileProcessor.batchPrepareAllFiles(this.cellList, this.oTable)

        // 统计 WebSocket 连接
        try {
          await this.webSocketDownloader.download(this.cellList, this.config, this.oTable)
          this.umamiTracker.trackWebSocketConnection({
            status: 'success',
            mode: this.config.downloadChannel === 'websocket_auth' ? 'token' : 'url'
          })
        } catch (wsError) {
          this.umamiTracker.trackWebSocketConnection({
            status: 'failed',
            mode: this.config.downloadChannel === 'websocket_auth' ? 'token' : 'url'
          })
          throw wsError
        }
      } else {
        // 浏览器下载:按需准备(改名/分目录/唯一名),做到边获取边下载
        await this.browserDownloader.download(this.cellList, this.config, this.oTable)
      }

      // 统计下载完成
      const duration = Date.now() - this.startTime
      this.umamiTracker.trackDownloadComplete({
        fileCount: this.cellList.length,
        successCount: this.successCount,
        failedCount: this.failedCount,
        duration
      })
    } catch (error) {
      console.error('download failed', error)
      const message = error?.message || $t('file_download_failed')
      this.emitter.emit('warn', message)

      // 统计下载失败
      this.umamiTracker.trackDownloadError({
        type: error?.name || 'unknown',
        message: error?.message || '未知错误',
        downloadMode: this.config.downloadChannel
      })
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
    this.browserDownloader.destroy()
    this.cellList = []
    this.oTable = null
  }
}

export default DownloadManager
