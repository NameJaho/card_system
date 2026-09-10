<template>
  <div>
    <div class="panel software-panel">
      <div class="software-toolbar">
        <div class="toolbar-copy">
          <span class="summary-kicker">Instance Registry</span>
          <strong>实例列表</strong>
          <span>管理客户端接入标识、版本更新策略和发布公告。</span>
        </div>
        <div class="software-filters">
          <el-input v-model="query.softwareName" :prefix-icon="Search" placeholder="实例名称" clearable @keyup.enter="search" />
          <el-input v-model="query.softwareId" placeholder="实例 ID" clearable @keyup.enter="search" />
          <el-button type="primary" :icon="Search" @click="search">搜索</el-button>
          <el-button :icon="Refresh" @click="reset">重置</el-button>
          <el-button v-if="canCreate" type="success" :icon="Plus" @click="openCreate">创建实例</el-button>
        </div>
      </div>

      <el-table class="desktop-data-table" v-loading="loading" :data="rows">
        <el-table-column label="实例" min-width="230">
          <template #default="{ row }">
            <div class="software-cell">
              <span class="software-badge"><el-icon><Box /></el-icon></span>
              <div>
                <strong>{{ row.name }}</strong>
                <span>{{ row.softwareId }}</span>
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="版本策略" min-width="190">
          <template #default="{ row }">
            <div class="version-cell">
              <el-tag>{{ row.version || '未设置' }}</el-tag>
              <span>最低 {{ row.lowVersion || '不限' }} · {{ row.force ? '强制更新' : '提示更新' }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="实例密钥" min-width="190">
          <template #default="{ row }">
            <div class="secret-cell">
              <code>{{ maskSecret(row.instanceKey) }}</code>
              <el-tooltip content="复制实例密钥" placement="top">
                <el-button size="small" :icon="CopyDocument" circle @click="copy(row.instanceKey)" />
              </el-tooltip>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="visit" label="访问" width="90" />
        <el-table-column prop="notice" label="公告" show-overflow-tooltip />
        <el-table-column label="操作" width="340" fixed="right">
          <template #default="{ row }">
            <el-button v-if="canEdit" size="small" :icon="EditPen" @click="edit(row)">编辑</el-button>
            <el-button size="small" :icon="CopyDocument" @click="copy(row.softwareId)">复制 ID</el-button>
            <el-button size="small" :icon="DocumentCopy" @click="openIntegration(row)">接入客户端</el-button>
            <el-button v-if="canDelete" size="small" type="danger" :icon="Delete" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <div v-loading="loading" class="mobile-card-list software-mobile-list">
        <article v-for="row in rows" :key="row.softwareId" class="mobile-record-card software-record-card">
          <div class="mobile-record-head">
            <div class="software-cell">
              <span class="software-badge"><el-icon><Box /></el-icon></span>
              <div>
                <strong>{{ row.name }}</strong>
                <span>{{ row.softwareId }}</span>
              </div>
            </div>
            <el-tag :type="row.force ? 'danger' : 'primary'" effect="light">{{ row.force ? '强制更新' : '提示更新' }}</el-tag>
          </div>
          <div class="mobile-record-meta">
            <span><b>当前版本</b><em>{{ row.version || '未设置' }}</em></span>
            <span><b>最低版本</b><em>{{ row.lowVersion || '不限' }}</em></span>
            <span><b>访问</b><em>{{ row.visit || 0 }}</em></span>
            <span><b>密钥</b><em>{{ maskSecret(row.instanceKey) }}</em></span>
          </div>
          <div class="mobile-record-note">
            <span>公告</span>
            <em>{{ row.notice || '暂无公告' }}</em>
          </div>
          <div class="mobile-record-actions">
            <el-button v-if="canEdit" size="small" :icon="EditPen" @click="edit(row)">编辑</el-button>
            <el-button size="small" :icon="CopyDocument" @click="copy(row.softwareId)">复制 ID</el-button>
            <el-button size="small" :icon="CopyDocument" @click="copy(row.instanceKey)">复制密钥</el-button>
            <el-button size="small" :icon="DocumentCopy" @click="openIntegration(row)">接入客户端</el-button>
            <el-button v-if="canDelete" size="small" type="danger" :icon="Delete" @click="remove(row)">删除</el-button>
          </div>
        </article>
        <el-empty v-if="!loading && rows.length === 0" description="暂无实例" />
      </div>

      <el-pagination v-model:current-page="page.pageNum" v-model:page-size="page.limit" :total="page.count" layout="total, prev, pager, next" @current-change="load" />
    </div>

    <el-dialog v-model="dialog.visible" class="software-dialog" width="960px" append-to-body destroy-on-close>
      <template #header>
        <div class="dialog-title">
          <span class="dialog-title-icon"><el-icon><Box /></el-icon></span>
          <div>
            <strong>{{ dialog.isCreate ? '创建实例' : '修改实例' }}</strong>
            <span>配置客户端唯一接入实例、版本更新和发布信息</span>
          </div>
        </div>
      </template>

      <div class="software-create-layout">
        <section class="software-create-main">
          <el-form label-position="top">
            <div class="panel-header">
              <h3>基础信息</h3>
              <span>{{ dialog.isCreate ? '保存后自动生成实例 ID' : '实例 ID 不可修改' }}</span>
            </div>
            <div class="form-grid">
              <el-form-item label="实例名称">
                <el-input v-model.trim="form.name" placeholder="例如：桌面端授权系统" />
              </el-form-item>
              <el-form-item v-if="!dialog.isCreate" label="实例 ID">
                <el-input v-model="form.softwareId" disabled>
                  <template #append>
                    <el-button :icon="CopyDocument" @click="copy(form.softwareId)" />
                  </template>
                </el-input>
              </el-form-item>
              <el-form-item v-if="!dialog.isCreate" label="实例密钥">
                <el-input v-model="form.instanceKey" disabled>
                  <template #append>
                    <el-button :icon="CopyDocument" @click="copy(form.instanceKey)" />
                  </template>
                </el-input>
              </el-form-item>
              <el-form-item label="当前版本">
                <el-input v-model.trim="form.version" placeholder="1.0.0" />
              </el-form-item>
              <el-form-item label="最低可用版本">
                <el-input v-model.trim="form.lowVersion" placeholder="留空表示不限制" />
              </el-form-item>
            </div>

            <el-form-item label="版本快捷设置">
              <div class="version-preset">
                <el-button v-for="item in versionPresets" :key="item" :type="form.version === item ? 'primary' : 'default'" @click="applyVersion(item)">
                  {{ item }}
                </el-button>
                <el-switch v-model="form.force" active-text="强制更新" inactive-text="提示更新" />
              </div>
            </el-form-item>

            <div class="panel-header">
              <h3>发布配置</h3>
              <span>客户端检查更新时会读取以下字段</span>
            </div>
            <el-form-item label="下载地址">
              <el-input v-model.trim="form.url" placeholder="https://example.com/app.zip" />
            </el-form-item>
            <div class="form-grid">
              <el-form-item label="文件 SHA-256">
                <el-input v-model.trim="form.sha256" placeholder="64 位 SHA-256 校验值" />
              </el-form-item>
              <el-form-item label="备注">
                <el-input v-model.trim="form.remark" placeholder="仅后台可见" />
              </el-form-item>
            </div>
            <el-form-item label="更新公告">
              <el-input v-model="form.notice" type="textarea" :rows="4" placeholder="展示给客户端用户的更新说明" />
            </el-form-item>
          </el-form>
        </section>

        <aside class="create-auth-summary software-summary">
          <span class="summary-kicker">Client Config</span>
          <strong>{{ form.name || '新实例' }}</strong>
          <div class="summary-row"><span>实例 ID</span><em>{{ form.softwareId || '保存后生成' }}</em></div>
          <div class="summary-row"><span>实例密钥</span><em>{{ form.instanceKey ? maskSecret(form.instanceKey) : '保存后生成' }}</em></div>
          <div class="summary-row"><span>当前版本</span><em>{{ form.version || '未设置' }}</em></div>
          <div class="summary-row"><span>最低版本</span><em>{{ form.lowVersion || '不限制' }}</em></div>
          <div class="summary-row"><span>更新策略</span><em>{{ form.force ? '强制更新' : '提示更新' }}</em></div>
          <div class="endpoint-list">
            <span>客户端端点</span>
            <code>/api/client/v1/license/validate</code>
          </div>
          <div class="summary-pulse"><i></i><span>配置待保存</span></div>
          <el-button v-if="!dialog.isCreate" class="w-full" :icon="DocumentCopy" @click="openIntegration(form)">接入客户端</el-button>
        </aside>
      </div>

      <template #footer>
        <el-button @click="dialog.visible = false">取消</el-button>
        <el-button type="primary" :icon="Finished" :loading="saving" @click="save">保存实例</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="integration.visible" title="接入客户端" width="640px" append-to-body>
      <el-descriptions :column="1" border>
        <el-descriptions-item label="公共服务地址">{{ publicBaseUrl }}</el-descriptions-item>
        <el-descriptions-item label="软件 ID">{{ integration.row?.softwareId }}</el-descriptions-item>
        <el-descriptions-item label="协议版本">v1</el-descriptions-item>
        <el-descriptions-item label="Python SDK">{{ sdkVersion }}</el-descriptions-item>
        <el-descriptions-item label="服务版本">{{ appVersion }} / {{ gitSha }} / schema {{ schemaVersion }}</el-descriptions-item>
        <el-descriptions-item label="授权接口">/api/client/v1/license/validate</el-descriptions-item>
      </el-descriptions>
      <p class="muted">配置只包含服务地址、软件 ID 和版本。卡密由最终用户输入，installation ID 由 SDK 自动生成。</p>
      <pre class="json-box">{{ JSON.stringify(clientConfig(integration.row || {}), null, 2) }}</pre>
      <template #footer>
        <el-button v-if="canEdit" type="danger" plain @click="rotateLegacyKey">轮换旧协议密钥</el-button>
        <el-button @click="copyClientConfig(integration.row || {})">复制最小配置</el-button>
        <el-button type="primary" @click="downloadPackage">下载 Python 接入包</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { CopyDocument, Delete, DocumentCopy, EditPen, Finished, Plus, Refresh, Search } from '@element-plus/icons-vue'
import { api, downloadFile, hasPermission } from '../services/api'

const loading = ref(false)
const saving = ref(false)
const rows = ref([])
const query = reactive({ softwareName: '', softwareId: '' })
const page = reactive({ pageNum: 1, limit: 10, count: 0 })
const dialog = reactive({ visible: false, isCreate: true })
const integration = reactive({ visible: false, row: null })
const form = reactive({ softwareId: '', instanceKey: '', name: '', version: '', lowVersion: '', sha256: '', url: '', notice: '', remark: '', force: false })
const publicBaseUrl = ref('')
const sdkVersion = ref('1.0.0')
const appVersion = ref('dev')
const gitSha = ref('unknown')
const schemaVersion = ref('unknown')
const versionPresets = ['1.0.0', '1.1.0', '2.0.0', '3.0.0']
const canCreate = computed(() => hasPermission('softCreate'))
const canEdit = computed(() => hasPermission('softEdit'))
const canDelete = computed(() => hasPermission('softDelete'))

async function load() {
  loading.value = true
  try {
    const res = await api.softwareList({ ...query, page })
    if (res.success) {
      rows.value = res.data.list
      Object.assign(page, res.data.page)
    }
  } finally {
    loading.value = false
  }
}

async function loadPublicConfig() {
  const res = await api.userConfig()
  if (res.success) {
    publicBaseUrl.value = res.data.publicBaseUrl || ''
    sdkVersion.value = res.data.sdkVersion || '1.0.0'
    appVersion.value = res.data.appVersion || 'dev'
    gitSha.value = res.data.gitSha || 'unknown'
    schemaVersion.value = res.data.schemaVersion || 'unknown'
  }
}

function search() {
  page.pageNum = 1
  load()
}

function reset() {
  query.softwareName = ''
  query.softwareId = ''
  search()
}

function openCreate() {
  dialog.isCreate = true
  Object.assign(form, { softwareId: '', instanceKey: '', name: '', version: '1.0.0', lowVersion: '', sha256: '', url: '', notice: '', remark: '', force: false })
  dialog.visible = true
}

function edit(row) {
  dialog.isCreate = false
  Object.assign(form, {
    softwareId: row.softwareId || '',
    instanceKey: row.instanceKey || '',
    name: row.name || '',
    version: row.version || '',
    lowVersion: row.lowVersion || '',
    sha256: row.sha256 || '',
    url: row.url || '',
    notice: row.notice || '',
    remark: row.remark || '',
    force: Boolean(row.force)
  })
  dialog.visible = true
}

function applyVersion(version) {
  form.version = version
}

function validateForm() {
  if (!form.name.trim()) {
    ElMessage.warning('请输入实例名称')
    return false
  }
  if (form.name.includes('|')) {
    ElMessage.warning('实例名称不能包含 |')
    return false
  }
  if (!form.version.trim()) {
    ElMessage.warning('请输入当前版本')
    return false
  }
  if (form.url && !/^https?:\/\//i.test(form.url)) {
    ElMessage.warning('下载地址必须以 http:// 或 https:// 开头')
    return false
  }
  return true
}

async function save() {
  if (!validateForm()) return
  saving.value = true
  try {
    const payload = {
      softwareId: form.softwareId,
      name: form.name.trim(),
      version: form.version.trim(),
      lowVersion: form.lowVersion.trim(),
      sha256: form.sha256.trim(),
      url: form.url.trim(),
      notice: form.notice,
      remark: form.remark.trim(),
      force: form.force
    }
    const res = dialog.isCreate ? await api.createSoftware(payload) : await api.updateSoftware(payload)
    if (res.success) {
      ElMessage.success(dialog.isCreate ? '实例已创建' : '实例已更新')
      dialog.visible = false
      await load()
      if (dialog.isCreate) openIntegration(res.data)
    }
  } finally {
    saving.value = false
  }
}

async function remove(row) {
  await ElMessageBox.confirm(`确定删除实例 ${row.name}？`, '确认删除', { type: 'warning' })
  const res = await api.deleteSoftware({ softwareId: row.softwareId })
  if (res.success) load()
}

function copy(text) {
  if (!text) return
  navigator.clipboard?.writeText(text)
  ElMessage.success('已复制')
}

function maskSecret(value) {
  if (!value) return '未生成'
  if (value.length <= 12) return value
  return `${value.slice(0, 6)}...${value.slice(-6)}`
}

function clientConfig(row) {
  return {
    baseUrl: publicBaseUrl.value,
    softwareId: row.softwareId || '',
    version: row.version || '1.0.0'
  }
  if (form.sha256 && !/^[0-9a-f]{64}$/i.test(form.sha256)) {
    ElMessage.warning('SHA-256 必须是 64 位十六进制字符串')
    return false
  }
}

function copyClientConfig(row) {
  copy(JSON.stringify(clientConfig(row), null, 2))
}

function openIntegration(row) {
  integration.row = { ...row }
  integration.visible = true
}

async function downloadPackage() {
  const row = integration.row || {}
  if (!row.softwareId) return
  await downloadFile(
    '/api/adm/clientPackage',
    { softwareId: row.softwareId },
    `keydesk-${row.softwareId}-python-v1.zip`
  )
}

async function rotateLegacyKey() {
  const row = integration.row || {}
  if (!row.softwareId) return
  await ElMessageBox.confirm('轮换后，仍使用旧协议的客户端必须更新 instanceKey。确定继续？', '轮换旧协议密钥', { type: 'warning' })
  const res = await api.rotateInstanceKey({ softwareId: row.softwareId })
  if (res.success) {
    integration.row = { ...res.data }
    ElMessage.success('旧协议实例密钥已轮换')
    load()
  }
}

onMounted(() => {
  load()
  loadPublicConfig()
})
</script>
