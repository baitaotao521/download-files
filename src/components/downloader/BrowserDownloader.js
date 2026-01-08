import { saveAs } from 'file-saver'
import JSZip from 'jszip'
import axios from 'axios'
import to from 'await-to-js'
import pLimit from 'p-limit'
import { chunkArrayByMaxSize } from '@/utils/index.js'
import { i18n } from '@/locales/i18n.js'
import ProgressThrottler from './ProgressThrottler.js'
import FailureManager from './FailureManager.js'

const $t = i18n.global.t

const MAX_ZIP_SIZE_NUM = 1
const MAX_ZIP_SIZE = MAX_ZIP_SIZE_NUM * 1024 * 1024 * 1024
// 浏览器直下:下载并发数需要受控,避免一次性获取过多"临时下载链接"后排队等待导致过期
// 经验值:单文件直下并发略高一些;ZIP 打包需要占用内存与 CPU,适当降低并发更稳
const BROWSER_DOWNLOAD_CONCURRENCY_INDIVIDUAL = 50
const BROWSER_DOWNLOAD_CONCURRENCY_ZIP = 30
// 进度更新节流间隔(毫秒) - 优化：100ms 提升 UI 流畅度
const PROGRESS_THROTTLE_INTERVAL = 100

/**
 * 浏览器直接下载器
 * 职责:
 * - 单文件逐个下载
 * - ZIP 打包下载
 * - 获取附件临时链接
 * - 并发控制
 * - 失败文件管理与重试
 * - 内存管理优化
 */
class BrowserDownloader {
  constructor(emitter, fileProcessor, umamiTracker = null, downloadChannel = '') {
    this.emitter = emitter
    this.fileProcessor = fileProcessor
    this.umamiTracker = umamiTracker
    this.downloadChannel = downloadChannel
    this.zip = null
    this.isCancelled = false
    this.abortController = null

    // 初始化辅助模块
    this.progressThrottler = new ProgressThrottler(emitter, PROGRESS_THROTTLE_INTERVAL)
    this.failureManager = new FailureManager(emitter, umamiTracker, downloadChannel)

    // ObjectURL 管理,防止内存泄漏
    this.objectUrls = new Set()

    // ⭐ 使用 p-limit 简化 URL 获取并发控制
    this.urlFetchLimit = pLimit(50)

    // 监听取消事件
    this.emitter.on('cancelled', () => {
      this.cancel()
    })
  }

  /**
   * 取消所有下载
   */
  cancel() {
    this.isCancelled = true

    // 中断所有正在进行的 HTTP 请求
    if (this.abortController) {
      this.abortController.abort()
    }

    // 清空 p-limit 队列
    this.urlFetchLimit.clearQueue()
  }

  /**
   * 以有限并发运行任务,避免一次性占满资源
   */
  async runWithConcurrency(list, worker, concurrency = BROWSER_DOWNLOAD_CONCURRENCY_INDIVIDUAL) {
    const source = Array.isArray(list) ? list : []
    if (!source.length) return
    const limit = Math.max(1, Math.min(concurrency, source.length))
    let cursor = 0
    const pick = () => {
      // 检查是否取消
      if (this.isCancelled) return null
      if (cursor >= source.length) return null
      const current = source[cursor]
      cursor += 1
      return current
    }
    const runners = Array.from({ length: limit }, async() => {
      let item = pick()
      while (item) {
        // 每个任务前检查取消状态
        if (this.isCancelled) break
        await worker(item)
        item = pick()
      }
    })
    await Promise.all(runners)
  }

  /**
   * 获取临时链接（使用 p-limit 自动管理并发）
   */
  async _getAttachmentUrlQueued(fileInfo, oTable) {
    const { token, fieldId, recordId } = fileInfo
    return this.urlFetchLimit(() => oTable.getAttachmentUrl(token, fieldId, recordId))
  }

  /**
   * 获取附件直链并应用唯一文件名
   */
  async getAttachmentUrl(fileInfo, oTable) {
    await this.fileProcessor.prepareFileInfoForDownload(fileInfo, oTable)

    if (fileInfo.fileUrl) {
      return fileInfo.fileUrl
    }

    const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))
    const isTimeoutError = (error) => {
      const code = error?.code
      if (code === 'ECONNABORTED') {
        return true
      }
      const message = error?.msg || error?.message || ''
      return typeof message === 'string' && message.toLowerCase().includes('timeout')
    }

    const maxAttempts = 3
    let lastError = null
    for (let attempt = 1; attempt <= maxAttempts; attempt++) {
      try {
        // ⭐ 使用队列化的获取方法，限制并发
        fileInfo.fileUrl = await this._getAttachmentUrlQueued(fileInfo, oTable)
        return fileInfo.fileUrl
      } catch (error) {
        lastError = error
        if (isTimeoutError(error) && attempt < maxAttempts) {
          await sleep(300 * attempt)
          continue
        }
        const logId = error?.logId
        if (isTimeoutError(error)) {
          throw new Error($t('error_temp_download_url_timeout', { logId: logId ? ` (logId: ${logId})` : '' }))
        }
        const message = error?.msg || error?.message || $t('file_download_failed')
        throw new Error(`${message}${logId ? ` (logId: ${logId})` : ''}`)
      }
    }
    const fallbackLogId = lastError?.logId
    throw new Error($t('error_temp_download_url_timeout', { logId: fallbackLogId ? ` (logId: ${fallbackLogId})` : '' }))
  }

  /**
   * 下载单个文件并上报进度(包含重试兜底,避免临时链接失效或网络抖动导致失败)
   */
  async downloadFile(fileInfo, oTable) {
    await this.fileProcessor.prepareFileInfoForDownload(fileInfo, oTable)

    const { name, order, size } = fileInfo
    const maxAttempts = 3
    const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

    // 检查是否取消
    if (this.isCancelled) {
      return null
    }

    // 初始进度上报
    this.progressThrottler.updateProgress({
      index: order,
      name,
      size,
      percentage: 0
    })

    for (let attempt = 1; attempt <= maxAttempts; attempt++) {
      // 每次重试前检查取消状态
      if (this.isCancelled) {
        return null
      }

      try {
        await this.getAttachmentUrl(fileInfo, oTable)
      } catch (error) {
        const errorType = this.failureManager.classifyError(error)
        const httpStatus = error?.response?.status

        if (this.failureManager.shouldRefreshUrl(errorType, httpStatus)) {
          // 埋点：临时链接刷新
          if (this.umamiTracker) {
            this.umamiTracker.trackRefreshTempUrl({
              fileName: fileInfo.name,
              httpStatus,
              refreshSuccess: attempt < maxAttempts, // 还有重试机会
              downloadMode: this.downloadChannel,
              retryCount: attempt
            })
          }
          fileInfo.fileUrl = null
        }

        if (attempt < maxAttempts) {
          await sleep(300 * attempt)
          continue
        }
        // 记录失败
        this.failureManager.recordFailure(fileInfo, error, attempt)
        this.emitter.emit('error', {
          message: error?.message || $t('file_download_failed'),
          index: order
        })
        return null
      }

      // 为每个下载创建独立的 AbortController
      const controller = new AbortController()

      let completed = false
      const [err, response] = await to(
        axios({
          method: 'get',
          responseType: 'blob',
          url: fileInfo.fileUrl,
          signal: controller.signal,
          onDownloadProgress: (progressEvent) => {
            if (completed) return
            // 检查取消状态并中断请求
            if (this.isCancelled) {
              controller.abort()
              return
            }
            if (progressEvent.lengthComputable && progressEvent.total > 0) {
              const percentage = Math.round(
                (progressEvent.loaded * 100) / progressEvent.total
              )
              // 避免提前上报 100% 导致 UI 误判"已完成"
              const safePercentage = Math.min(Math.max(percentage, 0), 99)

              // 使用节流更新进度
              this.progressThrottler.updateProgress({
                index: order,
                percentage: safePercentage
              })
            }
          }
        })
      )
      completed = true

      // 检查是否因取消而中断
      if (err && err.code === 'ERR_CANCELED') {
        return null
      }

      if (!err) {
        const blob = response.data

        // 文件完整性验证
        if (size > 0 && blob.size !== size) {
          console.warn(`文件 ${name} 大小不匹配: 预期 ${size}, 实际 ${blob.size}`)
          // 如果差异小于 1KB,可能是编码问题,仍然接受
          if (Math.abs(blob.size - size) > 1024 && attempt < maxAttempts) {
            await sleep(300 * attempt)
            continue
          }
        }

        // 上报 100% 进度(不节流)
        this.progressThrottler.updateProgress({
          index: order,
          percentage: 100
        })

        return blob
      }

      // 检查是否因取消而失败
      if (err.code === 'ERR_CANCELED') {
        return null
      }

      const errorType = this.failureManager.classifyError(err)
      const httpStatus = err?.response?.status

      if (this.failureManager.shouldRefreshUrl(errorType, httpStatus)) {
        // 埋点：临时链接刷新
        if (this.umamiTracker) {
          this.umamiTracker.trackRefreshTempUrl({
            fileName: fileInfo.name,
            httpStatus,
            refreshSuccess: attempt < maxAttempts, // 还有重试机会
            downloadMode: this.downloadChannel,
            retryCount: attempt
          })
        }
        fileInfo.fileUrl = null
      }

      if (attempt < maxAttempts) {
        await sleep(300 * attempt)
        continue
      }

      // 记录失败
      this.failureManager.recordFailure(fileInfo, err, attempt)
      this.emitter.emit('error', {
        message: err?.message || $t('file_download_failed'),
        index: order
      })
      return null
    }
    return null
  }

  /**
   * 处理单个文件,获取内容并写入当前 Zip
   */
  async processFile(fileInfo, oTable) {
    const blob = await this.downloadFile(fileInfo, oTable)

    if (blob) {
      this.zip.file(`${fileInfo.path}${fileInfo.name}`, blob)
    }
  }

  /**
   * 按 ZIP 包体积切片并串行写入压缩包
   */
  async zipDownLoad(cellList, zipName, oTable) {
    const { chunks: zipsList, maxChunks: maxChunksList } = chunkArrayByMaxSize(cellList, MAX_ZIP_SIZE)
    if (zipsList.length > 1) {
      this.emitter.emit('warn', $t('text19', { length: zipsList.length }))
    }
    if (maxChunksList.length) {
      this.emitter.emit('warn', $t('text20', { length: maxChunksList.length }))
    }

    for (const zipList of zipsList) {
      // 检查取消状态
      if (this.isCancelled) {
        return
      }

      this.zip = new JSZip()
      await this.runWithConcurrency(
        zipList,
        (fileInfo) => this.processFile(fileInfo, oTable),
        BROWSER_DOWNLOAD_CONCURRENCY_ZIP
      )

      // 检查取消状态
      if (this.isCancelled) {
        this.zip = null
        return
      }

      const [err, content] = await to(this.zip.generateAsync(
        { type: 'blob' },
        (metadata) => {
          // 检查取消状态
          if (this.isCancelled) {
            return
          }
          const percent = metadata.percent.toFixed(2)
          this.emitter.emit('zip_progress', percent)
        }
      ))

      if (err) {
        this.emitter.emit('max_size_warning')
      } else if (!this.isCancelled) {
        saveAs(content, `${zipName}.zip`)
        // 及时释放 Blob 内存
        setTimeout(() => {
          if (content && typeof content.close === 'function') {
            content.close()
          }
        }, 1000)
      }

      // 释放 zip 实例
      this.zip = null
    }

    // 检查取消状态
    if (this.isCancelled) {
      return
    }

    // 处理超大文件(单独下载)
    for (const fileInfo of maxChunksList) {
      if (this.isCancelled) {
        return
      }
      await this.sigleDownLoad([fileInfo], oTable)
    }

    // 刷新剩余的进度更新
    this.progressThrottler.flush()
  }

  /**
   * 浏览器单文件串行下载
   */
  async sigleDownLoad(cellList, oTable) {
    const downLocal = async(fileInfo) => {
      const blob = await this.downloadFile(fileInfo, oTable)
      if (blob) {
        const objectUrl = URL.createObjectURL(blob)
        this.objectUrls.add(objectUrl) // 记录 ObjectURL

        const a = document.createElement('a')
        a.setAttribute('href', objectUrl)
        a.setAttribute('download', fileInfo.name)
        a.click()

        // 延迟释放 ObjectURL,确保下载已触发
        setTimeout(() => {
          URL.revokeObjectURL(objectUrl)
          this.objectUrls.delete(objectUrl)
        }, 100)
      }
    }

    await this.runWithConcurrency(
      cellList,
      async(fileInfo) => {
        await downLocal(fileInfo)
      },
      BROWSER_DOWNLOAD_CONCURRENCY_INDIVIDUAL
    )

    // 刷新剩余的进度更新
    this.progressThrottler.flush()
  }

  /**
   * 通过浏览器串行下载:根据选择切换 zip 或逐个下载
   */
  async download(cellList, config, oTable) {
    if (config.downloadType === 2) {
      await this.sigleDownLoad(cellList, oTable)
      return
    }
    await this.zipDownLoad(cellList, config.zipName, oTable)
  }

  /**
   * 获取失败文件列表
   */
  getFailedFiles() {
    return this.failureManager.getFailedFiles()
  }

  /**
   * 获取失败统计
   */
  getFailureStats() {
    return this.failureManager.getFailureStats()
  }

  /**
   * 清理资源,防止内存泄漏
   */
  destroy() {
    // 清理所有未释放的 ObjectURL
    for (const url of this.objectUrls) {
      URL.revokeObjectURL(url)
    }
    this.objectUrls.clear()

    // 销毁辅助模块
    this.progressThrottler.destroy()
    this.failureManager.clear()

    // 释放 ZIP 实例
    this.zip = null

    // 重置取消状态
    this.isCancelled = false
    this.abortController = null
  }
}

export default BrowserDownloader
