<template>
  <div>
    <div class="panel">
      <div class="toolbar">
        <el-button type="primary" @click="load">刷新</el-button>
        <el-button @click="save">保存资料</el-button>
        <el-button v-if="isDeveloper" @click="regen">重新生成 OpenId/Token</el-button>
        <el-button @click="clearFinger">清除免密码登录</el-button>
        <el-button type="danger" @click="logout">退出登录</el-button>
      </div>
      <el-form label-position="top">
        <div class="form-grid">
          <el-form-item label="账号"><el-input v-model="profile.user" disabled /></el-form-item>
          <el-form-item label="角色"><el-input v-model="profile.roleLabel" disabled /></el-form-item>
          <el-form-item label="昵称"><el-input v-model="profile.nick" /></el-form-item>
          <el-form-item label="邮箱"><el-input v-model="profile.email" /></el-form-item>
          <el-form-item label="QQ"><el-input v-model="profile.qq" /></el-form-item>
        </div>
        <el-form-item v-if="isDeveloper" label="OpenId"><el-input v-model="profile.openId" readonly /></el-form-item>
        <el-form-item v-if="isDeveloper" label="Account Token"><el-input v-model="profile.accountToken" readonly /></el-form-item>
      </el-form>
    </div>
    <div v-if="canManageMessages" class="panel">
      <h3>消息</h3>
      <div class="toolbar">
        <el-input v-model="message" placeholder="发送一条后台消息" />
        <el-button type="primary" @click="send">发送</el-button>
      </div>
      <el-table :data="messages">
        <el-table-column prop="content" label="内容" />
        <el-table-column prop="createTime" label="时间" width="180" />
      </el-table>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { api, clearSession, hasPermission, session } from '../services/api'

const router = useRouter()
const profile = reactive({ user: '', role: '', roleLabel: '', nick: '', email: '', qq: '', openId: '', accountToken: '' })
const messages = ref([])
const message = ref('')
const isDeveloper = computed(() => session.role === 'developer')
const canManageMessages = computed(() => hasPermission('messageManage'))

async function load() {
  const [me, list] = await Promise.all([api.me(), canManageMessages.value ? api.messages() : Promise.resolve({ success: true, data: [] })])
  if (me.success) Object.assign(profile, me.data)
  if (list.success) messages.value = list.data
}
async function save() {
  const res = await api.updateUser({ nick: profile.nick, email: profile.email, qq: profile.qq })
  if (res.success) ElMessage.success('保存成功')
}
async function regen() {
  const suffix = Math.random().toString(36).slice(2, 14)
  const res = await api.updateUser({ openId: `open_${suffix}`, accountToken: `acct_${suffix}` })
  if (res.success) {
    ElMessage.success('已重新生成')
    load()
  }
}
async function clearFinger() {
  const res = await api.clearFinger()
  if (res.success) ElMessage.success('已清除')
}
async function send() {
  if (!message.value) return
  const res = await api.sendMessage({ content: message.value })
  if (res.success) {
    message.value = ''
    load()
  }
}
function logout() {
  clearSession()
  router.push('/login')
}
onMounted(load)
</script>
