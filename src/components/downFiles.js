import { bitable } from '@lark-base-open/js-sdk'
import { saveAs } from 'file-saver'
import JSZip from 'jszip'
import axios from 'axios'
import { chunkArrayByMaxSize } from '@/utils/index.js'
import { ElMessageBox } from 'element-plus'

import { i18n } from '@/locales/i18n.js'
import to from 'await-to-js'

import {
  removeSpecialChars,
  getFolderName,
  replaceFileName
} from '@/utils/index.js'

const $t = i18n.global.t

const MAX_ZIP_SIZE_NUM = 1

const MAX_ZIP_SIZE = MAX_ZIP_SIZE_NUM * 1024 * 1024 * 1024
// 下载工作线程并发数（普通模式不限制）。
const DOWNLOAD_WORKER_CONCURRENCY = Number.POSITIVE_INFINITY
const WEBSOCKET_LINK_TYPE = 'feishu_attachment_link'
const WEBSOCKET_CONFIG_TYPE = 'feishu_attachment_config'
const WEBSOCKET_COMPLETE_TYPE = 'feishu_attachment_complete'
const WEBSOCKET_REFRESH_TYPE = 'feishu_attachment_refresh'
const WEBSOCKET_ACK_TYPE = 'feishu_attachment_ack'

const MIN_DESKTOP_CLIENT_VERSION = '1.1.5'
const DESKTOP_CLIENT_UPDATE_URL =
  'https://xcnfciyevzhz.feishu.cn/wiki/J9bdwozIViVC4ZkOuKAcSbAQnKQ'

/**
 * 比较语义化版本号，返回 -1/0/1（仅比较前三段数字）。
 */
const compareSemanticVersions = (left, right) => {
  const parse = (value) => {
    const parts = String(value || '')
      .trim()
      .replace(/^v/i, '')
      .split('.')
      .map((item) => Number.parseInt(item, 10))
    return [parts[0] || 0, parts[1] || 0, parts[2] || 0]
  }
  const a = parse(left)
  const b = parse(right)
  for (let i = 0; i < 3; i += 1) {
    if (a[i] > b[i]) return 1
    if (a[i] < b[i]) return -1
  }
  return 0
}

class TokenDispatcher {
  /**
   * 控制鉴权码推送速率，可配置 1 秒内推送的条数。
   */
  constructor(limit = 50, windowMs = 1000) {
    this.limit = limit
    this.windowMs = windowMs
    this.timeline = []
  }

  /**
   * 获取一个可发送鉴权码的时间窗口，必要时等待。
   */
  async acquire(shouldAbort) {
    let acquired = false
    while (!acquired) {
      if (typeof shouldAbort === 'function' && shouldAbort()) {
        return
      }
      const now = Date.now()
      this.timeline = this.timeline.filter((timestamp) => now - timestamp < this.windowMs)
      if (this.timeline.length < this.limit) {
        this.timeline.push(now)
        acquired = true
      } else {
        const waitTime = this.windowMs - (now - this.timeline[0])
        await new Promise((resolve) => setTimeout(resolve, Math.max(waitTime, 0)))
      }
    }
  }
}

class FileDownloader {
  /**
   * 基于表单配置初始化下载器。
   */
  constructor(formData) {
    Object.keys(formData).map((key) => {
      this[key] = formData[key]
    })

    this.oTable = null

    this.nameSpace = new Set()
    this.zip = null
    this.cellList = []
    const pushLimit = Number(this.tokenPushBatchSize) || 50
    this.tokenDispatcher = new TokenDispatcher(pushLimit)
  }
  /**
   * 判断当前是否需要通过 WebSocket 推送文件链接。
   */
  isWebSocketChannel() {
    return this.downloadChannel === 'websocket' || this.downloadChannel === 'websocket_auth'
  }
  /**
   * 判断当前 WebSocket 模式是否走授权码下载流程。
   */
  isTokenWebSocketChannel() {
    return this.downloadChannel === 'websocket_auth'
  }
  /**
   * 根据记录选择情况聚合记录：优先使用手动选择，否则分页获取视图全部记录。
   */
  async loopGetRecordIdList(list = [], pageToken) {
    const hasExplicitSelection = Array.isArray(this.selectedRecordIds) && this.selectedRecordIds.length
    if (hasExplicitSelection) {
      const uniqueIds = Array.from(new Set(this.selectedRecordIds))
      for (const recordId of uniqueIds) {
        const [error, record] = await to(this.oTable.getRecordById(recordId))
        if (error) {
          console.log(error)
          continue
        }
        if (record) {
          list.push({
            recordId,
            fields: record.fields || {}
          })
        }
      }
      return list
    }
    const params = {
      pageSize: 200,
      viewId: this.viewId
    }
    if (pageToken) {
      params.pageToken = pageToken
    }
    const [err, response] = await to(this.oTable.getRecordsByPage(params))
    console.log('response', response)
    if (err) {
      console.log(err)
    } else {
      const { hasMore, records = [], pageToken: nextPageToken } = response

      list.push(...records)
      if (hasMore && nextPageToken) {
        await this.loopGetRecordIdList(list, nextPageToken)
      }
    }

    return list
  }
  /**
   * 组装附件单元格列表，补齐路径、顺序等信息。
   */
  async getCellsList() {
    const oRecordList = await this.loopGetRecordIdList()
    let cellList = []

    for (const fieldId of this.attachmentFileds) {
      for (const records of oRecordList) {
        let cell = records.fields[fieldId]
        const recordId = records.recordId

        if (cell) {
          cell = cell.map((e) => ({
            ...e,
            name: removeSpecialChars(e.name),
            recordId,
            fieldId,
            path: '',
            fileUrl: ''
          }))
          cellList.push(...cell)
          this.emit('preding', cell)
        } else {
          this.emit('preding')
        }
      }
    }
    cellList = cellList.map((e, index) => ({ ...e, order: index + 1 }))
    return cellList
  }

  /**
   * 注册进度事件监听器。
   */
  on(event, callback) {
    if (!this[event + 'Listeners']) {
      this[event + 'Listeners'] = []
    }
    this[event + 'Listeners'].push(callback)

    return this
  }
  /**
   * 触发指定类型的事件。
   */
  emit(type, messgae) {
    this[type + 'Listeners']?.forEach((listener) => {
      listener(messgae)
    })
  }
  /**
   * 按照字段规则批量重命名附件。
   */
  async setFileNames() {
    if (this.fileNameType !== 1) return
    const targetFieldIds = this.fileNameByField
    const getFileName = async(cell, fieldIds) => {
      const names = await Promise.all(
        fieldIds.map(fieldId =>
          this.oTable.getCellString(fieldId, cell.recordId)
        )
      )
      // 过滤掉空字符串，并用 '-' 连接剩余的名称部分
      return names.filter(name => name).join(this.nameMark)
    }

    const updateCellNames = (cell, newName) => {
      if (newName !== cell.name) {
        const cName = replaceFileName(cell.name, newName, $t('undefined'))
        cell.name = removeSpecialChars(cName)
      }
    }

    // 使用 map 创建一个包含所有异步操作的数组
    const promises = this.cellList.map((cell) =>
      getFileName(cell, targetFieldIds)
    )

    // 等待所有异步操作完成
    const names = await Promise.all(promises)

    // 使用 names 更新 cellList 中每个 cell 的 name
    names.forEach((name, index) => {
      updateCellNames(this.cellList[index], name)
    })
  }
  /**
   * 设置附件的目录路径（一级/二级目录）。
   */
  async setFolderPath() {
    const supportsFolderClassification = this.isWebSocketChannel() || this.downloadType === 1

    // 不支持文件夹分类的模式直接跳过（浏览器逐个下载无法落地文件夹）。
    if (!supportsFolderClassification) return
    if (!this.downloadTypeByFolders) return

    // 封装获取和处理文件夹名称的逻辑
    const getProcessedFolderName = async(fieldKey, recordId) => {
      const name = await this.oTable.getCellString(fieldKey, recordId)
      return removeSpecialChars(getFolderName(name)) || $t('uncategorized')
    }

    const setCellFolderName = async(cell, firstFolderKey, secondFolderKey) => {
      let parentFolder = ''
      if (firstFolderKey) {
        parentFolder += `${await getProcessedFolderName(firstFolderKey, cell.recordId)}/`
      }
      if (secondFolderKey) {
        parentFolder += `${await getProcessedFolderName(secondFolderKey, cell.recordId)}/`
      }
      cell.path = parentFolder
    }

    // 使用 Promise.all 处理所有单元格的文件夹名称设置
    await Promise.all(
      this.cellList.map((cell) =>
        setCellFolderName(cell, this.firstFolderKey, this.secondFolderKey)
      )
    )
  }
  /**
   * 生成不重复的文件名，避免覆盖。
   */
  getUniqueFileName(name, path) {
    const fileExtension = name.substring(name.lastIndexOf('.'))
    const baseName = name.substring(0, name.lastIndexOf('.'))
    let nameIndex = 1
    while (this.nameSpace.has(path + name)) {
      name = `${baseName}_${nameIndex}${fileExtension}`
      nameIndex++
    }
    this.nameSpace.add(path + name)
    return name
  }
  /**
   * 以有限并发运行任务，避免一次性占满资源。
   */
  async runWithConcurrency(list, worker, concurrency = DOWNLOAD_WORKER_CONCURRENCY) {
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
   * 按 ZIP 包体积切片并串行写入压缩包。
   */
  async zipDownLoad() {
    const { chunks: zipsList, maxChunks: maxChunksList } = chunkArrayByMaxSize(this.cellList, MAX_ZIP_SIZE)
    if (zipsList.length > 1) {
      this.emit('warn', $t('text19', { length: zipsList.length }))
    }
    if (maxChunksList.length) {
      this.emit('warn', $t('text20', { length: maxChunksList.length }))
    }

    for (const zipList of zipsList) {
      this.zip = new JSZip()
      await this.runWithConcurrency(
        zipList,
        (fileInfo) => this.processFile(fileInfo)
      )
      const [err, content] = await to(this.zip.generateAsync(
        { type: 'blob' },
        (metadata) => {
          const percent = metadata.percent.toFixed(2)
          this.emit('zip_progress', percent)
        }
      ))
      if (err) {
        this.emit('max_size_warning')
      } else {
        saveAs(content, `${this.zipName}.zip`)
        this.zip = null // 释放 zip 实例
      }
    }
    for (const fileInfo of maxChunksList) {
      await this.sigleDownLoad(fileInfo)
    }
  }
  /**
   * 获取附件直链并应用唯一文件名。
   */
  async getAttachmentUrl(fileInfo) {
    if (fileInfo.fileUrl) {
      return fileInfo.fileUrl
    }
    const { token, fieldId, recordId, path, name } = fileInfo

    if (!fileInfo.__uniqueNameReady) {
      fileInfo.name = this.getUniqueFileName(name, path)
      fileInfo.__uniqueNameReady = true
    }
    fileInfo.fileUrl = await this.oTable.getAttachmentUrl(
      token,
      fieldId,
      recordId
    )
    return fileInfo.fileUrl
  }
  /**
   * 为桌面端下载预先生成稳定的唯一文件名，避免后续重复改名。
   */
  _prepareUniqueFileName(fileInfo) {
    if (!fileInfo || fileInfo.__uniqueNameReady) {
      return
    }
    fileInfo.name = this.getUniqueFileName(fileInfo.name, fileInfo.path)
    fileInfo.__uniqueNameReady = true
  }
  /**
   * 处理单个文件，获取内容并写入当前 Zip。
   */
  async processFile(fileInfo) {
    await this.getAttachmentUrl(fileInfo)

    const blob = await this.downloadFile(fileInfo)

    if (blob) {
      this.zip.file(`${fileInfo.path}${fileInfo.name}`, blob)
    }
  }
  /**
   * 浏览器单文件串行下载。
   */
  async sigleDownLoad(file) {
    const cellList = file ? [file] : this.cellList
    const downLocal = async(fileInfo) => {
      const blob = await this.downloadFile(fileInfo)
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
        await this.getAttachmentUrl(fileInfo)
        await downLocal(fileInfo)
      }
    )
  }
  /**
   * 通过浏览器串行下载：根据选择切换 zip 或逐个下载。
   */
  async _downloadViaBrowser() {
    if (this.downloadType === 2) {
      await this.sigleDownLoad()
      return
    }
    await this.zipDownLoad()
  }
  /**
   * 兼容旧调用的桌面客户端下载入口。
   */
  async websocketDownload() {
    return this._downloadViaDesktop()
  }
  /**
   * 本地客户端下载：串行发送链接或鉴权码。
   */
  async _downloadViaDesktop() {
    const wsUrl = this._buildWebSocketUrl()
    const socket = await this._createWebSocket(wsUrl)
    let abortDownloads = false
    let resolveServerInfo = null
    let rejectServerInfo = null
    const serverInfoPromise = new Promise((resolve, reject) => {
      resolveServerInfo = resolve
      rejectServerInfo = reject
    })
    const serverInfoTimer = setTimeout(() => {
      if (typeof resolveServerInfo === 'function') {
        resolveServerInfo(null)
      }
    }, 3000)
    // 宏任务延迟：让出事件循环，确保能及时处理服务端 ACK/refresh。
    const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))
    // WebSocket 发送回压：避免 bufferedAmount 过大导致 refresh 消息排队过久。
    const drainSocketBuffer = async(maxBufferedAmount = 2 * 1024 * 1024) => {
      while (socket.bufferedAmount > maxBufferedAmount) {
        if (abortDownloads) return
        await sleep(20)
      }
    }
    const stopAllDownloads = (reason) => {
      if (abortDownloads) return
      abortDownloads = true
      const message = reason?.message || reason
      if (message) {
        this.emit('warn', message)
      }
      if (typeof rejectServerInfo === 'function') {
        rejectServerInfo(new Error(message || $t('file_download_failed')))
      }
    }
    const completion = this._bindWebSocketLifecycle(socket, {
      onFatalError: stopAllDownloads,
      onServerInfo: (info) => {
        clearTimeout(serverInfoTimer)
        if (typeof resolveServerInfo === 'function') {
          resolveServerInfo(info)
        }
      },
      onRefreshUrl: (() => {
        const fileInfoByOrder = new Map(
          (this.cellList || []).map((item) => [Number(item?.order), item])
        )
        const inflight = new Map()
        const maxConcurrent = Number.POSITIVE_INFINITY
        let active = 0
        const waitQueue = []
        const acquireSlot = async() => {
          if (active < maxConcurrent) {
            active += 1
            return
          }
          await new Promise((resolve) => waitQueue.push(resolve))
          active += 1
        }
        const releaseSlot = () => {
          active = Math.max(active - 1, 0)
          const next = waitQueue.shift()
          if (typeof next === 'function') {
            next()
          }
        }
        return async(order) => {
          if (inflight.has(order)) {
            return inflight.get(order)
          }
          const task = (async() => {
            const fileInfo = fileInfoByOrder.get(order)
            if (!fileInfo) {
              throw new Error($t('file_download_failed'))
            }
            await acquireSlot()
            try {
              // refresh 场景必须强制重新拉取临时链接（旧链接 10 分钟后会失效）。
              fileInfo.fileUrl = null
              const url = await this.getAttachmentUrl(fileInfo)
              if (!url) {
                throw new Error($t('file_download_failed'))
              }
              return url
            } finally {
              releaseSlot()
            }
          })()
          inflight.set(order, task)
          try {
            return await task
          } finally {
            inflight.delete(order)
          }
        }
      })()
    })
    const jobId = `${Date.now()}`
    const useTokenMode = this.isTokenWebSocketChannel()
    if (useTokenMode && !this.appToken) {
      throw new Error($t('error_app_token_missing'))
    }
    try {
      this._sendWebSocketMessage(socket, {
        type: WEBSOCKET_CONFIG_TYPE,
        data: {
          concurrent: 1,
          zipAfterDownload: Boolean(this.zipAfterDownload),
          jobId,
          jobName: this.zipName || jobId,
          zipName: this.zipName || jobId,
          total: this.cellList.length,
          downloadMode: useTokenMode ? 'token' : 'url',
          ...(useTokenMode
            ? {
              tableId: this.tableId,
              appToken: this.appToken
            }
            : {})
        }
      })
      const serverInfo = await serverInfoPromise
      const serverVersion = String(serverInfo?.version || '').trim()
      if (!serverVersion || compareSemanticVersions(serverVersion, MIN_DESKTOP_CLIENT_VERSION) < 0) {
        const displayedVersion = serverVersion || 'unknown'
        const message = $t('desktop_client_update_required', {
          current: displayedVersion,
          required: MIN_DESKTOP_CLIENT_VERSION,
          url: DESKTOP_CLIENT_UPDATE_URL
        })
        stopAllDownloads(message)
        try {
          await ElMessageBox.confirm(
            message,
            $t('desktop_client_update_title'),
            {
              type: 'warning',
              confirmButtonText: $t('desktop_client_update_open'),
              cancelButtonText: $t('desktop_client_update_cancel'),
              closeOnClickModal: false,
              closeOnPressEscape: false
            }
          )
          window.open(DESKTOP_CLIENT_UPDATE_URL, '_blank')
        } catch (error) {
          // 用户取消或弹窗失败时，保持终止下载即可。
        }
      }
      let sentCount = 0
      for (const fileInfo of this.cellList) {
        if (abortDownloads) break
        const { order } = fileInfo
        try {
          this._prepareUniqueFileName(fileInfo)
          if (abortDownloads) break
          this.emit('progress', {
            index: order,
            name: fileInfo.name,
            size: fileInfo.size,
            percentage: 0
          })
          const payload = {
            name: fileInfo.name,
            path: fileInfo.path,
            order: fileInfo.order,
            size: fileInfo.size
          }
          if (useTokenMode) {
            payload.token = fileInfo.token
            payload.fieldId = fileInfo.fieldId
            payload.recordId = fileInfo.recordId
            await this._acquireTokenModeSlot(() => abortDownloads)
          } else {
            payload.token = fileInfo.token
            payload.fieldId = fileInfo.fieldId
            payload.recordId = fileInfo.recordId
          }
          if (abortDownloads) break
          this._sendWebSocketMessage(socket, {
            type: WEBSOCKET_LINK_TYPE,
            data: payload
          })
          sentCount += 1
          if (!useTokenMode) {
            if (sentCount % 50 === 0) {
              await sleep(0)
            }
            await drainSocketBuffer()
          }
        } catch (error) {
          const message = error?.message || $t('file_download_failed')
          this.emit('error', {
            index: order,
            message
          })
          stopAllDownloads(error)
        }
      }
      if (!abortDownloads && useTokenMode) {
        this.emit('zip_progress', {
          message: $t('token_push_waiting_message')
        })
      }
      if (!abortDownloads) {
        this._sendWebSocketMessage(socket, {
          type: WEBSOCKET_COMPLETE_TYPE,
          data: {
            jobId
          }
        })
        await completion
      } else {
        await completion.catch(() => {})
      }
    } finally {
      clearTimeout(serverInfoTimer)
      if (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING) {
        socket.close()
      }
    }
  }
  /**
   * 组合用户输入的 WebSocket URL。
   */
  _buildWebSocketUrl() {
    const rawHost = (this.wsHost || '').trim()
    if (!rawHost) {
      throw new Error($t('error_websocket_host_required'))
    }
    if (/^wss?:\/\//i.test(rawHost)) {
      return rawHost
    }
    const port = this.wsPort ? String(this.wsPort).trim() : ''
    if (rawHost.includes(':') || !port) {
      return `ws://${rawHost}`
    }
    return `ws://${rawHost}:${port}`
  }
  /**
   * 建立 WebSocket 连接并在 ready 时返回实例。
   */
  _createWebSocket(url) {
    return new Promise((resolve, reject) => {
      const socket = new WebSocket(url)
      const cleanup = () => {
        socket.onopen = null
        socket.onerror = null
      }
      socket.onopen = () => {
        cleanup()
        resolve(socket)
      }
      socket.onerror = () => {
        cleanup()
        reject(new Error($t('websocket_connection_failed')))
      }
    })
  }
  /**
   * 监听服务端 ACK，驱动 UI 并在任务完成或失败时结束。
   */
  _bindWebSocketLifecycle(socket, hooks = {}) {
    return new Promise((resolve, reject) => {
      let finished = false
      let hasJobCompleted = false
      const notifyFatal = (error) => {
        if (typeof hooks.onFatalError === 'function') {
          try {
            hooks.onFatalError(error)
          } catch (err) {
            console.error('onFatalError hook failed', err)
          }
        }
      }
      const finish = (error) => {
        if (finished) return
        finished = true
        if (error) {
          reject(error)
        } else {
          resolve()
        }
      }
      socket.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data)
          if (payload.type !== WEBSOCKET_ACK_TYPE) {
            return
          }
          const data = payload.data || {}
          const rawOrder = data.order
          const order = Number(rawOrder)
          const status = data.status
          const stage = data.stage
          if (stage === 'server_info') {
            if (typeof hooks.onServerInfo === 'function') {
              try {
                hooks.onServerInfo(data)
              } catch (err) {
                console.error('onServerInfo hook failed', err)
              }
            }
            return
          }
          if (Number.isInteger(order) && order > 0) {
            if (status === 'success') {
              this.emit('progress', {
                index: order,
                percentage: 100
              })
            } else if (status === 'refresh') {
              const message = data.message || $t('file_download_failed')
              if (typeof hooks.onRefreshUrl === 'function') {
                Promise.resolve()
                  .then(() => hooks.onRefreshUrl(order, data))
                  .then((downloadUrl) => {
                    this._sendWebSocketMessage(socket, {
                      type: WEBSOCKET_REFRESH_TYPE,
                      data: {
                        order,
                        downloadUrl
                      }
                    })
                  })
                  .catch((error) => {
                    const errorMessage = error?.message || message
                    try {
                      this._sendWebSocketMessage(socket, {
                        type: WEBSOCKET_REFRESH_TYPE,
                        data: {
                          order,
                          error: errorMessage
                        }
                      })
                    } catch (sendError) {
                      console.error('failed to send refresh error', sendError)
                    }
                  })
              }
            } else {
              this.emit('error', {
                index: order,
                message: data.message || $t('file_download_failed')
              })
              notifyFatal(data.message || $t('file_download_failed'))
              finish(new Error(data.message || $t('file_download_failed')))
            }
            return
          }
          if (stage === 'zip') {
            this.emit('zip_progress', {
              stage,
              path: data.path,
              message: data.message
            })
            return
          }
          if (stage === 'job_complete') {
            hasJobCompleted = true
            this.emit('zip_progress', {
              stage,
              message: data.message
            })
            finish()
            return
          }
          if (status === 'error') {
            const message = data.message || $t('file_download_failed')
            this.emit('warn', message)
            notifyFatal(message)
            finish(new Error(message))
          }
        } catch (error) {
          console.error('failed to parse websocket ack', error)
        }
      }
      socket.onerror = () => {
        notifyFatal($t('websocket_connection_failed'))
        finish(new Error($t('websocket_connection_failed')))
      }
      socket.onclose = () => {
        if (hasJobCompleted) {
          finish()
        } else {
          notifyFatal($t('websocket_connection_failed'))
          finish(new Error($t('websocket_connection_failed')))
        }
      }
    })
  }
  /**
   * 发送序列化后的 WebSocket 消息。
   */
  _sendWebSocketMessage(socket, payload) {
    if (socket.readyState !== WebSocket.OPEN) {
      throw new Error($t('websocket_connection_failed'))
    }
    socket.send(JSON.stringify(payload))
  }

  /**
   * 控制鉴权码推送频率，使用限流器保证 1 秒最多 5 次。
   */
  async _acquireTokenModeSlot(shouldAbort) {
    await this.tokenDispatcher.acquire(shouldAbort)
  }

  /**
   * 下载单个文件并上报进度。
   */
  async downloadFile(fileInfo) {
    const { fileUrl, name, order, size } = fileInfo
    let isDownloadComplete = false // 新增变量，用于跟踪下载是否完成
    this.emit('progress', {
      index: order,
      name,
      size,
      percentage: 0
    })
    const [err, response] = await to(
      axios({
        method: 'get',
        responseType: 'blob',
        url: fileUrl,
        onDownloadProgress: (progressEvent) => {
          if (progressEvent.lengthComputable && !isDownloadComplete) {
            const percentage = Math.round(
              (progressEvent.loaded * 100) / progressEvent.total
            )
            this.emit('progress', {
              index: order,
              percentage
            })
          }
        }
      })
    )
    if (!isDownloadComplete) {
      this.emit('progress', {
        index: order,

        percentage: 100
      })
      isDownloadComplete = true // 标记下载完成
    }
    if (err) {
      this.emit('error', {
        message: err.message,
        index: order
      })
      return null
    }
    return response.data
  }

  /**
   * 按通道选择下载策略并串行执行。
   */
  async startDownload() {
    this.oTable = await bitable.base.getTableById(this.tableId)
    // 获取所有附件信息
    this.cellList = await this.getCellsList()
    //  为所有附件重新取名
    await this.setFileNames()
    await this.setFolderPath()

    if (!this.cellList.length) {
      this.emit('info', $t('no_files_to_download_message'))
      this.emit('finshed')
      return ''
    }
    try {
      if (this.isWebSocketChannel()) {
        await this._downloadViaDesktop()
      } else {
        await this._downloadViaBrowser()
      }
    } catch (error) {
      console.error('download failed', error)
      const message = error?.message || $t('file_download_failed')
      this.emit('warn', message)
    } finally {
      this.emit('finshed')
    }
  }
}

export default FileDownloader
