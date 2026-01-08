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
    this.isCancelled = false
    this.cancelReason = ''
    this.isDownloading = false

    // 初始化事件发射器
    this.emitter = new EventEmitter()

    // 初始化 Umami 统计追踪器
    this.umamiTracker = new UmamiTracker()

    // 初始化文件预处理器
    this.fileProcessor = new FileProcessor(this.config, this.emitter)

    // 初始化浏览器下载器
    this.browserDownloader = new BrowserDownloader(
      this.emitter,
      this.fileProcessor,
      this.umamiTracker,
      this.config.downloadChannel
    )

    // 初始化 WebSocket 下载器
    this.webSocketDownloader = new WebSocketDownloader(
      this.emitter,
      this.fileProcessor,
      this.browserDownloader,
      this.umamiTracker,
      this.config.downloadChannel
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

      // 实时更新下载速度（用于性能统计）
      const { size, percentage } = progressInfo
      if (size && percentage !== undefined && this.startTime > 0) {
        const now = Date.now()
        const elapsedSeconds = (now - this.startTime) / 1000

        if (elapsedSeconds > 0 && percentage > 0) {
          const downloadedBytes = size * (percentage / 100)
          const speedMBps = (downloadedBytes / elapsedSeconds) / (1024 * 1024)

          // 更新 Umami 追踪器的速度统计
          this.umamiTracker.updateSpeed(speedMBps)
        }
      }
    })

    this.emitter.on('error', () => {
      this.failedCount++
    })

    // 监听 ZIP 打包完成
    this.emitter.on('zip_progress', (payload) => {
      if (payload && typeof payload === 'object' && payload.stage === 'job_complete') {
        const totalSize = this.cellList.reduce((sum, file) => sum + (file.size || 0), 0)
        this.umamiTracker.trackZipComplete({
          fileCount: this.cellList.length,
          totalSize,
          duration: Date.now() - this.startTime,
          downloadChannel: this.config.downloadChannel // 使用标准参数名
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
      this.emitter.emit('finished')
      return ''
    }

    // 计算总大小
    const totalSize = this.cellList.reduce((sum, file) => sum + (file.size || 0), 0)

    // 重置会话 ID（开始新下载任务）
    this.umamiTracker.resetSession()

    // 统计用户配置提交
    this.umamiTracker.trackConfigSubmit({
      fileNameType: this.config.fileNameType,
      downloadTypeByFolders: this.config.downloadTypeByFolders,
      attachmentFieldsCount: this.config.attachmentFileds?.length || 0,
      downloadChannel: this.config.downloadChannel,
      downloadType: this.config.downloadType,
      concurrency: this.config.concurrency || 0
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
    this.isCancelled = false
    this.cancelReason = ''
    this.isDownloading = true

    // 重置下载器的取消状态
    this.browserDownloader.isCancelled = false

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

      // 获取失败文件统计
      const failureStats = this._isWebSocketChannel()
        ? this.webSocketDownloader.getFailureStats()
        : this.browserDownloader.getFailureStats()

      // 检查是否被用户取消
      if (this.isCancelled && this.cancelReason === 'user_manual_cancel') {
        // 统计用户主动取消
        const duration = Date.now() - this.startTime
        this.umamiTracker.trackDownloadCancel({
          reason: this.cancelReason,
          fileCount: this.cellList.length,
          successCount: this.successCount,
          failedCount: this.failedCount,
          duration,
          downloadChannel: this.config.downloadChannel
        })
      } else {
        // 统计正常下载完成
        const duration = Date.now() - this.startTime
        const totalSize = this.cellList.reduce((sum, file) => sum + (file.size || 0), 0)

        this.umamiTracker.trackDownloadComplete({
          fileCount: this.cellList.length,
          successCount: this.successCount,
          failedCount: this.failedCount,
          duration,
          isCancelled: this.isCancelled,
          failureStats,
          downloadChannel: this.config.downloadChannel
        })

        // 统计下载速度（使用内部实时计算的速度）
        if (duration > 1000 && this.successCount > 0) {
          const totalSizeMB = totalSize / (1024 * 1024)

          this.umamiTracker.trackDownloadSpeed({
            fileCount: this.cellList.length,
            totalSizeMB,
            duration,
            downloadChannel: this.config.downloadChannel
          })
        }
      }
    } catch (error) {
      console.error('download failed', error)
      const message = error?.message || $t('file_download_failed')
      this.emitter.emit('warn', message)

      // 细化取消原因
      if (!this.isCancelled) {
        this.isCancelled = true
        // 根据错误类型细化原因
        const errorType = this._classifyErrorType(error)
        this.cancelReason = errorType
      }

      // 统计异常中断（下载_取消）
      const duration = Date.now() - this.startTime
      this.umamiTracker.trackDownloadCancel({
        reason: this.cancelReason,
        fileCount: this.cellList.length,
        successCount: this.successCount,
        failedCount: this.failedCount,
        duration,
        downloadChannel: this.config.downloadChannel,
        errorCode: error?.code || error?.name,
        errorStack: error?.stack
      })

      // 统计致命错误
      this.umamiTracker.trackDownloadFatalError({
        type: error?.name || 'Error',
        message: error?.message || '未知错误',
        downloadChannel: this.config.downloadChannel, // 使用标准参数名
        code: error?.code,
        stack: error?.stack,
        httpStatus: error?.response?.status
      })
    } finally {
      this.isDownloading = false
      this.emitter.emit('finished')
    }
  }

  /**
   * 分类错误类型（增强版：支持更多错误场景）
   */
  _classifyErrorType(error) {
    const status = error?.response?.status
    const message = error?.message || ''
    const code = error?.code || ''
    const messageLower = message.toLowerCase()

    // 网络相关错误
    if (code === 'ECONNABORTED' || messageLower.includes('timeout')) {
      return 'timeout_error'
    }
    if (
      code === 'ENOTFOUND' ||
      code === 'ECONNREFUSED' ||
      code === 'ENETUNREACH' ||
      messageLower.includes('network') ||
      messageLower.includes('连接')
    ) {
      return 'network_error'
    }

    // WebSocket 错误
    if (
      messageLower.includes('websocket') ||
      messageLower.includes('ws:') ||
      messageLower.includes('wss:')
    ) {
      return 'websocket_error'
    }

    // CORS 错误
    if (
      messageLower.includes('cors') ||
      messageLower.includes('cross-origin') ||
      messageLower.includes('跨域')
    ) {
      return 'cors_error'
    }

    // 授权错误
    if (
      status === 401 ||
      status === 403 ||
      messageLower.includes('授权') ||
      messageLower.includes('auth') ||
      messageLower.includes('permission') ||
      messageLower.includes('forbidden')
    ) {
      return 'auth_error'
    }

    // 链接过期
    if (
      status === 404 ||
      status === 410 ||
      messageLower.includes('expired') ||
      messageLower.includes('过期') ||
      messageLower.includes('not found')
    ) {
      return 'expired_url_error'
    }

    // 客户端错误（4xx）
    if (status >= 400 && status < 500) {
      return 'client_error'
    }

    // 服务器错误（5xx）
    if (status >= 500) {
      return 'server_error'
    }

    // 文件系统错误
    if (
      messageLower.includes('filesystem') ||
      messageLower.includes('disk') ||
      messageLower.includes('文件系统') ||
      messageLower.includes('磁盘')
    ) {
      return 'filesystem_error'
    }

    // 默认未知错误
    return 'unknown_error'
  }

  /**
   * 用户主动取消下载
   */
  cancelDownload() {
    if (!this.isDownloading) {
      return
    }

    this.isCancelled = true
    this.cancelReason = 'user_manual_cancel'

    // 发出取消信号
    this.emitter.emit('cancelled')
  }

  /**
   * 获取当前下载统计信息
   */
  getDownloadStats() {
    const failureStats = this._isWebSocketChannel()
      ? this.webSocketDownloader.getFailureStats()
      : this.browserDownloader.getFailureStats()

    return {
      total: this.cellList.length,
      success: this.successCount,
      failed: this.failedCount,
      failureStats,
      isCancelled: this.isCancelled,
      isDownloading: this.isDownloading
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
