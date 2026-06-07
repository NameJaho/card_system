<template>
  <div class="login-page">
    <section class="login-aside">
      <div>
        <div class="brand login-brand">
          <div class="brand-mark">
            <el-icon><Key /></el-icon>
          </div>
          <div>
            <strong>KeyDesk</strong>
            <span>License Ops</span>
          </div>
        </div>
        <h1>授权业务控制台</h1>
        <p>License, activation, customer and runtime policy management.</p>
      </div>
      <div class="tech-board" aria-hidden="true">
        <div class="tech-board-grid"></div>
        <div class="scan-line"></div>
        <span class="node node-a"></span>
        <span class="node node-b"></span>
        <span class="node node-c"></span>
        <div class="trace trace-a"></div>
        <div class="trace trace-b"></div>
        <div class="trace trace-c"></div>
        <div class="core-lock">
          <el-icon><Lock /></el-icon>
        </div>
      </div>
      <div class="login-metrics">
        <div><strong>API</strong><span>Gateway</span></div>
        <div><strong>JWT</strong><span>Session</span></div>
        <div><strong>ACL</strong><span>Policy</span></div>
      </div>
    </section>
    <section class="login-main">
      <div class="login-box">
        <h1>登录后台</h1>
        <p>后台注册已关闭，账号由超级管理员创建并分配角色。</p>
        <el-form label-position="top" @submit.prevent>
          <el-form-item label="账号">
            <el-input v-model="form.user" size="large" placeholder="请输入账号" />
          </el-form-item>
          <el-form-item label="密码">
            <el-input v-model="form.password" size="large" type="password" show-password placeholder="请输入密码" />
          </el-form-item>
          <el-button type="primary" size="large" class="w-full" :loading="loading" @click="submit">
            登录
          </el-button>
        </el-form>
        <div class="smart-login-tip">
          复制管理员分享的整段登录信息后，打开本页面可一键识别账号密码。
        </div>
        <div class="login-links">
          <el-button link :loading="smartLoading" @click="smartLoginFromClipboard">一键识别登录</el-button>
          <el-button link @click="forgotVisible = true">找回密码</el-button>
        </div>
      </div>
    </section>
    <el-dialog v-model="pasteVisible" title="识别分享文本" width="min(460px, calc(100vw - 24px))">
      <el-input
        v-model="pasteText"
        type="textarea"
        :rows="7"
        placeholder="粘贴管理员分享的整段登录信息，系统会自动识别账号和密码并登录"
      />
      <template #footer>
        <el-button @click="pasteVisible = false">取消</el-button>
        <el-button type="primary" :loading="smartLoading" @click="smartLoginFromText(pasteText)">识别并登录</el-button>
      </template>
    </el-dialog>
    <el-dialog v-model="forgotVisible" title="找回密码" width="min(420px, calc(100vw - 24px))">
      <el-input v-model="forgotEmail" placeholder="请输入注册邮箱" />
      <template #footer>
        <el-button @click="forgotVisible = false">取消</el-button>
        <el-button type="primary" @click="sendForgot">发送</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Key, Lock } from '@element-plus/icons-vue'
import { api, clearSession, setSession } from '../services/api'

const router = useRouter()
const loading = ref(false)
const smartLoading = ref(false)
const forgotVisible = ref(false)
const forgotEmail = ref('')
const pasteVisible = ref(false)
const pasteText = ref('')
const form = reactive({ user: '', password: '' })

async function submit() {
  loading.value = true
  try {
    const payload = { user: form.user.trim(), password: form.password }
    if (!payload.user || !payload.password) {
      ElMessage.warning('请输入账号和密码')
      return
    }
    const res = await api.login(payload)
    if (res.success) {
      setSession(res.data)
      ElMessage.success('登录成功')
      router.push('/dashboard')
    }
  } finally {
    loading.value = false
  }
}

async function sendForgot() {
  const res = await api.forgotPassword({ email: forgotEmail.value })
  if (res.success) {
    ElMessage.success(res.message)
    forgotVisible.value = false
  }
}

function parseSharedCredentials(text) {
  const raw = String(text || '').trim()
  if (!raw) return null
  const userMatch = raw.match(/(?:账号|用户名|账户|user|username|account)\s*[：:=]\s*([^\s,，;；]+)/i)
  const passwordMatch = raw.match(/(?:密码|password|pass|pwd)\s*[：:=]\s*([^\s,，;；]+)/i)
  if (userMatch && passwordMatch) {
    return { user: userMatch[1].trim(), password: passwordMatch[1].trim() }
  }
  const lines = raw.split(/\r?\n/).map((line) => line.trim()).filter(Boolean)
  const compact = lines.filter((line) => !/(登录地址|角色|实例范围|后台账号登录信息|使用方式|安全提示|一键识别登录|修改密码)/.test(line))
  if (compact.length >= 2) return { user: compact[0], password: compact[1] }
  return null
}

async function smartLogin(text) {
  const credentials = parseSharedCredentials(text)
  if (!credentials) {
    ElMessage.warning('未识别到账号和密码，请粘贴完整分享文本')
    pasteVisible.value = true
    return
  }
  form.user = credentials.user
  form.password = credentials.password
  pasteVisible.value = false
  await submit()
}

async function smartLoginFromText(text) {
  smartLoading.value = true
  try {
    await smartLogin(text)
  } finally {
    smartLoading.value = false
  }
}

async function smartLoginFromClipboard() {
  smartLoading.value = true
  try {
    if (!navigator.clipboard?.readText) {
      pasteVisible.value = true
      return
    }
    const text = await navigator.clipboard.readText()
    pasteText.value = text
    await smartLogin(text)
  } catch {
    pasteVisible.value = true
    ElMessage.warning('浏览器未允许读取剪贴板，请手动粘贴分享文本')
  } finally {
    smartLoading.value = false
  }
}

onMounted(() => {
  clearSession()
})
</script>

<style scoped>
.w-full {
  width: 100%;
}

.login-brand {
  padding: 0 0 36px;
}

.login-links {
  display: flex;
  justify-content: space-between;
  margin-top: 14px;
}

.smart-login-tip {
  color: var(--muted);
  font-size: 12px;
  line-height: 1.55;
  margin-top: 12px;
}
</style>
