<template>
  <div v-loading="loading" class="form-container">
    <el-form
      ref="elform"
      class="form"
      :model="formData"
      :rules="rules"
      label-width="auto"
      :scroll-into-view-options="true"
      :label-position="'left'"
      v-if="!loading"
    >
      <el-form-item :label="$t('data_table_column')" prop="tableId">
        <el-select
          v-model="formData.tableId"
          :placeholder="$t('select_data_table')"
          style="width: 100%"
        >
          <el-option
            v-for="meta in datas.allInfo"
            :key="meta.tableId"
            :label="meta.tableName"
            :value="meta.tableId"
          />
        </el-select>
      </el-form-item>
      <el-form-item :label="$t('view_column')" prop="viewId">
        <template #label>
          <p style="display: flex; align-items: center">
            <span style="margin-right: 2px">{{ $t("view_column") }}</span>
            <el-popover
              placement="top-start"
              trigger="hover"
              :content="$t('text1')"
            >
              <template #reference>
                <el-icon>
                  <InfoFilled />
                </el-icon>
              </template>
            </el-popover>
          </p>
        </template>
        <el-select
          v-model="formData.viewId"
          :placeholder="$t('select_view')"
          style="width: 100%"
        >
          <el-option
            v-for="meta in viewList"
            :key="meta.id"
            :label="meta.name"
            :value="meta.id"
          />
        </el-select>
      </el-form-item>
      <el-form-item :label="$t('attachment_fields')" prop="attachmentFileds">
        <el-select
          v-model="formData.attachmentFileds"
          multiple
          :placeholder="$t('select_attachment_fields')"
          style="width: 100%"
        >
          <el-option
            v-for="meta in attachmentList"
            :key="meta.id"
            :label="meta.name"
            :value="meta.id"
          />
        </el-select>
      </el-form-item>

      <el-form-item :label="$t('file_naming_method')" prop="fileNameType">
        <el-select
          v-model="formData.fileNameType"
          :placeholder="$t('select_file_naming_method')"
          style="width: 100%"
        >
          <el-option :label="$t('original_file_name')" :value="0" />
          <el-option :label="$t('select_from_table_fields')" :value="1" />
        </el-select>
      </el-form-item>
      <el-form-item
        :label="$t('file_name_field')"
        prop="fileNameByField"
        v-if="formData.fileNameType === 1"
      >
        <template #label>
          <p style="display: flex; align-items: center">
            <span style="margin-right: 2px">{{ $t("file_name_field") }}</span>
            <el-popover
              placement="top-start"
              trigger="hover"
              :content="$t('text2')"
            >
              <template #reference>
                <el-icon>
                  <InfoFilled />
                </el-icon>
              </template>
            </el-popover>
          </p>
        </template>
        <el-select
          v-model="formData.fileNameByField"
          :placeholder="$t('select_file_name_field')"
          style="width: 100%"
          multiple
        >
          <el-option
            :label="item.name"
            :value="item.id"
            v-for="(item, index) in singleSelectList"
            :key="item.id"
          />
        </el-select>
      </el-form-item>
      <el-form-item
        :label="$t('text3')"
        prop="fileNameByField"
        v-if="
          formData.fileNameType === 1 && formData.fileNameByField.length > 1
        "
      >
        <template #label>
          <p style="display: flex; align-items: center">
            <span style="margin-right: 2px">{{ $t('text3') }}</span>
            <el-popover
              placement="top-start"
              trigger="hover"
              :content="$t('text4')"
            >
              <template #reference>
                <el-icon>
                  <InfoFilled />
                </el-icon>
              </template>
            </el-popover>
          </p>
        </template>
        <draggable :list="formData.fileNameByField" animation="300">
          <template #item="{ element }">
            <div class="drag-item">
              <el-icon>
                <Tickets />
              </el-icon>
              {{ getSingleSelectListName(element) }}
            </div>
          </template>
        </draggable>
      </el-form-item>
      <el-form-item
        :label="$t('text5')"
        prop="nameMark"
        v-if="
          formData.fileNameType === 1 && formData.fileNameByField.length > 1
        "
      >
        <template #label>
          <p style="display: flex; align-items: center">
            <span style="margin-right: 2px">{{ $t('text5') }}</span>
            <el-popover
              placement="top-start"
              trigger="hover"
              :content="$t('text6')"
            >
              <template #reference>
                <el-icon>
                  <InfoFilled />
                </el-icon>
              </template>
            </el-popover>
          </p>
        </template>
        <el-input v-model="formData.nameMark" />
      </el-form-item>
        <el-form-item :label="$t('download_channel')" prop="downloadChannel">
          <el-select
            v-model="formData.downloadChannel"
            :placeholder="$t('select_download_channel')"
            style="width: 100%"
          >
            <el-option :label="$t('download_channel_browser')" value="browser" />
            <el-option :label="$t('download_channel_ws')" value="websocket" />
            <el-option :label="$t('download_channel_ws_auth')" value="websocket_auth" />
          </el-select>
          <p v-if="requiresDesktopClient" class="advanced-tip" style="margin-top: 8px;">
            <a
              class="advanced-link"
              :href="desktopUsageGuideUrl"
              target="_blank"
              rel="noopener noreferrer"
            >{{ $t('desktop_usage_guide') }}</a>
          </p>
        </el-form-item>

        <el-form-item
          v-if="!requiresDesktopClient"
          :label="$t('download_method')"
          prop="downloadType"
        >
          <el-select
            v-model="formData.downloadType"
            :placeholder="$t('select_download_method')"
            style="width: 100%"
          >
            <el-option :label="$t('download_individual_files')" :value="2" />
            <el-option :label="$t('zip_download')" :value="1" />
          </el-select>
        </el-form-item>
        <el-form-item
          v-if="requiresDesktopClient"
          :label="$t('zip_after_download')"
          prop="zipAfterDownload"
        >
          <el-switch
            v-model="formData.zipAfterDownload"
            :active-text="$t('yes')"
            :inactive-text="$t('no')"
          />
        </el-form-item>
<!--      <el-form-item-->
<!--        :label="$t('text24')"-->
<!--        prop="concurrentDownloads"-->
<!--        v-if="formData.downloadType === 1"-->
<!--      >-->
<!--        <template #label>-->
<!--          <p style="display: flex; align-items: center">-->
<!--            <span style="margin-right: 2px">{{ $t('text24') }}</span>-->
<!--            <el-popover-->
<!--              placement="top-start"-->
<!--              trigger="hover"-->
<!--              :content="$t('text25')"-->
<!--            >-->
<!--              <template #reference>-->
<!--                <el-icon>-->
<!--                  <InfoFilled />-->
<!--                </el-icon>-->
<!--              </template>-->
<!--            </el-popover>-->
<!--          </p>-->
<!--        </template>-->
<!--        <el-input-number-->
<!--          v-model="formData.concurrentDownloads"-->
<!--          :min="1"-->
<!--          :max="100"-->
<!--          :step="1"-->
<!--          style="width: 100%"-->
<!--        />-->
<!--      </el-form-item>-->
        <div style="display: flex">
          <el-form-item
            prop="downloadTypeByFolders"
            v-if="folderClassificationAvailable"
          >
            <template #label>
              <p style="display: flex; align-items: center">
                <span style="margin-right: 2px">{{
                  $t("folder_classification")
              }}</span>
              <el-popover
                placement="top-start"
                trigger="hover"
                :content="$t('folder_classification_hint')"
              >
                <template #reference>
                  <el-icon>
                    <InfoFilled />
                  </el-icon>
                </template>
              </el-popover>
            </p>
          </template>
          <el-switch
            v-model="formData.downloadTypeByFolders"
            :active-text="$t('yes')"
            :inactive-text="$t('no')"
          />
        </el-form-item>
      </div>

        <el-form-item
          :label="$t('first_directory')"
          prop="firstFolderKey"
          v-if="folderClassificationAvailable && formData.downloadTypeByFolders"
        >
          <el-select
            v-model="formData.firstFolderKey"
            :placeholder="$t('select_first_directory')"
            style="width: 100%"
          clearable
        >
          <el-option
            v-for="meta in singleSelectList"
            :key="meta.id"
            :label="meta.name"
            :value="meta.id"
          />
        </el-select>
      </el-form-item>
        <el-form-item
          :label="$t('second_directory')"
          prop="secondFolderKey"
          v-if="folderClassificationAvailable && formData.downloadTypeByFolders"
        >
          <el-select
            clearable
            v-model="formData.secondFolderKey"
          :placeholder="$t('select_second_directory')"
          style="width: 100%"
        >
          <el-option
            v-for="meta in singleSelectList"
            :key="meta.id"
            :label="meta.name"
            :value="meta.id"
          />
        </el-select>
      </el-form-item>

      <div v-if="requiresDesktopClient">
        <el-collapse v-model="advancedPanels" class="advanced-collapse">
          <el-collapse-item :title="$t('advanced_settings_title')" name="ws">
            <p class="advanced-tip">
              {{ $t('advanced_settings_desc') }}
            </p>
            <el-form-item
              :label="$t('websocket_host')"
              prop="wsHost"
            >
              <el-input
                v-model="formData.wsHost"
                :placeholder="$t('websocket_host_placeholder')"
              />
            </el-form-item>
            <el-form-item
              :label="$t('websocket_port')"
              prop="wsPort"
            >
              <el-input-number
                v-model="formData.wsPort"
                :min="1"
                :max="65535"
                :placeholder="$t('websocket_port_placeholder')"
                style="width: 100%"
              />
            </el-form-item>
            <el-form-item
              v-if="formData.downloadChannel === 'websocket_auth'"
              :label="$t('token_push_batch_label')"
              prop="tokenPushBatchSize"
            >
              <el-input-number
                v-model="formData.tokenPushBatchSize"
                :min="1"
                :max="10000"
                style="width: 100%"
              />
              <p class="advanced-tip">
                {{ $t('token_push_batch_hint') }}
              </p>
            </el-form-item>
          </el-collapse-item>
        </el-collapse>
      </div>

      <div class="btns">
        <el-button class="btn-select" @click="downloadSelectedRecords">
          {{ $t('download_selected_records') }}
        </el-button>
        <el-button class="btn-download" type="primary" @click="downloadAllRecords">
          {{ $t('download_all_records') }}
          <el-icon>
            <Download />
          </el-icon>
        </el-button>
      </div>
    </el-form>
    <el-dialog
      v-model="confirmSelectedDialogVis"
      :title="$t('confirm_dialog_title')"
      width="min(360px, 90vw)"
      :close-on-click-modal="false"
      :close-on-press-escape="false"
      :append-to-body="true"
      :show-close="true"
      class="confirm-selected-dialog"
    >
      <template #header>
        <div class="confirm-dialog__header">
          <el-icon class="confirm-dialog__icon">
            <WarningFilled />
          </el-icon>
          <div class="confirm-dialog__header-text">
            <p class="confirm-dialog__title">{{ $t('confirm_dialog_title') }}</p>
            <p class="confirm-dialog__subtitle">{{ $t('download_selected_records') }}</p>
          </div>
        </div>
      </template>
      <div class="confirm-dialog__content">
        <p class="confirm-dialog__desc">
          {{ $t('confirm_download_selected', { count: pendingSelectedIds.length }) }}
        </p>
        <div class="confirm-dialog__summary">
          <span class="confirm-dialog__summary-label">{{ $t('download_selected_records') }}</span>
          <span class="confirm-dialog__summary-value">{{ pendingSelectedIds.length }}</span>
        </div>
      </div>
      <template #footer>
        <div class="dialog-footer-actions">
          <el-button @click="confirmSelectedDialogVis = false">{{ $t('no') }}</el-button>
          <el-button type="primary" @click="confirmSelectedDownload">{{ $t('yes') }}</el-button>
        </div>
      </template>
    </el-dialog>
    <el-dialog
      v-model="downModelVis"
      :title="$t('file_download')"
      width="80%"
      :close-on-click-modal="false"
      :close-on-press-escape="false"
      :append-to-body="true"
    >
      <DownModel
        v-if="downModelVis"
        :formData="formData"
        @finsh="datas.finshDownload = true"
        @cancel="downModelVis = false"
        :zipName="activeTableInfo.tableName"
      />
      <template #footer v-if="datas.finshDownload">
        <span class="dialog-footer">
          <el-button @click="downModelVis = false">{{
            $t("complete")
          }}</el-button>
        </span>
      </template>
    </el-dialog>
  </div>
</template>
<script setup>
import { ref, onMounted, reactive, toRefs, watch, computed } from 'vue'
import { bitable, FieldType, base, PermissionEntity, OperationType } from '@lark-base-open/js-sdk'

import { Download, InfoFilled, Tickets, WarningFilled } from '@element-plus/icons-vue'
import { ElMessageBox } from 'element-plus'
import DownModel from './DownModel.vue'
import draggable from 'vuedraggable'

import { SUPPORT_TYPES, getInfoByTableMetaList, sortByOrder } from '@/hooks/useBitable.js'
import { i18n } from '@/locales/i18n.js'
import { compareSemanticVersions } from '@/utils/index.js'

const $t = i18n.global.t
const desktopUsageGuideUrl =
  'https://p6bgwki4n6.feishu.cn/docx/Pn7Kdw2rPocwPZxVfF5cMsAcnle#share-P1DidKxwIoVRO9xruLecXk4snLV'
const MIN_DESKTOP_CLIENT_VERSION = '1.1.8'
const DESKTOP_CLIENT_UPDATE_URL =
  'https://xcnfciyevzhz.feishu.cn/wiki/J9bdwozIViVC4ZkOuKAcSbAQnKQ'
const WEBSOCKET_ACK_TYPE = 'feishu_attachment_ack'
const WEBSOCKET_PROBE_TYPE = 'feishu_attachment_probe'
const WEBSOCKET_CONFIG_TYPE = 'feishu_attachment_config'
const elform = ref(null)
const loading = ref(true)
const downModelVis = ref(false)
const confirmSelectedDialogVis = ref(false)
const pendingSelectedIds = ref([])
const advancedPanels = ref([])
const desktopChannels = ['websocket', 'websocket_auth']
const formData = reactive({
  tableId: '',
  attachmentFileds: [],
  fileNameType: 0,
  fileNameByField: [],
  nameMark: '-',
  viewId: '',
  downloadChannel: 'browser',
  downloadType: 1,
  zipAfterDownload: false,
  downloadTypeByFolders: false,
  firstFolderKey: '',
  secondFolderKey: '',
  wsHost: '127.0.0.1',
  wsPort: 11548,
  tokenPushBatchSize: 50,
  appToken: '',
  selectedRecordIds: []
})
const requiresDesktopClient = computed(() => desktopChannels.includes(formData.downloadChannel))
const folderClassificationAvailable = computed(() => {
  if (requiresDesktopClient.value) {
    return true
  }
  return formData.downloadType === 1
})
const rules = reactive({
  tableId: [
    {
      required: true,
      message: '请选择数据表',
      trigger: 'change'
    }
  ],
  attachmentFileds: [
    {
      required: true,
      message: '请选择附件字段',
      trigger: 'change'
    }
  ],
  viewId: [
    {
      required: true,
      message: '请选择视图',
      trigger: 'change'
    }
  ],
  fileNameType: [
    {
      required: true,
      message: '请选择文件名命名方式',
      trigger: 'change'
    }
  ],
  fileNameByField: [
    {
      required: true,
      message: '请选择文件命名字段',
      trigger: 'change'
    }
  ],
  nameMark: [
    {
      required: true,
      message: '请选择输入间隔文字',
      trigger: 'change'
    },
    {
      pattern: /^[^\/\.<>!@#$%^&*()=\[\]{}|\\:;"'?,~`]*$/,
      message: '包含一些特殊字符，暂不支持',
      trigger: 'change'
    }
  ],

  downloadType: [
    {
      validator: (rule, value, callback) => {
        if (desktopChannels.includes(formData.downloadChannel)) {
          callback()
          return
        }
        if (value === undefined || value === null || value === '') {
          callback(new Error('请选择文件下载方式'))
          return
        }
        callback()
      },
      trigger: 'change'
    }
  ],
  downloadChannel: [
    {
      required: true,
      message: $t('select_download_channel'),
      trigger: 'change'
    }
  ],
  wsHost: [
    {
      validator: (rule, value, callback) => {
        if (!desktopChannels.includes(formData.downloadChannel)) {
          callback()
          return
        }
        if (!value) {
          callback(new Error($t('error_websocket_host_required')))
          return
        }
        callback()
      },
      trigger: 'change'
    }
  ],
  wsPort: [
    {
      validator: (rule, value, callback) => {
        if (!desktopChannels.includes(formData.downloadChannel)) {
          callback()
          return
        }
        if (value === undefined || value === null || value === '') {
          callback(new Error($t('error_websocket_port_required')))
          return
        }
        const port = Number(value)
        if (!Number.isInteger(port) || port < 1 || port > 65535) {
          callback(new Error($t('error_websocket_port_range')))
          return
        }
        callback()
      },
      trigger: 'change'
    }
  ],
  tokenPushBatchSize: [
    {
      validator: (rule, value, callback) => {
        if (formData.downloadChannel !== 'websocket_auth') {
          callback()
          return
        }
        if (value === undefined || value === null || value === '') {
          callback(new Error($t('error_token_push_batch_required')))
          return
        }
        const num = Number(value)
        if (!Number.isInteger(num) || num < 1 || num > 10000) {
          callback(new Error($t('error_token_push_batch_range')))
          return
        }
        callback()
      },
      trigger: 'change'
    }
  ],
  concurrentDownloads: [
    {
      required: true,
      message: $t('error_concurrent_downloads_required'),
      trigger: 'change'
    },
    {
      type: 'number',
      min: 1,
      max: 100,
      message: $t('error_concurrent_downloads_range'),
      trigger: 'change'
    }
  ],
  // firstFolderKey: [
  //   {
  //     required: true,
  //     message: "请选择一级目录，如不需要则关闭分类下载",
  //     trigger: "change",
  //   },
  // ],
  secondFolderKey: [
    {
      validator: (rule, value, callback) => {
        if (!value && !formData.firstFolderKey) {
          callback()
        } else if (!formData.firstFolderKey) {
          callback(new Error('请先选择一级目录'))
        } else if (value === formData.firstFolderKey) {
          callback(new Error('二级目录不能与一级目录相同'))
        } else {
          callback()
        }
      },
      trigger: 'change'
    }
  ]
})
const datas = reactive({
  allInfo: [],
  finshDownload: false
})
const activeTableInfo = computed(() => {
  const item = datas.allInfo.find((item) => item.tableId === formData.tableId)
  return item || null
})
const viewList = computed(() => {
  return activeTableInfo.value ? activeTableInfo.value.viewMetaList : []
})
const attachmentList = computed(() => {
  return activeTableInfo.value
    ? activeTableInfo.value['fieldMetaList'].filter(
      (item) => {
        if (item.type === FieldType.Attachment) {
          return true
        }
        if (item.type === FieldType.Lookup) {
          const { property: { refFieldId, refTableId }} = item
          const refTable = datas.allInfo.find((item) => item.tableId === refTableId)
          const refField = refTable?.fieldMetaList.find((item) => item.id === refFieldId)

          if (refField?.type === FieldType.Attachment) {
            return true
          }
        }
        return false
      }

    )
    : []
})
watch(
  () => formData.viewId,
  async(viewId) => {
    formData.selectedRecordIds = []
    if (viewId && activeTableInfo.value) {
      const table = await bitable.base.getTableById(formData.tableId)

      const view = await table.getViewById(formData.viewId)
      const list = await view.getFieldMetaList()

      const item = datas.allInfo.find(
        (item) => item.tableId === formData.tableId
      )
      item.fieldMetaList = sortByOrder(item.fieldMetaList, list)
    }
  }
)
const getSingleSelectListName = (id) => {
  const item = singleSelectList.value.find((e) => e.id === id)
  return item ? item.name : ''
}
const singleSelectList = computed(() => {
  return activeTableInfo.value
    ? activeTableInfo.value['fieldMetaList'].filter((item) =>
      SUPPORT_TYPES.includes(item.type)
    )
    : []
})
watch(
  () => formData.tableId,
  () => {
    const isExit = viewList.value.find((e) => e.id === formData.viewId)
    if (!isExit) {
      formData.viewId = viewList.value.length ? viewList.value[0]['id'] : ''
    }
    formData.fileNameByField = []
    formData.attachmentFileds = attachmentList.value.map((e) => e.id)
    formData.firstFolderKey = ''
    formData.secondFolderKey = ''
    formData.selectedRecordIds = []
  }
)
watch(
  () => formData.firstFolderKey,
  () => {
    // 清除二级目录的验证错误
    elform.value.clearValidate('secondFolderKey')
  }
)
watch(
  () => formData.secondFolderKey,
  (newVal) => {
    if (!newVal && formData.firstFolderKey) {
      elform.value.validateField('secondFolderKey')
    }
  }
)
watch(
  () => formData.downloadChannel,
  (channel) => {
    if (channel !== 'websocket_auth' && elform.value) {
      elform.value.clearValidate('tokenPushBatchSize')
    }
    if (desktopChannels.includes(channel) && elform.value) {
      elform.value.clearValidate('downloadType')
    }
  }
)
watch(
  () => confirmSelectedDialogVis.value,
  (visible) => {
    if (!visible) {
      pendingSelectedIds.value = []
    }
  }
)

/**
 * 组合用户输入的 WebSocket URL（兼容 ws://127.0.0.1:11548 与直接输入完整 URL）。
 */
const buildWebSocketUrl = (rawHost, rawPort) => {
  const host = String(rawHost || '').trim()
  if (!host) {
    return ''
  }
  if (/^wss?:\/\//i.test(host)) {
    return host
  }
  const port = rawPort === undefined || rawPort === null ? '' : String(rawPort).trim()
  if (host.includes(':') || !port) {
    return `ws://${host}`
  }
  return `ws://${host}:${port}`
}

/**
 * 连接本地客户端并获取服务端版本号（优先 probe，失败后回退 config）。
 */
const requestDesktopClientVersion = async() => {
  const wsUrl = buildWebSocketUrl(formData.wsHost, formData.wsPort)
  if (!wsUrl) {
    throw new Error($t('websocket_connection_failed'))
  }

  const timeoutMs = 3000
  const fallbackDelayMs = 800

  return await new Promise((resolve, reject) => {
    const socket = new WebSocket(wsUrl)
    let settled = false
    let fallbackTimer = null
    const timeoutTimer = setTimeout(() => {
      if (!settled) {
        settled = true
        try {
          socket.close()
        } catch (error) {
          // ignore
        }
        reject(new Error($t('websocket_connection_failed')))
      }
    }, timeoutMs)

    const cleanup = () => {
      clearTimeout(timeoutTimer)
      if (fallbackTimer) {
        clearTimeout(fallbackTimer)
        fallbackTimer = null
      }
      socket.onopen = null
      socket.onerror = null
      socket.onmessage = null
      socket.onclose = null
      try {
        socket.close()
      } catch (error) {
        // ignore
      }
    }

    const finish = (err, version) => {
      if (settled) return
      settled = true
      cleanup()
      if (err) {
        reject(err)
        return
      }
      resolve(version || '')
    }

    const sendPayload = (payload) => {
      try {
        socket.send(JSON.stringify(payload))
      } catch (error) {
        // ignore
      }
    }

    socket.onopen = () => {
      // 新版本客户端支持 probe，不会创建下载目录。
      sendPayload({ type: WEBSOCKET_PROBE_TYPE })
      // 兼容老版本：若 probe 无响应，则回退发送 config 触发 server_info。
      fallbackTimer = setTimeout(() => {
        sendPayload({
          type: WEBSOCKET_CONFIG_TYPE,
          data: {
            concurrent: 1,
            zipAfterDownload: false,
            jobId: `probe_${Date.now()}`,
            jobName: 'probe',
            zipName: 'probe',
            total: 0,
            downloadMode: 'url'
          }
        })
      }, fallbackDelayMs)
    }

    socket.onmessage = (event) => {
      try {
        const payload = JSON.parse(event?.data || '{}')
        if (!payload || payload.type !== WEBSOCKET_ACK_TYPE) {
          return
        }
        const data = payload.data || {}
        if (data.stage !== 'server_info') {
          return
        }
        const version = String(data.version || '').trim()
        finish(null, version)
      } catch (error) {
        // ignore
      }
    }

    socket.onerror = () => {
      finish(new Error($t('websocket_connection_failed')))
    }

    socket.onclose = () => {
      finish(new Error($t('websocket_connection_failed')))
    }
  })
}

/**
 * 检查本地客户端下载器版本；低于要求则弹窗提示并阻止继续下载。
 */
const ensureDesktopClientVersion = async() => {
  let serverVersion = ''
  try {
    serverVersion = await requestDesktopClientVersion()
  } catch (error) {
    await bitable.ui.showToast({
      toastType: 'warning',
      message: $t('websocket_connection_failed')
    })
    return false
  }

  if (!serverVersion || compareSemanticVersions(serverVersion, MIN_DESKTOP_CLIENT_VERSION) < 0) {
    const displayedVersion = serverVersion || 'unknown'
    const message = $t('desktop_client_update_required', {
      current: displayedVersion,
      required: MIN_DESKTOP_CLIENT_VERSION,
      url: DESKTOP_CLIENT_UPDATE_URL
    })
    await ElMessageBox.alert(message, $t('desktop_client_update_title'), {
      type: 'warning',
      confirmButtonText: $t('desktop_client_update_open'),
      showClose: false,
      closeOnClickModal: false,
      closeOnPressEscape: false,
      center: true,
      callback: () => {
        try {
          window.open(DESKTOP_CLIENT_UPDATE_URL, '_blank')
        } catch (error) {
          // ignore
        }
      }
    })
    return false
  }

  return true
}

const getSelectedRecordIdList = async() => {
  try {
    const selection = await bitable.base.getSelection()
    const tableId = formData.tableId || selection?.tableId
    const viewId = formData.viewId || selection?.viewId
    if (!tableId || !viewId) return []
    const table = await bitable.base.getTableById(tableId)
    if (!table) return []
    const view = await table.getViewById(viewId)
    if (view && typeof view.getSelectedRecordIdList === 'function') {
      const list = await view.getSelectedRecordIdList()
      return Array.isArray(list) ? list : []
    }
  } catch (error) {
    console.error('getSelectedRecordIdList failed', error)
  }
  return []
}
const downloadSelectedRecords = async() => {
  const ids = await getSelectedRecordIdList()
  if (!ids.length) {
    await bitable.ui.showToast({
      toastType: 'warning',
      message: $t('no_selected_records')
    })
    return
  }
  pendingSelectedIds.value = ids
  confirmSelectedDialogVis.value = true
}
const downloadAllRecords = async() => {
  formData.selectedRecordIds = []
  await submit()
}
const confirmSelectedDownload = async() => {
  formData.selectedRecordIds = [...pendingSelectedIds.value]
  confirmSelectedDialogVis.value = false
  pendingSelectedIds.value = []
  await submit()
}
const submit = async() => {
  // 获取下载权限（下载和打印归属一个权限）
  const bool = await base.getPermission({
    entity: PermissionEntity.Base,
    type: OperationType.Printable
  })

  if (!bool) {
    await bitable.ui.showToast({
      toastType: 'warning',
      message: '您无权限下载附件，请联系管理员'
    })
    return
  }
  if (!elform.value) return
  try {
    await elform.value.validate()
  } catch (error) {
    return
  }

  if (requiresDesktopClient.value) {
    const ok = await ensureDesktopClientVersion()
    if (!ok) return
  }

  datas.finshDownload = false
  downModelVis.value = true
}

onMounted(async() => {
  let tableMetaList = await bitable.base.getTableMetaList()
  // 无权限用户。通过以上接口会返回数据，但是name为空
  tableMetaList = tableMetaList.filter((e) => !!e.name)
  console.log('tableMetaList', tableMetaList)
  datas.allInfo = await getInfoByTableMetaList(tableMetaList)
  console.log('allInfo', datas.allInfo)

  // 刚渲染本插件的时候，用户所选的tableId等信息
  const selection = await bitable.base.getSelection()
  formData.tableId = selection?.tableId || ''
  formData.viewId = selection?.viewId || ''
  formData.appToken = selection?.baseId || ''
  formData.attachmentFileds = attachmentList.value.map((e) => e.id)
  formData.selectedRecordIds = []

  loading.value = false
})
</script>
<style lang="scss">
.form-container {
  min-height: 300px;

  .btns {
    display: flex;
    justify-content: flex-end;
    align-items: center;
    gap: 12px;
    width: 100%;
    margin-top: 16px;

    .btn-select,
    .btn-download {
      min-width: 160px;
    }
  }
}

.confirm-selected-dialog {
  .el-dialog__header {
    display: flex;
    align-items: center;
    padding: 16px 20px 8px;
  }

  .el-dialog__body {
    height: auto;
    padding: 0 20px 20px;
  }

  .confirm-dialog__header {
    display: flex;
    align-items: flex-start;
    gap: 12px;
  }

  .confirm-dialog__icon {
    font-size: 20px;
    color: var(--el-color-warning);
    flex-shrink: 0;
  }

  .confirm-dialog__header-text {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }

  .confirm-dialog__title {
    font-size: 16px;
    font-weight: 600;
    color: var(--N900);
    margin: 0;
  }

  .confirm-dialog__subtitle {
    font-size: 13px;
    color: var(--N500);
    margin: 0;
  }

  .confirm-dialog__content {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }

  .confirm-dialog__desc {
    font-size: 14px;
    color: var(--N700);
    margin: 0;
  }

  .confirm-dialog__summary {
    display: flex;
    justify-content: space-between;
    align-items: center;
    border: 1px solid var(--el-color-warning-light-7);
    background-color: var(--el-color-warning-light-9);
    border-radius: 8px;
    padding: 12px 16px;
  }

  .confirm-dialog__summary-label {
    font-size: 13px;
    color: var(--N500);
  }

  .confirm-dialog__summary-value {
    font-size: 20px;
    font-weight: 600;
    color: var(--el-color-warning);
  }

  .dialog-footer-actions {
    display: flex;
    justify-content: flex-end;
    gap: 8px;
    width: 100%;
  }
}

.el-dialog {
  .el-dialog__header {
    display: none;
  }

  .el-dialog__body {
    height: 60vh;
    overflow: auto;
    padding: 16px;
  }
}

.drag-item {
  cursor: move;
  display: inline-flex;
  margin-right: 10px;
  align-items: center;
  color: var(--N900);
  &:hover {
    opacity: 0.8;
  }
  .el-icon {
    margin-right: 3px;
  }
}
.advanced-collapse {
  margin-bottom: 16px;
}
.advanced-tip {
  font-size: 13px;
  color: var(--N500);
  margin-bottom: 12px;
}

.advanced-link {
  color: var(--el-color-primary);
  text-decoration: none;
}

.advanced-link:hover {
  text-decoration: underline;
}
</style>
