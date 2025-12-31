/**
 * 失败文件管理器
 * 职责:
 * - 收集下载失败的文件信息
 * - 区分错误类型(网络/授权/服务器)
 * - 支持失败文件重试
 * - 提供失败统计信息
 */
class FailureManager {
  constructor(emitter) {
    this.emitter = emitter
    this.failedFiles = new Map() // fileIndex -> { fileInfo, error, retryCount, errorType }
  }

  /**
   * 错误类型分类
   */
  classifyError(error) {
    const status = error?.response?.status
    const message = error?.message || ''

    // 网络错误
    if (error?.code === 'ECONNABORTED' || message.toLowerCase().includes('timeout')) {
      return 'network'
    }
    if (message.toLowerCase().includes('network')) {
      return 'network'
    }

    // 授权错误
    if (status === 401 || status === 403) {
      return 'auth'
    }

    // 链接失效
    if ([400, 404, 410].includes(status)) {
      return 'expired_url'
    }

    // 服务器错误
    if (status >= 500) {
      return 'server'
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
}

export default FailureManager
