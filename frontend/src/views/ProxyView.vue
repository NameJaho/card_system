<template>
  <div>
    <div class="panel proxy-panel">
      <div class="proxy-toolbar">
        <div class="toolbar-copy">
          <span class="summary-kicker">Account Authority</span>
          <strong>账号管理</strong>
          <span>由超级管理员创建账号并分配固定角色，后台不开放公开注册。</span>
        </div>
        <div class="proxy-meta">
          <div class="proxy-stat">
            <span>账号</span>
            <strong>{{ rows.length }}</strong>
          </div>
          <div class="proxy-stat">
            <span>在线</span>
            <strong>{{ onlineCount }}</strong>
          </div>
          <div class="proxy-stat">
            <span>普通用户</span>
            <strong>{{ roleCount.user }}</strong>
          </div>
          <el-button :icon="Refresh" @click="load">刷新</el-button>
          <el-button type="primary" :icon="Plus" @click="openCreate">创建账号</el-button>
        </div>
      </div>

      <el-table class="desktop-data-table" :data="rows" v-loading="loading">
        <el-table-column label="账号" min-width="230">
          <template #default="{ row }">
            <div class="account-cell">
              <span class="account-avatar">{{ initialOf(row.user) }}</span>
              <div>
                <strong>{{ row.user }}</strong>
                <span>{{ row.nick || '未设置昵称' }} · {{ row.email || '未设置邮箱' }}</span>
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="角色" width="150">
          <template #default="{ row }">
            <el-tag :type="roleTag(row.role)" effect="light">{{ row.roleLabel || roleLabel(row.role) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="实例范围" min-width="220">
          <template #default="{ row }">
            <div class="scope-cell">
              <el-tag :type="row.softwareIds?.includes('*') ? 'success' : 'primary'">{{ rowScopeLabel(row) }}</el-tag>
              <div v-if="!row.softwareIds?.includes('*')" class="mini-chip-list">
                <span v-for="name in rowScopePreview(row)" :key="name">{{ name }}</span>
                <em v-if="rowScopeRest(row)">+{{ rowScopeRest(row) }}</em>
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="权限" min-width="300">
          <template #default="{ row }">
            <div class="permission-tags">
              <el-tag v-for="label in rowPermissionPreview(row)" :key="label">{{ label }}</el-tag>
              <span v-if="rowPermissionRest(row)" class="permission-more">+{{ rowPermissionRest(row) }} 项</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="lastLogin" label="最近登录" width="170" />
        <el-table-column prop="time" label="创建时间" width="170" />
        <el-table-column label="操作" width="170" fixed="right">
          <template #default="{ row }">
            <el-button size="small" :icon="EditPen" @click="edit(row)">编辑</el-button>
            <el-button size="small" type="danger" :icon="Delete" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <div v-loading="loading" class="mobile-card-list proxy-mobile-list">
        <article v-for="row in rows" :key="row.user" class="mobile-record-card proxy-record-card">
          <div class="mobile-record-head">
            <div class="account-cell">
              <span class="account-avatar">{{ initialOf(row.user) }}</span>
              <div>
                <strong>{{ row.user }}</strong>
                <span>{{ row.nick || '未设置昵称' }} · {{ row.email || '未设置邮箱' }}</span>
              </div>
            </div>
            <el-tag :type="roleTag(row.role)" effect="light">{{ row.roleLabel || roleLabel(row.role) }}</el-tag>
          </div>
          <div class="mobile-record-meta">
            <span><b>实例</b><em>{{ rowScopeLabel(row) }}</em></span>
            <span><b>最近登录</b><em>{{ row.lastLogin || '从未登录' }}</em></span>
            <span><b>创建时间</b><em>{{ row.time || '未知' }}</em></span>
          </div>
          <div class="mobile-chip-section">
            <span>实例范围</span>
            <div class="mini-chip-list">
              <template v-if="row.softwareIds?.includes('*')">
                <span>全部实例</span>
              </template>
              <template v-else>
                <span v-for="name in rowScopePreview(row)" :key="name">{{ name }}</span>
                <em v-if="rowScopeRest(row)">+{{ rowScopeRest(row) }}</em>
              </template>
            </div>
          </div>
          <div class="mobile-chip-section">
            <span>权限</span>
            <div class="permission-tags">
              <el-tag v-for="label in rowPermissionPreview(row)" :key="label">{{ label }}</el-tag>
              <span v-if="rowPermissionRest(row)" class="permission-more">+{{ rowPermissionRest(row) }} 项</span>
            </div>
          </div>
          <div class="mobile-record-actions">
            <el-button size="small" :icon="EditPen" @click="edit(row)">编辑</el-button>
            <el-button size="small" type="danger" :icon="Delete" @click="remove(row)">删除</el-button>
          </div>
        </article>
        <el-empty v-if="!loading && rows.length === 0" description="暂无账号" />
      </div>
    </div>

    <el-dialog v-model="dialog.visible" class="proxy-dialog" width="960px" append-to-body destroy-on-close>
      <template #header>
        <div class="dialog-title">
          <span class="dialog-title-icon"><el-icon><Connection /></el-icon></span>
          <div>
            <strong>{{ dialog.isCreate ? '创建账号' : '编辑账号' }}</strong>
            <span>选择角色后，系统会自动写入对应权限，不再手动勾选权限项。</span>
          </div>
        </div>
      </template>

      <div class="proxy-create-layout">
        <section class="proxy-create-main">
          <el-form label-position="top">
            <div class="panel-header">
              <h3>账号资料</h3>
              <div class="panel-header-actions">
                <span>{{ dialog.isCreate ? '密码为必填项' : '密码留空则保持不变' }}</span>
                <el-button size="small" :icon="Refresh" @click="quickFillAccount()">{{ dialog.isCreate ? '一键生成' : '生成新密码' }}</el-button>
              </div>
            </div>
            <div class="form-grid">
              <el-form-item label="账号">
                <el-input v-model.trim="form.user" :disabled="!dialog.isCreate" placeholder="登录账号" />
              </el-form-item>
              <el-form-item label="密码">
                <el-input v-model="form.password" type="password" show-password :placeholder="dialog.isCreate ? '设置登录密码' : '不填则不修改'" />
              </el-form-item>
              <el-form-item label="昵称">
                <el-input v-model.trim="form.nick" placeholder="用于后台展示" />
              </el-form-item>
              <el-form-item label="邮箱">
                <el-input v-model.trim="form.email" placeholder="通知或找回账号使用" />
              </el-form-item>
            </div>

            <div class="panel-header">
              <h3>角色权限</h3>
              <span>{{ roleHelpText }}</span>
            </div>
            <div class="role-grid">
              <button
                v-for="item in availableRoleOptions"
                :key="item.value"
                type="button"
                class="role-card"
                :class="{ active: form.role === item.value }"
                @click="form.role = item.value"
              >
                <span class="role-card-top">
                  <i :class="`role-dot role-${item.value}`"></i>
                  <strong>{{ item.label }}</strong>
                  <em>{{ item.badge }}</em>
                </span>
                <span>{{ item.desc }}</span>
              </button>
            </div>

            <div class="permission-preview">
              <div v-for="code in selectedRolePermissions" :key="code" class="permission-preview-item">
                <el-icon><component :is="permissionIcon(code)" /></el-icon>
                <span>{{ permissionMap[code] || code }}</span>
              </div>
            </div>

            <div class="panel-header">
              <h3>实例范围</h3>
              <span>{{ scopeSummary }}</span>
            </div>
            <div class="scope-box">
              <template v-if="isUserRole">
                <el-select
                  v-model="form.softwareIds"
                  class="w-full"
                  multiple
                  filterable
                  collapse-tags
                  collapse-tags-tooltip
                  placeholder="选择普通用户可访问的实例"
                >
                  <el-option v-for="item in software" :key="item.softwareId" :label="`${item.name} · ${item.softwareId}`" :value="item.softwareId" />
                </el-select>
                <div class="scope-preview">
                  <div v-if="selectedSoftwareItems.length" class="scope-preview-list">
                    <span v-for="item in selectedSoftwareItems" :key="item.softwareId">{{ item.name }}</span>
                  </div>
                  <span v-else>普通用户必须选择至少一个可访问实例。</span>
                </div>
              </template>
              <template v-else>
                <div class="scope-preview all-scope">
                  <span>该角色拥有全部实例范围，保存时会自动写入全部实例。</span>
                </div>
              </template>
            </div>
          </el-form>
        </section>

        <aside class="create-auth-summary proxy-summary">
          <span class="summary-kicker">Role Preview</span>
          <strong>{{ selectedRole?.label || '未选择角色' }}</strong>
          <div class="summary-row"><span>账号</span><em>{{ form.user || '未填写' }}</em></div>
          <div class="summary-row"><span>权限数</span><em>{{ selectedRolePermissions.length }} 项</em></div>
          <div class="summary-row"><span>实例范围</span><em>{{ scopeSummary }}</em></div>
          <div class="summary-row"><span>密码</span><em>{{ passwordSummary }}</em></div>
          <div class="summary-row summary-url-row"><span>登录地址</span><em :title="shareLoginUrl">{{ shareLoginUrl }}</em></div>
          <el-button v-if="dialog.isCreate" class="summary-share-button" :icon="CopyDocument" :loading="sharing" @click="saveAndShare">一键分享</el-button>
          <div class="summary-pulse"><i></i><span>等待保存</span></div>
        </aside>
      </div>

      <template #footer>
        <el-button @click="dialog.visible = false">取消</el-button>
        <el-button type="primary" :icon="Finished" :loading="saving" @click="save">保存账号</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { CopyDocument, Delete, EditPen, Finished, Plus, Refresh } from '@element-plus/icons-vue'
import { api, session } from '../services/api'

const permissionMap = {
  softView: '实例查看',
  softCreate: '实例新增',
  softEdit: '实例编辑',
  softDelete: '实例删除',
  authCreate: '卡密新增',
  authDelete: '卡密删除',
  authExport: '卡密导出',
  authUnbind: '卡密解绑/换绑',
  userView: '终端用户管理',
  cloudVarView: '查看云变量',
  cloudVarAdd: '云变量新增',
  cloudVarDelete: '云变量删除',
  blackWhiteView: '查看黑白名单',
  blackWhiteAdd: '黑白名单新增',
  blackWhiteDelete: '黑白名单删除',
  accountManage: '账号管理',
  eventView: '事件日志',
  messageManage: '后台消息'
}

const rolePermissionMap = {
  developer: Object.keys(permissionMap),
  admin: ['softView', 'softCreate', 'softEdit', 'softDelete', 'authCreate', 'accountManage'],
  user: ['softView', 'authCreate']
}

const roleOptions = [
  { value: 'developer', label: '超级管理员', badge: '全部权限', desc: '开发者账号，拥有所有后台接口和系统接入密钥。' },
  { value: 'admin', label: '管理员', badge: '账号 + 实例 + 卡密', desc: '可以创建普通用户，管理实例，并为任意可见实例创建卡密。' },
  { value: 'user', label: '普通用户', badge: '卡密 + 查看', desc: '只允许创建卡密，并查看被分配实例的数据。' }
]

const rows = ref([])
const software = ref([])
const loading = ref(false)
const saving = ref(false)
const sharing = ref(false)
const onlineCount = ref(0)
const dialog = reactive({ visible: false, isCreate: true })
const form = reactive({ user: '', password: '', nick: '', email: '', role: 'user', softwareIds: [] })

const availableRoleOptions = computed(() => (session.role === 'developer' ? roleOptions : roleOptions.filter((item) => item.value === 'user')))
const selectedRole = computed(() => roleOptions.find((item) => item.value === form.role))
const selectedRolePermissions = computed(() => rolePermissionMap[form.role] || rolePermissionMap.user)
const isUserRole = computed(() => form.role === 'user')
const selectedSoftwareItems = computed(() => software.value.filter((item) => form.softwareIds.includes(item.softwareId)))
const roleCount = computed(() => rows.value.reduce((acc, row) => {
  const role = row.role || 'user'
  acc[role] = (acc[role] || 0) + 1
  return acc
}, { developer: 0, admin: 0, user: 0 }))
const roleHelpText = computed(() => (session.role === 'developer' ? '超级管理员可以创建任意角色。' : '管理员只能创建普通用户。'))
const defaultCreateRole = computed(() => (availableRoleOptions.value.some((item) => item.value === 'user') ? 'user' : availableRoleOptions.value[0]?.value || 'user'))
const scopeSummary = computed(() => {
  if (!isUserRole.value) return '全部实例'
  if (selectedSoftwareItems.value.length) return `${selectedSoftwareItems.value.length} 个指定实例`
  return '未选择实例'
})
const shareLoginUrl = computed(() => adminLoginUrl())
const shareText = computed(() => [
  '后台账号登录信息',
  `登录地址：${shareLoginUrl.value}`,
  `账号：${form.user || '未填写'}`,
  `密码：${form.password || '未设置'}`,
  `角色：${selectedRole.value?.label || '未选择'}`,
  `实例范围：${scopeSummary.value}`,
  '登录后请尽快修改密码。'
].join('\n'))
const passwordSummary = computed(() => {
  if (dialog.isCreate) return form.password ? '已设置' : '未设置'
  return form.password ? '将更新' : '保持原密码'
})

watch(availableRoleOptions, (options) => {
  if (!options.some((item) => item.value === form.role)) {
    form.role = options[0]?.value || 'user'
  }
}, { immediate: true })

watch(() => form.role, (role) => {
  if (role !== 'user') form.softwareIds = []
})

async function load() {
  loading.value = true
  try {
    const [users, sw] = await Promise.all([api.subUsers({ page: { pageNum: 1, limit: 100 } }), api.softwareSelect()])
    if (users.success) {
      rows.value = users.data.list || []
      onlineCount.value = users.data.onlineCount || 0
    }
    if (sw.success) software.value = sw.data || []
  } finally {
    loading.value = false
  }
}

function resetForm() {
  Object.assign(form, {
    user: '',
    password: '',
    nick: '',
    email: '',
    role: defaultCreateRole.value,
    softwareIds: []
  })
}

function randomSuffix() {
  return Math.random().toString(36).slice(2, 8)
}

function generateUsername(role = form.role) {
  const prefixMap = { developer: 'dev', admin: 'admin', user: 'user' }
  return `${prefixMap[role] || 'user'}_${Date.now().toString(36).slice(-4)}${randomSuffix()}`
}

function generatePassword() {
  return `Kd${randomSuffix()}${Math.floor(1000 + Math.random() * 9000)}`
}

function quickFillAccount(forceUsername = dialog.isCreate) {
  if (dialog.isCreate && (forceUsername || !form.user.trim())) form.user = generateUsername(form.role)
  if (dialog.isCreate && (forceUsername || !form.nick.trim())) form.nick = roleLabel(form.role)
  form.password = generatePassword()
  if (isUserRole.value && form.softwareIds.length === 0 && software.value[0]) {
    form.softwareIds = [software.value[0].softwareId]
  }
}

function openCreate() {
  dialog.isCreate = true
  resetForm()
  quickFillAccount(true)
  dialog.visible = true
}

function edit(row) {
  dialog.isCreate = false
  Object.assign(form, {
    user: row.user,
    password: '',
    nick: row.nick || '',
    email: row.email || '',
    role: row.role || 'user',
    softwareIds: row.softwareIds?.includes('*') ? [] : [...(row.softwareIds || [])]
  })
  if (!availableRoleOptions.value.some((item) => item.value === form.role)) {
    form.role = availableRoleOptions.value[0]?.value || 'user'
  }
  dialog.visible = true
}

function validateForm() {
  if (!form.user.trim()) {
    ElMessage.warning('请输入账号')
    return false
  }
  if (dialog.isCreate && !form.password.trim()) {
    ElMessage.warning('创建账号时必须设置密码')
    return false
  }
  if (!selectedRole.value) {
    ElMessage.warning('请选择角色')
    return false
  }
  if (isUserRole.value && form.softwareIds.length === 0) {
    ElMessage.warning('普通用户必须选择至少一个实例')
    return false
  }
  if (form.email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.email)) {
    ElMessage.warning('请输入正确的邮箱格式')
    return false
  }
  return true
}

async function save() {
  if (!validateForm()) return
  saving.value = true
  try {
    if (await persistAccount()) {
      ElMessage.success('账号已保存')
      dialog.visible = false
    }
  } finally {
    saving.value = false
  }
}

function accountPayload() {
  return {
    user: form.user.trim(),
    password: form.password,
    nick: form.nick.trim(),
    email: form.email.trim(),
    role: form.role,
    softwareIds: isUserRole.value ? form.softwareIds : ['*']
  }
}

async function persistAccount() {
  const res = dialog.isCreate ? await api.createSubUser(accountPayload()) : await api.updateSubUser(accountPayload())
  if (res.success) {
    await load()
    return true
  }
  return false
}

function adminLoginUrl() {
  const basePath = window.location.pathname.endsWith('/') ? window.location.pathname : `${window.location.pathname}/`
  return `${window.location.origin}${basePath}#/login`
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text)
  } catch {
    const textarea = document.createElement('textarea')
    textarea.value = text
    textarea.setAttribute('readonly', '')
    textarea.style.position = 'fixed'
    textarea.style.left = '-9999px'
    document.body.appendChild(textarea)
    textarea.select()
    document.execCommand('copy')
    document.body.removeChild(textarea)
  }
}

async function saveAndShare() {
  if (!dialog.isCreate) return
  if (!form.password.trim()) {
    ElMessage.warning(dialog.isCreate ? '请先生成密码' : '请先生成新密码')
    return
  }
  if (!validateForm()) return
  const text = shareText.value
  sharing.value = true
  try {
    if (await persistAccount()) {
      await copyText(text)
      ElMessage.success('账号已保存，分享信息已复制')
      dialog.visible = false
    }
  } finally {
    sharing.value = false
  }
}

async function remove(row) {
  await ElMessageBox.confirm(`确定删除账号 ${row.user}？`, '确认删除', { type: 'warning' })
  const res = await api.deleteSubUser({ user: row.user })
  if (res.success) load()
}

function softwareName(id) {
  const item = software.value.find((entry) => entry.softwareId === id)
  return item ? item.name : id
}

function roleLabel(role) {
  const item = roleOptions.find((entry) => entry.value === role)
  return item ? item.label : '普通用户'
}

function roleTag(role) {
  if (role === 'developer') return 'danger'
  if (role === 'admin') return 'warning'
  return 'primary'
}

function rowScopeLabel(row) {
  if (row.softwareIds?.includes('*')) return '全部实例'
  return `${row.softwareIds?.length || 0} 个实例`
}

function rowScopePreview(row) {
  return (row.softwareIds || []).slice(0, 3).map(softwareName)
}

function rowScopeRest(row) {
  return Math.max((row.softwareIds?.length || 0) - 3, 0)
}

function rowPermissionPreview(row) {
  const permissions = row.permissionTypes?.length ? row.permissionTypes : rolePermissionMap[row.role || 'user']
  return (permissions || []).slice(0, 5).map((code) => permissionMap[code] || code)
}

function rowPermissionRest(row) {
  const permissions = row.permissionTypes?.length ? row.permissionTypes : rolePermissionMap[row.role || 'user']
  return Math.max((permissions?.length || 0) - 5, 0)
}

function permissionIcon(code) {
  if (code.startsWith('soft')) return 'Box'
  if (code.startsWith('auth')) return 'Key'
  if (code.startsWith('cloud')) return 'Files'
  if (code.startsWith('black')) return 'List'
  if (code === 'accountManage') return 'Connection'
  if (code === 'eventView') return 'Tickets'
  if (code === 'messageManage') return 'ChatDotRound'
  return 'CircleCheck'
}

function initialOf(value) {
  return String(value || '?').slice(0, 1).toUpperCase()
}

onMounted(load)
</script>

<style scoped>
.w-full { width: 100%; }
</style>
