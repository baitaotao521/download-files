import to from 'await-to-js'
import {
  removeSpecialChars,
  getFolderName,
  replaceFileName
} from '@/utils/index.js'
import { i18n } from '@/locales/i18n.js'

const $t = i18n.global.t

/**
 * 文件预处理器
 * 职责:
 * - 获取记录与附件元信息
 * - 文件自定义命名
 * - 文件夹分类
 * - 文件名去重
 */
class FileProcessor {
  constructor(config, emitter) {
    this.config = config
    this.emitter = emitter
    this.nameSpace = new Set()
    this.cellStringCache = new Map()
  }

  /**
   * 根据记录选择情况聚合记录:优先使用手动选择,否则分页获取视图全部记录
   * @param {Object} oTable - 数据表实例
   * @returns {Promise<Array>} 记录列表
   */
  async loopGetRecordIdList(oTable, list = [], pageToken) {
    const hasExplicitSelection = Array.isArray(this.config.selectedRecordIds) && this.config.selectedRecordIds.length
    if (hasExplicitSelection) {
      const uniqueIds = Array.from(new Set(this.config.selectedRecordIds))
      for (const recordId of uniqueIds) {
        const [error, record] = await to(oTable.getRecordById(recordId))
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
      viewId: this.config.viewId
    }
    if (pageToken) {
      params.pageToken = pageToken
    }
    const [err, response] = await to(oTable.getRecordsByPage(params))
    console.log('response', response)
    if (err) {
      console.log(err)
    } else {
      const { hasMore, records = [], pageToken: nextPageToken } = response

      list.push(...records)
      if (hasMore && nextPageToken) {
        await this.loopGetRecordIdList(oTable, list, nextPageToken)
      }
    }

    return list
  }

  /**
   * 组装附件单元格列表,补齐路径、顺序等信息
   * @param {Object} oTable - 数据表实例
   * @returns {Promise<Array>} 附件信息列表
   */
  async getCellsList(oTable) {
    const oRecordList = await this.loopGetRecordIdList(oTable)
    let cellList = []

    for (const fieldId of this.config.attachmentFileds) {
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
          this.emitter.emit('preding', cell)
        } else {
          this.emitter.emit('preding')
        }
      }
    }
    cellList = cellList.map((e, index) => ({ ...e, order: index + 1 }))
    return cellList
  }

  /**
   * 获取单元格字符串(带缓存),避免重复请求导致等待时间变长
   */
  async _getCellStringCached(fieldId, recordId, oTable) {
    const cacheKey = `${recordId}::${fieldId}`
    if (this.cellStringCache.has(cacheKey)) {
      return this.cellStringCache.get(cacheKey)
    }
    const value = await oTable.getCellString(fieldId, recordId)
    this.cellStringCache.set(cacheKey, value)
    return value
  }

  /**
   * 批量预取所有需要的字段数据，避免并发时频繁调用 getCellString
   * @param {Array} cellList - 文件列表
   * @param {Object} oTable - 数据表实例
   */
  async _prefetchAllFieldData(cellList, oTable) {
    // 收集所有需要查询的字段 ID
    const fieldIds = new Set()

    // 自定义命名字段
    if (this.config.fileNameType === 1 && Array.isArray(this.config.fileNameByField)) {
      this.config.fileNameByField.forEach(id => fieldIds.add(id))
    }

    // 文件夹分类字段
    if (this._supportsFolderClassification() && this.config.downloadTypeByFolders) {
      if (this.config.firstFolderKey) {
        fieldIds.add(this.config.firstFolderKey)
      }
      if (this.config.secondFolderKey) {
        fieldIds.add(this.config.secondFolderKey)
      }
    }

    if (fieldIds.size === 0) {
      return // 无需预取
    }

    // 收集所有唯一的 recordId
    const recordIds = [...new Set(cellList.map(cell => cell.recordId))]

    // 批量预取（满速并发）
    const PREFETCH_CONCURRENCY = 30
    const tasks = []

    for (const recordId of recordIds) {
      for (const fieldId of fieldIds) {
        const cacheKey = `${recordId}::${fieldId}`
        if (!this.cellStringCache.has(cacheKey)) {
          tasks.push({ recordId, fieldId })
        }
      }
    }

    // 分批并发执行
    for (let i = 0; i < tasks.length; i += PREFETCH_CONCURRENCY) {
      const batch = tasks.slice(i, i + PREFETCH_CONCURRENCY)
      await Promise.all(
        batch.map(async({ recordId, fieldId }) => {
          try {
            const value = await oTable.getCellString(fieldId, recordId)
            const cacheKey = `${recordId}::${fieldId}`
            this.cellStringCache.set(cacheKey, value)
          } catch (error) {
            console.warn(`预取字段数据失败: recordId=${recordId}, fieldId=${fieldId}`, error)
            // 失败时设置空值，避免后续重复请求
            this.cellStringCache.set(`${recordId}::${fieldId}`, '')
          }
        })
      )
    }

    console.log(`✅ 预取完成: ${tasks.length} 个字段数据已缓存（并发数: ${PREFETCH_CONCURRENCY}，满速模式）`)
  }

  /**
   * 判断当前是否支持文件夹分类(ZIP 或桌面端下载)
   */
  _supportsFolderClassification() {
    const isWebSocketChannel = this.config.downloadChannel === 'websocket' || this.config.downloadChannel === 'websocket_auth'
    return isWebSocketChannel || this.config.downloadType === 1
  }

  /**
   * 确保当前文件的文件夹路径已就绪(按需计算)
   */
  async _ensureFolderPathReady(fileInfo, oTable) {
    if (!fileInfo || fileInfo.__folderPathReady) {
      return
    }

    if (!this._supportsFolderClassification() || !this.config.downloadTypeByFolders) {
      fileInfo.path = fileInfo.path || ''
      fileInfo.__folderPathReady = true
      return
    }

    const getProcessedFolderName = async(fieldKey) => {
      const rawValue = await this._getCellStringCached(fieldKey, fileInfo.recordId, oTable)
      return removeSpecialChars(getFolderName(rawValue)) || $t('uncategorized')
    }

    let parentFolder = ''
    if (this.config.firstFolderKey) {
      parentFolder += `${await getProcessedFolderName(this.config.firstFolderKey)}/`
    }
    if (this.config.secondFolderKey) {
      parentFolder += `${await getProcessedFolderName(this.config.secondFolderKey)}/`
    }

    fileInfo.path = parentFolder
    fileInfo.__folderPathReady = true
  }

  /**
   * 确保当前文件的自定义命名已就绪(按需计算)
   */
  async _ensureCustomFileNameReady(fileInfo, oTable) {
    if (!fileInfo || fileInfo.__customNameReady) {
      return
    }

    if (this.config.fileNameType !== 1) {
      fileInfo.__customNameReady = true
      return
    }

    const targetFieldIds = Array.isArray(this.config.fileNameByField) ? this.config.fileNameByField : []
    if (!targetFieldIds.length) {
      fileInfo.__customNameReady = true
      return
    }

    const parts = await Promise.all(
      targetFieldIds.map((fieldId) =>
        this._getCellStringCached(fieldId, fileInfo.recordId, oTable)
      )
    )
    const mergedName = parts.filter((name) => name).join(this.config.nameMark)

    const replaced = replaceFileName(fileInfo.name, mergedName, $t('undefined'))
    fileInfo.name = removeSpecialChars(replaced)
    fileInfo.__customNameReady = true
  }

  /**
   * 生成不重复的文件名,避免覆盖
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
   * 为桌面端下载预先生成稳定的唯一文件名,避免后续重复改名
   */
  _prepareUniqueFileName(fileInfo) {
    if (!fileInfo || fileInfo.__uniqueNameReady) {
      return
    }
    fileInfo.name = this.getUniqueFileName(fileInfo.name, fileInfo.path)
    fileInfo.__uniqueNameReady = true
  }

  /**
   * 按需准备文件元信息:路径、改名、唯一名
   * 目标:避免"先把全部临时链接/元信息算完才开始下载",改为边准备边下载
   */
  async prepareFileInfoForDownload(fileInfo, oTable) {
    if (!fileInfo) {
      return
    }
    await this._ensureFolderPathReady(fileInfo, oTable)
    await this._ensureCustomFileNameReady(fileInfo, oTable)
    this._prepareUniqueFileName(fileInfo)
  }

  /**
   * 批量预处理所有文件(用于桌面端下载,需要稳定的元信息)
   */
  async batchPrepareAllFiles(cellList, oTable) {
    // 先批量处理自定义命名(可并发)
    if (this.config.fileNameType === 1) {
      const targetFieldIds = Array.isArray(this.config.fileNameByField) ? this.config.fileNameByField : []

      const getFileName = async(cell, fieldIds) => {
        const names = await Promise.all(
          fieldIds.map((fieldId) =>
            this._getCellStringCached(fieldId, cell.recordId, oTable)
          )
        )
        return names.filter((name) => name).join(this.config.nameMark)
      }

      const updateCellNames = (cell, newName) => {
        const cName = replaceFileName(cell.name, newName, $t('undefined'))
        cell.name = removeSpecialChars(cName)
        cell.__customNameReady = true
      }

      const promises = cellList.map((cell) =>
        getFileName(cell, targetFieldIds)
      )

      const names = await Promise.all(promises)

      names.forEach((name, index) => {
        updateCellNames(cellList[index], name)
      })
    }

    // 批量处理文件夹路径(可并发)
    if (this._supportsFolderClassification() && this.config.downloadTypeByFolders) {
      const getProcessedFolderName = async(fieldKey, recordId) => {
        const name = await this._getCellStringCached(fieldKey, recordId, oTable)
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
        cell.__folderPathReady = true
      }

      await Promise.all(
        cellList.map((cell) =>
          setCellFolderName(cell, this.config.firstFolderKey, this.config.secondFolderKey)
        )
      )
    }

    // 串行生成唯一文件名(依赖 nameSpace 状态,不可并发)
    for (const cell of cellList) {
      this._prepareUniqueFileName(cell)
    }
  }

  /**
   * 清除缓存(用于重新下载时重置状态)
   */
  clearCache() {
    this.nameSpace.clear()
    this.cellStringCache.clear()
  }
}

export default FileProcessor
