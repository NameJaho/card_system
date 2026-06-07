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
        <div class="login-links">
          <el-button link @click="forgotVisible = true">找回密码</el-button>
        </div>
      </div>
    </section>
    <el-dialog v-model="forgotVisible" title="找回密码" width="420px">
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
const forgotVisible = ref(false)
const forgotEmail = ref('')
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
</style>
