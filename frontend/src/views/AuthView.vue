<template>
  <div>
    <div class="panel auth-panel">
      <div class="auth-toolbar">
        <div class="auth-search">
          <el-input
            v-model="query.keyword"
            :prefix-icon="Search"
            placeholder="搜索卡密 / 实例 / 设备 / 备注"
            clearable
            @keyup.enter="search"
          />
        </div>
        <el-select v-model="query.softwareId" placeholder="实例" clearable>
          <el-option v-for="item in software" :key="item.softwareId" :label="item.name" :value="item.softwareId" />
        </el-select>
        <el-input v-model="query.authId" placeholder="卡密片段" clearable />
        <el-input v-model="query.macid" placeholder="设备码" clearable />
        <el-select v-model="query.status" placeholder="状态" clearable>
          <el-option label="未激活" value="unused" />
          <el-option label="已激活" value="active" />
          <el-option label="已过期" value="expired" />
          <el-option label="已禁用" value="disabled" />
          <el-option label="已撤销" value="revoked" />
        </el-select>
        <el-button type="primary" :icon="Search" @click="search">搜索</el-button>
        <el-button :icon="Refresh" @click="resetSearch">重置</el-button>
      </div>

      <div class="auth-actions">
        <el-button v-if="canCreateAuth" type="success" :icon="Plus" @click="openCreate">新增卡密</el-button>
        <el-button v-if="canExportAuth" :icon="Download" @click="exportRows">导出</el-button>
        <el-button v-if="canDeleteAuth" type="danger" :icon="Delete" :disabled="selected.length === 0" @click="batchDelete">批量删除</el-button>
      </div>

      <el-table class="desktop-data-table" v-loading="loading" :data="rows" @selection-change="selected = $event">
        <el-table-column v-if="canDeleteAuth" type="selection" width="44" />
        <el-table-column label="卡密" min-width="250">
          <template #default="{ row }">
            <div class="card-code">
              <strong>{{ row.authId }}</strong>
              <span>{{ row.createTime }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="softwareId" label="实例 ID" min-width="150" />
        <el-table-column v-if="showCreatorColumn" label="创建者" min-width="170">
          <template #default="{ row }">
            <div class="creator-cell" :class="{ 'creator-user-card': row.creatorRole === 'user' }">
              <span>{{ creatorDisplayName(row) }}</span>
              <el-tag :type="creatorTag(row)" effect="light">{{ creatorRoleText(row) }}</el-tag>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="statusTag(row)">{{ statusText(row) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="macid" label="设备码" min-width="160" show-overflow-tooltip />
        <el-table-column label="换绑" width="110">
          <template #default="{ row }">
            <span class="muted">{{ row.bindUsed || 0 }} / {{ row.bindCount ?? '不限' }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="endTime" label="到期时间" min-width="160" />
        <el-table-column prop="remark" label="备注" min-width="140" show-overflow-tooltip />
        <el-table-column label="操作" width="108" fixed="right" class-name="auth-operation-column">
          <template #default="{ row }">
            <div class="auth-row-actions">
              <el-tooltip content="复制卡密" placement="top">
                <el-button size="small" :icon="CopyDocument" circle @click="copy(row.authId)" />
              </el-tooltip>
              <el-dropdown v-if="canUnbindAuth || canDeleteAuth" trigger="click" placement="bottom-end" @command="(command) => handleRowAction(command, row)">
                <el-button size="small" :icon="MoreFilled" circle />
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item v-if="canUnbindAuth" command="remark" :icon="EditPen">修改备注</el-dropdown-item>
                    <el-dropdown-item v-if="canUnbindAuth" command="bind" :icon="Unlock">解绑/换绑</el-dropdown-item>
                    <el-dropdown-item v-if="canUnbindAuth && row.state !== 'revoked'" command="revoke" :icon="Delete" divided>撤销卡密</el-dropdown-item>
                    <el-dropdown-item v-if="canDeleteAuth" command="delete" :icon="Delete" divided class="danger-dropdown-item">删除卡密</el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </div>
          </template>
        </el-table-column>
      </el-table>

      <div v-loading="loading" class="mobile-card-list auth-mobile-list">
        <article v-for="row in rows" :key="row.authId" class="mobile-record-card auth-record-card">
          <div class="mobile-record-head">
            <div class="card-code mobile-card-code">
              <strong>{{ row.authId }}</strong>
              <span>{{ row.createTime }}</span>
            </div>
            <div class="mobile-record-status">
              <el-checkbox v-if="canDeleteAuth" :model-value="isSelected(row)" @change="(checked) => toggleMobileSelect(row, checked)" />
              <el-tag :type="statusTag(row)">{{ statusText(row) }}</el-tag>
            </div>
          </div>
          <div class="mobile-record-meta">
            <span><b>实例</b><em>{{ row.softwareId }}</em></span>
            <span><b>设备</b><em>{{ row.macid || '未绑定' }}</em></span>
            <span><b>换绑</b><em>{{ row.bindUsed || 0 }} / {{ row.bindCount ?? '不限' }}</em></span>
            <span><b>到期</b><em>{{ row.endTime || '永久' }}</em></span>
          </div>
          <div class="mobile-record-note">
            <span>备注</span>
            <em>{{ row.remark || '无备注' }}</em>
          </div>
          <div v-if="showCreatorColumn" class="mobile-record-creator">
            <span>创建者</span>
            <div class="creator-cell" :class="{ 'creator-user-card': row.creatorRole === 'user' }">
              <span>{{ creatorDisplayName(row) }}</span>
              <el-tag :type="creatorTag(row)" effect="light">{{ creatorRoleText(row) }}</el-tag>
            </div>
          </div>
          <div class="mobile-record-actions">
            <el-button size="small" :icon="CopyDocument" @click="copy(row.authId)">复制</el-button>
            <el-button v-if="canUnbindAuth" size="small" :icon="EditPen" @click="openRemark(row)">备注</el-button>
            <el-button v-if="canUnbindAuth" size="small" :icon="Unlock" @click="openBind(row)">解绑</el-button>
            <el-button v-if="canUnbindAuth && row.state !== 'revoked'" size="small" type="warning" @click="revoke(row)">撤销</el-button>
            <el-button v-if="canDeleteAuth" size="small" type="danger" :icon="Delete" @click="remove(row)">删除</el-button>
          </div>
        </article>
        <el-empty v-if="!loading && rows.length === 0" description="暂无卡密" />
      </div>

      <el-pagination
        v-model:current-page="page.pageNum"
        v-model:page-size="page.limit"
        :page-sizes="[10, 20, 50, 100]"
        :total="page.count"
        layout="total, sizes, prev, pager, next"
        @current-change="load"
        @size-change="search"
      />
    </div>

    <el-dialog v-model="createDialog" class="create-auth-dialog" width="760px" destroy-on-close>
      <template #header>
        <div class="dialog-title">
          <span class="dialog-title-icon"><el-icon><Key /></el-icon></span>
          <div>
            <strong>新增卡密</strong>
            <span>批量生成授权码并写入当前实例</span>
          </div>
        </div>
      </template>
      <div class="create-auth-layout">
        <section class="create-auth-main">
          <el-form label-position="top">
            <el-form-item label="授权实例">
              <el-select v-model="createForm.softwareId" class="w-full" filterable>
                <el-option v-for="item in software" :key="item.softwareId" :label="`${item.name} · ${item.softwareId}`" :value="item.softwareId" />
              </el-select>
            </el-form-item>
            <div class="form-grid compact-grid">
              <el-form-item label="生成数量">
                <el-input-number v-model="createForm.createNumber" :min="1" :max="100" controls-position="right" />
                <div class="quick-choice-row">
                  <button
                    v-for="value in quantityPresets"
                    :key="value"
                    type="button"
                    :class="{ active: createForm.createNumber === value }"
                    @click="createForm.createNumber = value"
                  >
                    {{ value }} 张
                  </button>
                </div>
              </el-form-item>
              <el-form-item label="换绑次数">
                <el-input-number v-model="createForm.bindCount" :min="0" controls-position="right" placeholder="不限" />
                <div class="quick-choice-row">
                  <button
                    v-for="item in bindPresets"
                    :key="item.label"
                    type="button"
                    :class="{ active: createForm.bindCount === item.value }"
                    @click="createForm.bindCount = item.value"
                  >
                    {{ item.label }}
                  </button>
                </div>
              </el-form-item>
            </div>
            <el-form-item label="有效期">
              <div class="duration-preset">
                <el-button v-for="item in durationPresets" :key="item.label" :type="isPresetActive(item) ? 'primary' : 'default'" @click="applyDuration(item)">
                  {{ item.label }}
                </el-button>
              </div>
            </el-form-item>
            <div class="form-grid compact-grid">
              <el-form-item label="天">
                <el-input-number v-model="createForm.day" :min="0" controls-position="right" />
              </el-form-item>
              <el-form-item label="小时">
                <el-input-number v-model="createForm.hour" :min="0" :max="23" controls-position="right" />
              </el-form-item>
              <el-form-item label="分钟">
                <el-input-number v-model="createForm.minute" :min="0" :max="59" controls-position="right" />
              </el-form-item>
            </div>
            <el-form-item label="备注">
              <el-input v-model="createForm.remark" type="textarea" :rows="3" placeholder="例如：订单号、渠道、批次说明" />
            </el-form-item>
          </el-form>
        </section>
        <aside class="create-auth-summary">
          <span class="summary-kicker">Issue Preview</span>
          <strong>{{ createForm.createNumber }} 张卡密</strong>
          <div class="summary-row"><span>实例</span><em>{{ selectedSoftwareName }}</em></div>
          <div class="summary-row"><span>有效期</span><em>{{ durationText }}</em></div>
          <div class="summary-row"><span>换绑</span><em>{{ createForm.bindCount ?? '不限' }}</em></div>
          <div class="summary-pulse"><i></i><span>等待生成</span></div>
        </aside>
      </div>
      <div v-if="createdCards.length" class="created-result">
        <div class="panel-header">
          <h3>已生成卡密</h3>
          <el-button size="small" :icon="CopyDocument" @click="copyCreated">复制全部</el-button>
        </div>
        <div class="created-list">
          <button v-for="item in createdCards" :key="item.authId" type="button" @click="copy(item.authId)">
            {{ item.authId }}
          </button>
        </div>
      </div>
      <template #footer>
        <el-button @click="createDialog = false">取消</el-button>
        <el-button type="primary" :icon="Finished" :loading="creating" @click="createCards">创建卡密</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="bindDialog.visible" title="卡密解绑/换绑" width="440px">
      <el-switch v-model="bindDialog.change" active-text="换绑为指定设备码" inactive-text="清除绑定" />
      <el-input v-if="bindDialog.change" v-model="bindDialog.macid" style="margin-top: 12px" placeholder="新设备码" />
      <template #footer>
        <el-button @click="bindDialog.visible = false">取消</el-button>
        <el-button type="primary" @click="saveBind">确定</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="remarkDialog.visible" title="修改备注" width="440px">
      <el-input v-model="remarkDialog.remark" type="textarea" />
      <template #footer>
        <el-button @click="remarkDialog.visible = false">取消</el-button>
        <el-button type="primary" @click="saveRemark">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { CopyDocument, Delete, Download, EditPen, Finished, Key, MoreFilled, Plus, Refresh, Search, Unlock } from '@element-plus/icons-vue'
import { api, downloadCsv, hasPermission, session } from '../services/api'

const loading = ref(false)
const creating = ref(false)
const rows = ref([])
const selected = ref([])
const software = ref([])
const page = reactive({ pageNum: 1, limit: 10, count: 0 })
const query = reactive({ keyword: '', softwareId: '', authId: '', macid: '', status: '' })
const createDialog = ref(false)
const createForm = reactive({ softwareId: '', createNumber: 1, day: 30, hour: 0, minute: 0, bindCount: null, remark: '' })
const createdCards = ref([])
const bindDialog = reactive({ visible: false, authId: '', macid: '', change: false })
const remarkDialog = reactive({ visible: false, authId: '', remark: '' })
const canCreateAuth = computed(() => hasPermission('authCreate'))
const canDeleteAuth = computed(() => hasPermission('authDelete'))
const canExportAuth = computed(() => hasPermission('authExport'))
const canUnbindAuth = computed(() => hasPermission('authUnbind'))
const showCreatorColumn = computed(() => ['developer', 'admin'].includes(session.role))
const durationPresets = [
  { label: '1 天', day: 1, hour: 0, minute: 0 },
  { label: '7 天', day: 7, hour: 0, minute: 0 },
  { label: '30 天', day: 30, hour: 0, minute: 0 },
  { label: '365 天', day: 365, hour: 0, minute: 0 },
  { label: '永久', day: 0, hour: 0, minute: 0 }
]
const quantityPresets = [1, 5, 10, 20, 50]
const bindPresets = [
  { label: '不限', value: null },
  { label: '0 次', value: 0 },
  { label: '1 次', value: 1 },
  { label: '3 次', value: 3 }
]

const selectedSoftwareName = computed(() => {
  const item = software.value.find((entry) => entry.softwareId === createForm.softwareId)
  return item ? item.name : '未选择'
})

const durationText = computed(() => {
  const parts = []
  if (createForm.day) parts.push(`${createForm.day} 天`)
  if (createForm.hour) parts.push(`${createForm.hour} 小时`)
  if (createForm.minute) parts.push(`${createForm.minute} 分钟`)
  return parts.length ? parts.join(' ') : '永久'
})

function statusText(row) {
  if (row.state === 'active') return '已激活'
  if (row.state === 'expired') return '已过期'
  if (row.state === 'disabled') return '已禁用'
  if (row.state === 'revoked') return '已撤销'
  return '未激活'
}

function statusTag(row) {
  if (row.state === 'active') return 'success'
  if (row.state === 'expired') return 'info'
  if (row.state === 'disabled') return 'danger'
  if (row.state === 'revoked') return 'danger'
  return 'primary'
}

function creatorRoleText(row) {
  if (row.creatorUser === session.user) return '本人创建'
  return row.creatorRoleLabel || '历史数据'
}

function creatorDisplayName(row) {
  return row.creatorName || row.creatorUser || '历史数据'
}

function creatorTag(row) {
  if (row.creatorUser === session.user) return 'success'
  if (row.creatorRole === 'user') return 'warning'
  if (row.creatorRole === 'admin') return 'primary'
  if (row.creatorRole === 'developer') return 'danger'
  return 'info'
}

function creatorWarningText(row) {
  const who = creatorDisplayName(row)
  const role = row.creatorRoleLabel || '未知角色'
  if (row.creatorRole === 'user') return `该卡密由普通用户 ${who} 创建，删除后用户侧也会失去这条记录。`
  return `该卡密由${role} ${who} 创建。`
}

async function loadSoftware() {
  const res = await api.softwareSelect()
  if (res.success) {
    software.value = res.data
    if (!createForm.softwareId && software.value[0]) createForm.softwareId = software.value[0].softwareId
  }
}

async function load() {
  loading.value = true
  try {
    const res = await api.authList({ ...query, page })
    if (res.success) {
      rows.value = res.data.list
      Object.assign(page, res.data.page)
    }
  } finally {
    loading.value = false
  }
}

function search() {
  page.pageNum = 1
  load()
}

function resetSearch() {
  Object.assign(query, { keyword: '', softwareId: '', authId: '', macid: '', status: '' })
  selected.value = []
  search()
}

function openCreate() {
  if (!createForm.softwareId && software.value[0]) createForm.softwareId = software.value[0].softwareId
  createdCards.value = []
  createDialog.value = true
}

async function createCards() {
  if (!createForm.softwareId) {
    ElMessage.warning('请先选择实例')
    return
  }
  creating.value = true
  try {
    const res = await api.createAuth(createForm)
    if (res.success) {
      createdCards.value = res.data || []
      ElMessage.success(`已创建 ${createdCards.value.length} 张卡密`)
      load()
    }
  } finally {
    creating.value = false
  }
}

function applyDuration(item) {
  createForm.day = item.day
  createForm.hour = item.hour
  createForm.minute = item.minute
}

function isPresetActive(item) {
  return createForm.day === item.day && createForm.hour === item.hour && createForm.minute === item.minute
}

function openBind(row) {
  Object.assign(bindDialog, { visible: true, authId: row.authId, macid: row.macid || '', change: false })
}

async function saveBind() {
  const res = await api.unbindAuth({ authId: bindDialog.authId, macid: bindDialog.change ? bindDialog.macid : '' })
  if (res.success) {
    ElMessage.success('修改成功')
    bindDialog.visible = false
    load()
  }
}

function openRemark(row) {
  Object.assign(remarkDialog, { visible: true, authId: row.authId, remark: row.remark || '' })
}

function handleRowAction(command, row) {
  if (command === 'remark') openRemark(row)
  if (command === 'bind') openBind(row)
  if (command === 'revoke') revoke(row)
  if (command === 'delete') remove(row)
}

async function revoke(row) {
  await ElMessageBox.confirm(`撤销后卡密 ${row.authId} 将立即失效，确定继续？`, '撤销卡密', { type: 'warning' })
  const res = await api.revokeAuth({ authId: row.authId })
  if (res.success) load()
}

function isSelected(row) {
  return selected.value.some((item) => item.authId === row.authId)
}

function toggleMobileSelect(row, checked) {
  if (checked && !isSelected(row)) {
    selected.value = [...selected.value, row]
  } else if (!checked) {
    selected.value = selected.value.filter((item) => item.authId !== row.authId)
  }
}

async function saveRemark() {
  const res = await api.updateAuthRemark({ authId: remarkDialog.authId, remark: remarkDialog.remark })
  if (res.success) {
    ElMessage.success('保存成功')
    remarkDialog.visible = false
    load()
  }
}

async function remove(row) {
  await ElMessageBox.confirm(`确定删除卡密 ${row.authId}？${showCreatorColumn.value ? `\n${creatorWarningText(row)}` : ''}`, row.creatorRole === 'user' ? '删除用户创建的卡密' : '确认删除', { type: 'warning' })
  const res = await api.deleteAuth({ authId: row.authId })
  if (res.success) load()
}

async function batchDelete() {
  const userCreated = selected.value.filter((row) => row.creatorRole === 'user').length
  const suffix = userCreated ? `，其中 ${userCreated} 个由普通用户创建` : ''
  await ElMessageBox.confirm(`确定删除选中的 ${selected.value.length} 个卡密${suffix}？`, userCreated ? '批量删除含用户卡密' : '确认删除', { type: 'warning' })
  const res = await api.batchDeleteAuth({ list: selected.value.map((row) => row.authId) })
  if (res.success) load()
}

function exportRows() {
  downloadCsv('/api/adm/exportTable', { ...query }, 'auth_cards.csv')
}

function copy(text) {
  navigator.clipboard?.writeText(text)
  ElMessage.success('已复制')
}

function copyCreated() {
  copy(createdCards.value.map((row) => row.authId).join('\n'))
}

onMounted(async () => { await loadSoftware(); await load() })
</script>

<style scoped>
.w-full { width: 100%; }
</style>
