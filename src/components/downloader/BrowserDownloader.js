import { saveAs } from 'file-saver'
import JSZip from 'jszip'
import axios from 'axios'
import to from 'await-to-js'
import { chunkArrayByMaxSize } from '@/utils/index.js'
import { i18n } from '@/locales/i18n.js'

const $t = i18n.global.t

const MAX_ZIP_SIZE_NUM = 1
const MAX_ZIP_SIZE = MAX_ZIP_SIZE_NUM * 1024 * 1024 * 1024
// 浏览器直下:下载并发数需要受控,避免一次性获取过多"临时下载链接"后排队等待导致过期
// 经验值:单文件直下并发略高一些;ZIP 打包需要占用内存与 CPU,适当降低并发更稳
const BROWSER_DOWNLOAD_CONCURRENCY_INDIVIDUAL = 50
const BROWSER_DOWNLOAD_CONCURRENCY_ZIP = 30

/**
 * 浏览器直接下载器
 * 职责:
 * - 单文件逐个下载
 * - ZIP 打包下载
 * - 获取附件临时链接
 * - 并发控制
 */
class BrowserDownloader {
  constructor(emitter, fileProcessor) {
    this.emitter = emitter
    this.fileProcessor = fileProcessor
    this.zip = null
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
      if (cursor >= source.length) return null
      const current = source[cursor]
      cursor += 1
      return current
    }
    const runners = Array.from({ length: limit }, async() => {
      let item = pick()
      while (item) {
        await worker(item)
        item = pick()
      }
    })
    await Promise.all(runners)
  }

  /**
   * 获取附件直链并应用唯一文件名
   */
  async getAttachmentUrl(fileInfo, oTable) {
    await this.fileProcessor.prepareFileInfoForDownload(fileInfo, oTable)

    if (fileInfo.fileUrl) {
      return fileInfo.fileUrl
    }
    const { token, fieldId, recordId } = fileInfo

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
        fileInfo.fileUrl = await oTable.getAttachmentUrl(
          token,
          fieldId,
          recordId
        )
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
    const shouldRefreshUrl = (status) => {
      const code = Number(status)
      return [400, 401, 403, 404, 410].includes(code)
    }

    this.emitter.emit('progress', {
      index: order,
      name,
      size,
      percentage: 0
    })

    for (let attempt = 1; attempt <= maxAttempts; attempt++) {
      try {
        await this.getAttachmentUrl(fileInfo, oTable)
      } catch (error) {
        if (shouldRefreshUrl(error?.response?.status)) {
          fileInfo.fileUrl = null
        }
        if (attempt < maxAttempts) {
          await sleep(300 * attempt)
          continue
        }
        this.emitter.emit('error', {
          message: error?.message || $t('file_download_failed'),
          index: order
        })
        return null
      }

      let completed = false
      const [err, response] = await to(
        axios({
          method: 'get',
          responseType: 'blob',
          url: fileInfo.fileUrl,
          onDownloadProgress: (progressEvent) => {
            if (completed) return
            if (progressEvent.lengthComputable && progressEvent.total > 0) {
              const percentage = Math.round(
                (progressEvent.loaded * 100) / progressEvent.total
              )
              // 避免提前上报 100% 导致 UI 误判"已完成"
              const safePercentage = Math.min(Math.max(percentage, 0), 99)
              this.emitter.emit('progress', {
                index: order,
                percentage: safePercentage
              })
            }
          }
        })
      )
      completed = true

      if (!err) {
        this.emitter.emit('progress', {
          index: order,
          percentage: 100
        })
        return response.data
      }

      if (shouldRefreshUrl(err?.response?.status)) {
        fileInfo.fileUrl = null
      }
      if (attempt < maxAttempts) {
        await sleep(300 * attempt)
        continue
      }
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
      this.zip = new JSZip()
      await this.runWithConcurrency(
        zipList,
        (fileInfo) => this.processFile(fileInfo, oTable),
        BROWSER_DOWNLOAD_CONCURRENCY_ZIP
      )
      const [err, content] = await to(this.zip.generateAsync(
        { type: 'blob' },
        (metadata) => {
          const percent = metadata.percent.toFixed(2)
          this.emitter.emit('zip_progress', percent)
        }
      ))
      if (err) {
        this.emitter.emit('max_size_warning')
      } else {
        saveAs(content, `${zipName}.zip`)
        this.zip = null // 释放 zip 实例
      }
    }
    for (const fileInfo of maxChunksList) {
      await this.sigleDownLoad([fileInfo], oTable)
    }
  }

  /**
   * 浏览器单文件串行下载
   */
  async sigleDownLoad(cellList, oTable) {
    const downLocal = async(fileInfo) => {
      const blob = await this.downloadFile(fileInfo, oTable)
      if (blob) {
        const objectUrl = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.setAttribute('href', objectUrl)
        a.setAttribute('download', fileInfo.name)
        a.click()
        URL.revokeObjectURL(objectUrl)
      }
    }
    await this.runWithConcurrency(
      cellList,
      async(fileInfo) => {
        await downLocal(fileInfo)
      },
      BROWSER_DOWNLOAD_CONCURRENCY_INDIVIDUAL
    )
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
}

export default BrowserDownloader
