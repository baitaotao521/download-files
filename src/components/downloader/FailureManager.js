/**
 * 失败文件管理器
 * 职责:
 * - 收集下载失败的文件信息
 * - 区分错误类型(网络/授权/服务器/CORS/超时等)
 * - 支持失败文件重试
 * - 提供失败统计信息
 * - 集成 Umami 埋点追踪
 */
class FailureManager {
  constructor(emitter, umamiTracker = null, downloadChannel = '') {
    this.emitter = emitter
    this.umamiTracker = umamiTracker
    this.downloadChannel = downloadChannel
    this.failedFiles = new Map() // fileIndex -> { fileInfo, error, retryCount, errorType }
  }

  /**
   * 错误类型分类（增强版）
   */
  classifyError(error) {
    const status = error?.response?.status
    const message = error?.message || ''
    const code = error?.code || ''
    const messageLower = message.toLowerCase()

    // 超时错误
    if (code === 'ECONNABORTED' || messageLower.includes('timeout')) {
      return 'timeout'
    }

    // 网络错误
    if (
      code === 'ENOTFOUND' ||
      code === 'ECONNREFUSED' ||
      code === 'ENETUNREACH' ||
      messageLower.includes('network') ||
      messageLower.includes('连接')
    ) {
      return 'network'
    }

    // CORS 错误
    if (
      messageLower.includes('cors') ||
      messageLower.includes('cross-origin') ||
      messageLower.includes('跨域')
    ) {
      return 'cors'
    }

    // 授权错误
    if (status === 401 || status === 403) {
      return 'auth'
    }

    // 链接失效
    if ([400, 404, 410].includes(status)) {
      return 'expired_url'
    }

    // 客户端错误（4xx）
    if (status >= 400 && status < 500) {
      return 'client'
    }

    // 服务器错误（5xx）
    if (status >= 500) {
      return 'server'
    }

    // 文件系统错误
    if (
      messageLower.includes('filesystem') ||
      messageLower.includes('disk') ||
      messageLower.includes('文件系统')
    ) {
      return 'filesystem'
    }

    // 未知错误
    return 'unknown'
  }

  /**
   * 判断是否应该刷新临时链接
   */
  shouldRefreshUrl(errorType, status) {
    const code = Number(status)
    return errorType === 'expired_url' || [400, 401, 403, 404, 410].includes(code)
  }

  /**
   * 记录失败文件
   */
  recordFailure(fileInfo, error, retryCount = 0) {
    const errorType = this.classifyError(error)
    const { order } = fileInfo

    this.failedFiles.set(order, {
      fileInfo,
      error,
      retryCount,
      errorType,
      timestamp: Date.now()
    })

    this.emitter.emit('file_failed', {
      index: order,
      name: fileInfo.name,
      errorType,
      message: error?.message || '下载失败'
    })

    // 埋点：单个文件下载失败
    if (this.umamiTracker) {
      this.umamiTracker.trackFileDownloadError({
        fileName: fileInfo.name,
        fileSize: fileInfo.size || 0,
        errorType,
        httpStatus: error?.response?.status || 0,
        retryCount,
        downloadMode: this.downloadChannel
      })
    }
  }

  /**
   * 获取所有失败文件
   */
  getFailedFiles() {
    return Array.from(this.failedFiles.values()).map(item => item.fileInfo)
  }

  /**
   * 获取失败统计
   */
  getFailureStats() {
    const stats = {
      total: this.failedFiles.size,
      byType: {
        network: 0,
        auth: 0,
        expired_url: 0,
        server: 0,
        client: 0,
        timeout: 0,
        cors: 0,
        filesystem: 0,
        unknown: 0
      }
    }

    for (const item of this.failedFiles.values()) {
      stats.byType[item.errorType]++
    }

    return stats
  }

  /**
   * 清空失败记录
   */
  clear() {
    this.failedFiles.clear()
  }

  /**
   * 移除指定文件的失败记录(重试成功后调用)
   */
  removeFailure(fileIndex) {
    this.failedFiles.delete(fileIndex)
  }

  /**
   * 单个文件重试埋点
   */
  trackRetryFile(fileInfo) {
    if (!this.umamiTracker) return

    const failureRecord = this.failedFiles.get(fileInfo.order)
    const errorType = failureRecord?.errorType || 'unknown'

    this.umamiTracker.trackRetryFile({
      fileName: fileInfo.name,
      fileSize: fileInfo.size || 0,
      errorType,
      downloadMode: this.downloadChannel
    })
  }

  /**
   * 批量重试埋点
   */
  trackRetryBatch() {
    if (!this.umamiTracker) return

    const failedFiles = this.getFailedFiles()
    const totalSize = failedFiles.reduce((sum, file) => sum + (file.size || 0), 0)
    const stats = this.getFailureStats()

    this.umamiTracker.trackRetryBatch({
      fileCount: failedFiles.length,
      totalSize,
      downloadMode: this.downloadChannel,
      failureTypes: stats.byType
    })
  }
}

export default FailureManager

