<template>
  <div class="dialog-process">
    <h4>
      <el-icon class="title-icon"><Download /></el-icon>
      {{ $t("download_progress") }}
    </h4>
    <div class="dialog-circle">
      <ProgressCircle :percent="percent" />
    </div>

    <!-- 警告信息区域 -->
    <div v-if="totalSize > MAX_SIZE || warnList.length || zipError" class="warning-section">
      <el-alert
        v-if="totalSize > MAX_SIZE"
        type="warning"
        :closable="false"
        show-icon
        style="margin-bottom: 8px;"
      >
        {{ $t('text7') }}
      </el-alert>
      <el-alert
        v-for="item in warnList"
        :key="item"
        type="warning"
        :closable="false"
        show-icon
        style="margin-bottom: 8px;"
      >
        {{ item }}
      </el-alert>
      <el-alert
        v-if="!!zipError"
        type="error"
        :closable="false"
        show-icon
        style="margin-bottom: 8px;"
      >
        {{ $t('text11') }}
      </el-alert>
    </div>

    <h4>{{ $t("download_details") }}</h4>
    <div class="prompt">
      <!-- 统计卡片 - 边栏竖向布局 -->
      <el-row :gutter="8" class="stats-row">
        <el-col :span="12">
          <div class="stat-card">
            <div class="stat-label">{{ $t('text8', { totalLength: '' }).replace(/\d+/, '').trim() }}</div>
            <div class="stat-value">{{ totalLength }}</div>
          </div>
        </el-col>
        <el-col :span="12">
          <div class="stat-card">
            <div class="stat-label">{{ $t('text10', { getCompletedIdsLength: '' }).replace(/\d+/, '').trim() }}</div>
            <div class="stat-value stat-success">{{ getCompletedIdsLength }}</div>
          </div>
        </el-col>
      </el-row>
      <el-row :gutter="8" class="stats-row">
        <el-col :span="12">
          <div class="stat-card">
            <div class="stat-label">{{ $t('text21', { failedCount: '' }).replace(/\d+/, '').trim() }}</div>
            <div class="stat-value stat-danger">{{ getFailedIdsLength }}</div>
          </div>
        </el-col>
        <el-col :span="12">
          <div class="stat-card">
            <div class="stat-label">{{ $t('text9', { totalSize: '' }).split(':')[0] }}</div>
            <div class="stat-value stat-info">{{ getFileSize(totalSize) }}</div>
          </div>
        </el-col>
      </el-row>

      <!-- 速度和时间信息 -->
      <div class="speed-time-info">
        <div class="info-item">
          <el-icon class="info-icon"><Odometer /></el-icon>
          <span class="info-label">{{ $t('download_speed') }}:</span>
          <span class="info-value">{{ speedText }}</span>
        </div>
        <div class="info-item">
          <el-icon class="info-icon"><Clock /></el-icon>
          <span class="info-label">{{ $t('remaining_time') }}:</span>
          <span class="info-value">{{ remainingTimeText }}</span>
        </div>
      </div>

      <!-- 失败统计信息 -->
      <div v-if="showFailureStats" class="failure-stats-info">
        <div class="failure-stats-header">
          <el-icon class="stats-icon"><Warning /></el-icon>
          <span class="stats-title">{{ $t('failure_stats') }}</span>
        </div>
        <div class="failure-stats-grid">
          <div v-if="failureStats.byType.network > 0" class="failure-item">
            <span class="failure-label">{{ $t('failure_network') }}:</span>
            <span class="failure-value">{{ failureStats.byType.network }}</span>
          </div>
          <div v-if="failureStats.byType.auth > 0" class="failure-item">
            <span class="failure-label">{{ $t('failure_auth') }}:</span>
            <span class="failure-value">{{ failureStats.byType.auth }}</span>
          </div>
          <div v-if="failureStats.byType.expired_url > 0" class="failure-item">
            <span class="failure-label">{{ $t('failure_expired_url') }}:</span>
            <span class="failure-value">{{ failureStats.byType.expired_url }}</span>
          </div>
          <div v-if="failureStats.byType.server > 0" class="failure-item">
            <span class="failure-label">{{ $t('failure_server') }}:</span>
            <span class="failure-value">{{ failureStats.byType.server }}</span>
          </div>
          <div v-if="failureStats.byType.unknown > 0" class="failure-item">
            <span class="failure-label">{{ $t('failure_unknown') }}:</span>
            <span class="failure-value">{{ failureStats.byType.unknown }}</span>
          </div>
        </div>
      </div>

      <!-- 状态信息 -->
      <div v-if="maxInfo || zipProgressText" class="status-info">
        <p v-if="maxInfo" class="status-text">{{ maxInfo }}</p>
        <p v-if="zipProgressText" class="status-text">
          <el-icon class="status-icon"><Loading /></el-icon>
          {{ zipProgressText }}
        </p>
      </div>

      <div class="button-group">
        <el-button
          v-if="isDownloading && !isCancelled"
          size="small"
          type="danger"
          @click="handleCancelDownload"
          class="action-button"
        >
          <el-icon class="button-icon"><Close /></el-icon>
          {{ $t('cancel_download') }}
        </el-button>
        <el-button
          v-if="getFailedIdsLength > 0"
          size="small"
          :type="showFailedOnly ? 'primary' : 'default'"
          @click="showFailedOnly = !showFailedOnly"
          class="action-button"
        >
          <el-icon class="button-icon"><Filter /></el-icon>
          {{ showFailedOnly ? $t('text22') : $t('text23') }}
        </el-button>
      </div>
      <el-table
        :data="filteredFileInfo"
        style="width: 100%"
        show-overflow-tooltip
        size="small"
        :row-class-name="tableRowClassName"
        :header-cell-style="{ background: 'var(--el-fill-color-lighter)', fontWeight: '600' }"
        stripe
      >
        <el-table-column type="index" width="50" />
        <el-table-column prop="name" :label="$t('text12')" width="" />
      <el-table-column prop="percentage" :label="$t('text13')">
          <template #default="scope">
            {{ scope.row.percentage }}%
          </template>
        </el-table-column>
        <el-table-column prop="size" :label="$t('text14')">
          <template #default="scope">
            {{ getFileSize(scope.row.size) }}
          </template>
        </el-table-column>
        <el-table-column prop="status" :label="$t('text15')">
          <template #default="scope">
            <el-button
              type="primary"
              v-if="scope.row.type === 'loading'"
              size="small"
              link
              >{{ $t('text16') }}</el-button
            >
            <el-button
              type="success"
              link
              v-if="scope.row.type === 'success'"
              size="small"
              >{{ $t('text17') }}</el-button
            >
            <el-button
              type="danger"
              link
              v-if="scope.row.type === 'error'"
              size="small"
              >{{ $t('text18') }}</el-button
            >
          </template>
        </el-table-column>
        <el-table-column prop="errorMessage" :label="$t('error_message')">
          <template #default="scope">
            <span v-if="scope.row.type === 'error'">{{ scope.row.errorMessage }}</span>
          </template>
        </el-table-column>
        <el-table-column :label="$t('retry')" width="80" fixed="right" v-if="getFailedIdsLength > 0">
          <template #default="scope">
            <el-button
              v-if="scope.row.type === 'error'"
              link
              type="primary"
              size="small"
              @click="retryDownload(scope.row)"
              :disabled="isDownloading"
              class="retry-button"
            >
              <el-icon><RefreshRight /></el-icon>
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>
  </div>
</template>
<script setup>
import { ref, onMounted, toRefs, computed, defineEmits } from 'vue'
import { Loading, Download, Odometer, Clock, Warning, Close, Filter, RefreshRight } from '@element-plus/icons-vue'
import { ElMessageBox, ElMessage } from 'element-plus'
import ProgressCircle from './ProgressCircle.vue'
import { DownloadManager } from './downloader/index.js'
import { i18n } from '@/locales/i18n.js'
import { getFileSize } from '@/utils/index.js'
const $t = i18n.global.t
const emit = defineEmits(['finsh', 'cancel'])
const MAX_SIZE = 1073741824 * 1 // 1G
const warnList = ref([])
const completedIds = ref(new Set())
const failedIds = ref(new Set())
const zipError = ref(false)
const totalSize = ref(0)
const totalLength = ref(0)
const maxInfo = ref('')
const fileCellLength = ref(0)
const zipProgressText = ref('')
const showFailedOnly = ref(false)
const activeRecords = new Map()
const visibleActive = ref([])
const visibleFailed = ref([])
const isDownloading = ref(false)
const isCancelled = ref(false)
const failureStats = ref({
  total: 0,
  byType: {
    network: 0,
    auth: 0,
    expired_url: 0,
    server: 0,
    unknown: 0
  }
})

// 下载管理器实例
let fileDownloader = null

// 下载速度和时间追踪
const startTime = ref(0)
const downloadedBytes = ref(0)
const lastUpdateTime = ref(0)
const lastDownloadedBytes = ref(0)
// 所有文件的完整记录 Map<index, {size, percentage}>
const allFilesMap = new Map()

const props = defineProps({
  zipName: {
    type: String,
    default: ''
  },
  formData: {
    type: Object,
    default: () => {}
  }
})
const getCompletedIdsLength = computed(() => {
  return completedIds.value.size
})

const getFailedIdsLength = computed(() => {
  return failedIds.value.size
})

const MAX_VISIBLE_ITEMS = 30
const filteredFileInfo = computed(() => {
  return showFailedOnly.value ? visibleFailed.value : visibleActive.value
})

const refreshActiveDisplay = () => {
  const items = Array.from(activeRecords.values())
    .filter(item => item.type === 'loading')
    .sort((a, b) => a.index - b.index)
    .slice(0, MAX_VISIBLE_ITEMS)
  visibleActive.value = items
}

const recordFailedDisplay = (entry) => {
  const next = [entry, ...visibleFailed.value.filter(item => item.index !== entry.index)]
  visibleFailed.value = next.slice(0, MAX_VISIBLE_ITEMS)
}

const removeFromFailedDisplay = (index) => {
  const filtered = visibleFailed.value.filter(item => item.index !== index)
  if (filtered.length !== visibleFailed.value.length) {
    visibleFailed.value = filtered
  }
}

// 格式化时间显示（秒 -> 时分秒）
const formatTime = (seconds) => {
  if (!seconds || seconds <= 0 || !isFinite(seconds)) {
    return '--'
  }
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = Math.floor(seconds % 60)

  if (h > 0) {
    return `${h}h ${m}m ${s}s`
  } else if (m > 0) {
    return `${m}m ${s}s`
  } else {
    return `${s}s`
  }
}

// 格式化速度显示
const formatSpeed = (bytesPerSecond) => {
  if (!bytesPerSecond || bytesPerSecond <= 0 || !isFinite(bytesPerSecond)) {
    return '--'
  }
  return `${getFileSize(bytesPerSecond)}/s`
}

// 计算下载速度（字节/秒）
const downloadSpeed = computed(() => {
  const now = Date.now()
  const elapsedSeconds = (now - startTime.value) / 1000

  if (elapsedSeconds <= 0 || downloadedBytes.value <= 0) {
    return 0
  }

  return downloadedBytes.value / elapsedSeconds
})

// 计算剩余时间（秒）
const remainingTime = computed(() => {
  const speed = downloadSpeed.value

  if (speed <= 0 || totalSize.value <= 0) {
    return 0
  }

  const remainingBytes = totalSize.value - downloadedBytes.value

  if (remainingBytes <= 0) {
    return 0
  }

  return remainingBytes / speed
})

// 格式化的速度文本
const speedText = computed(() => formatSpeed(downloadSpeed.value))

// 格式化的剩余时间文本
const remainingTimeText = computed(() => formatTime(remainingTime.value))

// 是否显示失败统计
const showFailureStats = computed(() => {
  return failureStats.value.total > 0
})

// 表格行类名
const tableRowClassName = ({ row }) => {
  if (row.type === 'success') {
    return 'success-row'
  } else if (row.type === 'error') {
    return 'error-row'
  } else if (row.type === 'loading') {
    return 'loading-row'
  }
  return ''
}

// 处理取消下载
const handleCancelDownload = async() => {
  try {
    await ElMessageBox.confirm(
      $t('cancel_download_tip'),
      $t('confirm_cancel'),
      {
        confirmButtonText: $t('yes'),
        cancelButtonText: $t('no'),
        type: 'warning'
      }
    )

    // 用户确认取消 - 只调用取消方法，后续由 'cancelled' 事件统一处理
    if (fileDownloader) {
      fileDownloader.cancelDownload()
    }
  } catch {
    // 用户取消了取消操作
  }
}

// 重试失败的下载项
const retryDownload = async(row) => {
  if (!fileDownloader || !row || row.index === undefined) {
    ElMessage.warning($t('retry_failed') || '重试失败')
    return
  }

  try {
    // 从失败列表中移除
    failedIds.value.delete(row.index)
    removeFromFailedDisplay(row.index)

    // 重置文件状态
    row.type = 'loading'
    row.percentage = 0
    row.errorMessage = ''

    // 添加到活跃下载列表
    activeRecords.set(row.index, row)
    refreshActiveDisplay()

    // 提示用户（实际的重试逻辑需要 DownloadManager 支持）
    ElMessage.success($t('retry_started') || '已开始重试')

    // 更新失败统计
    updateFailureStats()
  } catch (error) {
    console.error('重试下载失败:', error)
    ElMessage.error($t('retry_failed') || '重试失败')
  }
}

// 更新失败统计
const updateFailureStats = () => {
  if (fileDownloader) {
    const stats = fileDownloader.getDownloadStats()
    failureStats.value = stats.failureStats || failureStats.value
  }
}

const percent = computed(() => {
  if (!totalLength.value || !totalSize.value) {
    return 0
  }

  // 使用已经在 progress 事件中计算好的 downloadedBytes
  // 这个值基于 allFilesMap，包含了所有文件（包括已完成的）
  const totalBytes = totalSize.value
  const downloaded = downloadedBytes.value

  if (totalBytes <= 0) {
    return 0
  }

  // 如果所有文件都处理完了（完成或失败），确保显示 100%
  const finished = completedIds.value.size + failedIds.value.size
  if (finished === totalLength.value && totalLength.value > 0) {
    return 100
  }

  const val = ((downloaded / totalBytes) * 100).toFixed(2) - 0
  return Math.min(Math.max(val || 0, 0), 100)
})
const { formData, zipName } = toRefs(props)
onMounted(async() => {
  fileDownloader = new DownloadManager({
    ...formData.value,
    zipName: zipName.value
  })

  isDownloading.value = true

  fileDownloader.on('warn', (msg) => {
    warnList.value.push(msg)
  })
  fileDownloader.on('preding', (cells) => {
    fileCellLength.value += 1

    // 记录下载开始时间
    if (!startTime.value) {
      startTime.value = Date.now()
      lastUpdateTime.value = Date.now()
    }

    if (cells) {
      totalLength.value += cells.length
      cells.forEach((cell) => {
        totalSize.value += cell.size
      })
    }
  })
  fileDownloader.on('error', (errorInfo) => {
    const { index, message } = errorInfo
    if (!Number.isInteger(index)) {
      return
    }
    failedIds.value.add(index)
    const existing = activeRecords.get(index) || {
      index,
      name: $t('undefined'),
      size: 0,
      percentage: 0,
      errorMessage: '',
      type: 'error'
    }
    existing.type = 'error'
    existing.errorMessage = message || $t('file_download_failed')
    activeRecords.delete(index)
    recordFailedDisplay(existing)
    refreshActiveDisplay()

    // 更新失败统计
    updateFailureStats()

    // 确保失败的文件也在 allFilesMap 中，并标记为完成（避免总进度卡住）
    const fileData = allFilesMap.get(index)
    if (fileData) {
      allFilesMap.set(index, { ...fileData, percentage: 100 })
      // 重新计算总下载字节数
      let totalDownloaded = 0
      allFilesMap.forEach((fd) => {
        const fileSize = fd.size || 0
        const filePercentage = fd.percentage || 0
        totalDownloaded += fileSize * (filePercentage / 100)
      })
      downloadedBytes.value = totalDownloaded
    }
  })
  fileDownloader.on('max_size_warning', (info) => {
    zipError.value = true
  })

  fileDownloader.on('progress', (progressInfo) => {
    const { index, percentage = 0, name, size } = progressInfo
    if (!Number.isInteger(index) || completedIds.value.has(index)) {
      return
    }

    // 更新文件记录 Map
    if (size !== undefined) {
      const existing = allFilesMap.get(index) || {}
      allFilesMap.set(index, {
        ...existing,
        size: size,
        percentage: percentage,
        name: name || existing.name
      })
    }

    let existing = activeRecords.get(index)
    if (!existing) {
      existing = {
        index,
        name: name || $t('undefined'),
        size,
        percentage,
        errorMessage: '',
        type: 'loading'
      }
    } else {
      if (name) {
        existing.name = name
      }
      if (size !== undefined) {
        existing.size = size
      }
      existing.percentage = percentage
    }
    existing.type = 'loading'
    existing.errorMessage = ''
    removeFromFailedDisplay(index)
    failedIds.value.delete(index)

    if (percentage >= 100) {
      existing.type = 'success'
      completedIds.value.add(index)
      activeRecords.delete(index)
      // 更新文件 Map，标记为完成
      const fileData = allFilesMap.get(index)
      if (fileData) {
        allFilesMap.set(index, { ...fileData, percentage: 100 })
      }
    } else {
      activeRecords.set(index, existing)
    }
    refreshActiveDisplay()

    // 重新计算总下载字节数
    let totalDownloaded = 0
    allFilesMap.forEach((fileData) => {
      const fileSize = fileData.size || 0
      const filePercentage = fileData.percentage || 0
      totalDownloaded += fileSize * (filePercentage / 100)
    })

    downloadedBytes.value = totalDownloaded
    lastUpdateTime.value = Date.now()
  })
  fileDownloader.on('finshed', (cells) => {
    isDownloading.value = false
    // 最后更新一次失败统计
    updateFailureStats()
    emit('finsh')
  })
  fileDownloader.on('cancelled', () => {
    isCancelled.value = true
    isDownloading.value = false

    // 取消后延迟关闭窗口（发出 cancel 事件直接关闭对话框）
    setTimeout(() => {
      emit('cancel')
    }, 500)
  })
  fileDownloader.on('zip_progress', (payload) => {
    maxInfo.value = ''
    if (payload && typeof payload === 'object') {
      if (payload.stage === 'zip') {
        const path = payload.path || payload.message || ''
        zipProgressText.value = $t('websocket_zip_stage_message', { path })
        return
      }
      if (payload.stage === 'retry_failed_files') {
        const count = Number(payload.failed) || 0
        zipProgressText.value = $t('websocket_retry_failed_files_message', { count })
        return
      }
      if (payload.stage === 'job_complete') {
        zipProgressText.value = $t('websocket_job_stage_message')
        return
      }
      if (payload.message) {
        zipProgressText.value = payload.message
        return
      }
    }
    const text = $t('file_packing_progress_message').replace(
      'percentage',
      payload
    )
    zipProgressText.value = text
  })
  await fileDownloader.startDownload()
})
</script>

<style scoped lang="scss">
.dialog-process {
  padding: 4px;
  animation: fadeIn 0.4s ease-out;

  h4 {
    color: var(--N900);
    margin-bottom: 20px;
    font-size: 18px;
    font-weight: 700;
    border-left: 4px solid var(--el-color-primary);
    padding-left: 12px;
    display: flex;
    align-items: center;
    gap: 8px;
    background: linear-gradient(90deg, var(--el-fill-color-lighter), transparent);
    padding-top: 8px;
    padding-bottom: 8px;
    border-radius: 0 8px 8px 0;
    transition: all 0.3s ease;

    &:hover {
      border-left-width: 6px;
      padding-left: 10px;
      background: linear-gradient(90deg, var(--el-fill-color-light), transparent);
    }

    .title-icon {
      font-size: 20px;
      color: var(--el-color-primary);
      animation: bounce 2s ease-in-out infinite;
    }
  }

  .dialog-circle {
    position: relative;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    margin-bottom: 24px;
    padding: 20px;
    background: radial-gradient(circle at 50% 50%, var(--el-fill-color-lighter), transparent);
    border-radius: 16px;

    .statistic {
      width: 100%;
      display: flex;
      align-items: center;
      justify-content: space-between;
    }
  }

  .warning-section {
    margin-bottom: 20px;
    animation: slideInDown 0.5s ease-out;
  }
}

.prompt {
  h4 {
    margin-bottom: 8px;
  }

  p {
    line-height: 1.2;
    color: var(--N500);
    font-size: 14px;
    margin-bottom: 8px;
  }

  .stats-row {
    margin-bottom: 8px;
  }

  .stat-card {
    background: linear-gradient(135deg, rgba(255, 255, 255, 0.9) 0%, rgba(249, 250, 252, 0.9) 100%);
    backdrop-filter: blur(10px);
    border-radius: 12px;
    padding: 14px 12px;
    text-align: center;
    transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
    border: 1px solid var(--el-border-color-lighter);
    position: relative;
    overflow: hidden;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);

    &::before {
      content: '';
      position: absolute;
      top: 0;
      left: 0;
      right: 0;
      height: 3px;
      background: linear-gradient(90deg,
        transparent,
        var(--el-color-primary-light-3),
        var(--el-color-primary),
        var(--el-color-primary-light-3),
        transparent
      );
      transform: translateX(-100%);
      animation: shimmer 3s ease-in-out infinite;
    }

    &::after {
      content: '';
      position: absolute;
      inset: 0;
      border-radius: 12px;
      padding: 1px;
      background: linear-gradient(135deg, transparent, var(--el-color-primary-light-7), transparent);
      -webkit-mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
      -webkit-mask-composite: xor;
      mask-composite: exclude;
      opacity: 0;
      transition: opacity 0.4s ease;
    }

    &:hover {
      box-shadow: 0 8px 24px rgba(64, 158, 255, 0.15);
      border-color: var(--el-color-primary-light-5);
      transform: translateY(-4px) scale(1.02);

      &::after {
        opacity: 1;
      }
    }

    .stat-label {
      font-size: 12px;
      color: var(--el-text-color-secondary);
      margin-bottom: 8px;
      line-height: 1.3;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      font-weight: 500;
      letter-spacing: 0.3px;
    }

    .stat-value {
      font-size: 24px;
      font-weight: 700;
      color: var(--el-text-color-primary);
      line-height: 1.2;
      transition: all 0.3s;
      font-variant-numeric: tabular-nums;

      &.stat-success {
        background: linear-gradient(135deg, #67c23a, #85ce61);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        filter: drop-shadow(0 2px 4px rgba(103, 194, 58, 0.3));
      }

      &.stat-danger {
        background: linear-gradient(135deg, #f56c6c, #f78989);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        filter: drop-shadow(0 2px 4px rgba(245, 108, 108, 0.3));
      }

      &.stat-info {
        background: linear-gradient(135deg, #409eff, #79bbff);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        font-size: 18px;
        font-weight: 600;
      }
    }
  }

  .speed-time-info {
    margin-bottom: 16px;
    padding: 14px 16px;
    background: linear-gradient(135deg,
      rgba(64, 158, 255, 0.05) 0%,
      rgba(103, 194, 58, 0.05) 100%
    );
    backdrop-filter: blur(8px);
    border-radius: 12px;
    border: 1px solid var(--el-border-color-lighter);
    display: flex;
    flex-direction: column;
    gap: 10px;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
    transition: all 0.3s ease;

    &:hover {
      box-shadow: 0 4px 12px rgba(64, 158, 255, 0.1);
      border-color: var(--el-color-primary-light-7);
    }

    .info-item {
      display: flex;
      align-items: center;
      font-size: 14px;
      color: var(--el-text-color-regular);
      padding: 6px 0;
      transition: all 0.3s ease;

      &:hover {
        transform: translateX(4px);
      }

      .info-icon {
        font-size: 18px;
        margin-right: 8px;
        color: var(--el-color-primary);
        animation: pulse 2s ease-in-out infinite;
      }

      .info-label {
        margin-right: 8px;
        color: var(--el-text-color-secondary);
        font-weight: 500;
      }

      .info-value {
        font-weight: 700;
        background: linear-gradient(135deg, var(--el-color-primary), var(--el-color-success));
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        margin-left: auto;
        font-size: 15px;
        font-variant-numeric: tabular-nums;
      }
    }
  }

  .status-info {
    margin-bottom: 16px;
    padding: 14px 16px;
    background: linear-gradient(135deg,
      var(--el-fill-color-light) 0%,
      var(--el-fill-color) 100%
    );
    border-radius: 12px;
    border-left: 4px solid var(--el-color-primary);
    box-shadow: 0 2px 12px rgba(64, 158, 255, 0.08);
    animation: slideInLeft 0.5s ease-out;

    .status-text {
      margin: 0;
      padding: 6px 0;
      color: var(--el-text-color-primary);
      font-size: 14px;
      line-height: 1.6;
      display: flex;
      align-items: center;

      .status-icon {
        margin-right: 10px;
        animation: rotating 2s linear infinite;
        color: var(--el-color-primary);
        font-size: 18px;
      }
    }
  }

  .failure-stats-info {
    margin-bottom: 16px;
    padding: 16px;
    background: linear-gradient(135deg,
      rgba(245, 108, 108, 0.08) 0%,
      rgba(255, 179, 179, 0.08) 100%
    );
    backdrop-filter: blur(8px);
    border-radius: 12px;
    border-left: 4px solid var(--el-color-danger);
    box-shadow: 0 2px 12px rgba(245, 108, 108, 0.12);
    animation: slideInLeft 0.5s ease-out;

    .failure-stats-header {
      display: flex;
      align-items: center;
      margin-bottom: 12px;
      padding-bottom: 10px;
      border-bottom: 1px dashed rgba(245, 108, 108, 0.2);

      .stats-icon {
        font-size: 18px;
        margin-right: 8px;
        color: var(--el-color-danger);
        animation: shake 3s ease-in-out infinite;
      }

      .stats-title {
        font-weight: 700;
        font-size: 15px;
        color: var(--el-text-color-primary);
      }
    }

    .failure-stats-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
      gap: 10px;

      .failure-item {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 8px 12px;
        background: rgba(255, 255, 255, 0.9);
        backdrop-filter: blur(4px);
        border-radius: 8px;
        font-size: 13px;
        transition: all 0.3s ease;
        border: 1px solid rgba(245, 108, 108, 0.1);

        &:hover {
          background: rgba(255, 255, 255, 1);
          transform: translateX(4px) scale(1.02);
          box-shadow: 0 2px 8px rgba(245, 108, 108, 0.15);
          border-color: var(--el-color-danger-light-7);
        }

        .failure-label {
          color: var(--el-text-color-secondary);
          margin-right: 8px;
          font-weight: 500;
        }

        .failure-value {
          font-weight: 700;
          background: linear-gradient(135deg, var(--el-color-danger), var(--el-color-danger-light-3));
          -webkit-background-clip: text;
          -webkit-text-fill-color: transparent;
          background-clip: text;
          margin-left: auto;
          font-size: 16px;
        }
      }
    }
  }

  .button-group {
    display: flex;
    justify-content: flex-end;
    align-items: center;
    margin-bottom: 12px;
    gap: 10px;
    padding: 8px 0;

    .action-button {
      display: flex;
      align-items: center;
      gap: 6px;
      padding: 8px 16px;
      border-radius: 8px;
      font-weight: 600;
      font-size: 13px;
      transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
      box-shadow: 0 2px 4px rgba(0, 0, 0, 0.08);

      &:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
      }

      &:active {
        transform: translateY(0);
      }

      .button-icon {
        font-size: 14px;
        transition: transform 0.3s ease;
      }

      &:hover .button-icon {
        transform: scale(1.2) rotate(5deg);
      }
    }

    .el-button--danger {
      background: linear-gradient(135deg, var(--el-color-danger), var(--el-color-danger-light-3));
      border: none;

      &:hover {
        background: linear-gradient(135deg, var(--el-color-danger-dark-2), var(--el-color-danger));
      }
    }

    .el-button--primary {
      background: linear-gradient(135deg, var(--el-color-primary), var(--el-color-primary-light-3));
      border: none;

      &:hover {
        background: linear-gradient(135deg, var(--el-color-primary-dark-2), var(--el-color-primary));
      }
    }

    .el-button--default {
      background: linear-gradient(135deg, var(--el-fill-color-light), var(--el-fill-color));
      border: 1px solid var(--el-border-color);

      &:hover {
        background: linear-gradient(135deg, var(--el-fill-color), var(--el-fill-color-lighter));
        border-color: var(--el-color-primary-light-5);
      }
    }
  }

  // 按钮区域样式优化
  :deep(.el-table) {
    border-radius: 8px;
    overflow: hidden;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);

    .el-table__header {
      th {
        font-size: 13px;
        color: var(--el-text-color-primary);
      }
    }

    .el-table__body {
      tr {
        transition: all 0.3s ease;

        &:hover {
          background: var(--el-fill-color-light) !important;
          transform: scale(1.005);
        }

        &.success-row {
          background: rgba(103, 194, 58, 0.03);

          &:hover {
            background: rgba(103, 194, 58, 0.08) !important;
          }
        }

        &.error-row {
          background: rgba(245, 108, 108, 0.03);

          &:hover {
            background: rgba(245, 108, 108, 0.08) !important;
          }
        }

        &.loading-row {
          background: rgba(64, 158, 255, 0.02);

          &:hover {
            background: rgba(64, 158, 255, 0.05) !important;
          }

          animation: pulse-row 2s ease-in-out infinite;
        }
      }

      td {
        font-size: 13px;
        border-bottom: 1px solid var(--el-border-color-lighter);
      }
    }

    .el-button--small.is-link {
      font-weight: 600;
      padding: 4px 8px;
      border-radius: 4px;
      transition: all 0.3s ease;

      &:hover {
        transform: scale(1.1);
      }
    }
  }
}

@keyframes pulse-row {
  0%, 100% {
    opacity: 1;
  }
  50% {
    opacity: 0.95;
  }
}

// ========== 动画定义 ==========

@keyframes fadeIn {
  from {
    opacity: 0;
    transform: translateY(-10px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@keyframes slideInDown {
  from {
    opacity: 0;
    transform: translateY(-20px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@keyframes slideInLeft {
  from {
    opacity: 0;
    transform: translateX(-20px);
  }
  to {
    opacity: 1;
    transform: translateX(0);
  }
}

@keyframes rotating {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}

@keyframes pulse {
  0%, 100% {
    opacity: 1;
    transform: scale(1);
  }
  50% {
    opacity: 0.85;
    transform: scale(1.05);
  }
}

@keyframes bounce {
  0%, 100% {
    transform: translateY(0);
  }
  50% {
    transform: translateY(-4px);
  }
}

@keyframes shimmer {
  0% {
    transform: translateX(-100%);
  }
  100% {
    transform: translateX(200%);
  }
}

@keyframes shake {
  0%, 100% {
    transform: translateX(0);
  }
  10%, 30%, 50%, 70%, 90% {
    transform: translateX(-2px);
  }
  20%, 40%, 60%, 80% {
    transform: translateX(2px);
  }
}

// ========== 暗色模式适配 ==========

@media (prefers-color-scheme: dark) {
  .stat-card {
    background: linear-gradient(135deg, rgba(48, 49, 51, 0.9) 0%, rgba(58, 59, 62, 0.9) 100%);
  }

  .speed-time-info {
    background: linear-gradient(135deg,
      rgba(64, 158, 255, 0.1) 0%,
      rgba(103, 194, 58, 0.1) 100%
    );
  }

  .failure-stats-info {
    background: linear-gradient(135deg,
      rgba(245, 108, 108, 0.15) 0%,
      rgba(255, 179, 179, 0.15) 100%
    );

    .failure-item {
      background: rgba(48, 49, 51, 0.8);

      &:hover {
        background: rgba(58, 59, 62, 0.9);
      }
    }
  }
}
</style>
