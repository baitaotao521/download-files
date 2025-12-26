<template>
  <div class="dialog-process">
    <h4>{{ $t("download_progress") }}</h4>
    <div class="dialog-circle">
      <ProgressCircle :percent="percent" />
    </div>
    <h4>{{ $t("download_details") }}</h4>
    <div class="prompt">
     <p  v-if="totalSize>MAX_SIZE" style="color: var(--el-color-warning);line-height: 1.5;">{{ $t('text7') }}</p>
     <template v-if="warnList.length">
      <p v-for="item in warnList" :key="item" style="color: var(--el-color-warning);line-height: 1.5;">{{ item }}</p>
     </template>
      <!-- <p>已找到{{ fileCellLength }}个单元格</p> -->

      <p> {{ $t('text8',{totalLength}) }}</p>
      <p> {{ $t('text9',{totalSize:getFileSize(totalSize)})}}</p>
      <p> {{ $t('text10',{getCompletedIdsLength})}}</p>
      <p style="color:red" v-if="getFailedIdsLength > 0">{{ $t('text21',{failedCount: getFailedIdsLength})}}</p>
      <p>{{ maxInfo }}</p>
      <p>{{ zipProgressText }}</p>
      <p style="color:red" v-if="!!zipError">{{ $t('text11') }}</p>

      <div style="display: flex; justify-content: flex-end; align-items: center; margin-bottom: 8px;">
        <el-button
          v-if="getFailedIdsLength > 0"
          size="small"
          :type="showFailedOnly ? 'primary' : 'default'"
          @click="showFailedOnly = !showFailedOnly"
        >
          {{ showFailedOnly ? $t('text22') : $t('text23') }}
        </el-button>
      </div>
      <el-table
        :data="filteredFileInfo"
        style="width: 100%"
        show-overflow-tooltip
        size="small"
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
      </el-table>
    </div>
  </div>
</template>
<script setup>
import { ref, onMounted, toRefs, computed, defineEmits } from 'vue'
import ProgressCircle from './ProgressCircle.vue'
import FileDownloader from './downFiles.js'
import { i18n } from '@/locales/i18n.js'
import { getFileSize } from '@/utils/index.js'
const $t = i18n.global.t
const emit = defineEmits(['finsh'])
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

const percent = computed(() => {
  const finished = getCompletedIdsLength.value + getFailedIdsLength.value
  if (!totalLength.value) {
    return 0
  }
  const val = ((finished / totalLength.value) * 100).toFixed(2) - 0
  return val || 0
})
const { formData, zipName } = toRefs(props)
onMounted(async() => {
  const fileDownloader = new FileDownloader({
    ...formData.value,
    zipName: zipName.value
  })
  fileDownloader.on('warn', (msg) => {
    warnList.value.push(msg)
  })
  fileDownloader.on('preding', (cells) => {
    fileCellLength.value += 1

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
  })
  fileDownloader.on('max_size_warning', (info) => {
    zipError.value = true
  })

  fileDownloader.on('progress', (progressInfo) => {
    const { index, percentage = 0, name, size } = progressInfo
    if (!Number.isInteger(index) || completedIds.value.has(index)) {
      return
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
    } else {
      activeRecords.set(index, existing)
    }
    refreshActiveDisplay()
  })
  fileDownloader.on('finshed', (cells) => {
    emit('finsh')
  })
  fileDownloader.on('zip_progress', (payload) => {
    maxInfo.value = ''
    if (payload && typeof payload === 'object') {
      if (payload.stage === 'zip') {
        const path = payload.path || payload.message || ''
        zipProgressText.value = $t('websocket_zip_stage_message', { path })
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
  h4 {
    color: var(--N900);
    margin-bottom: 16px;
    font-size: 16px;
    border-left: 3px solid var(--el-color-primary);
    padding-left: 8px;
  }

  .dialog-circle {
    position: relative;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    margin-bottom: 16px;

    .statistic {
      width: 100%;
      display: flex;
      align-items: center;
      justify-content: space-between;
    }
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
}

</style>
