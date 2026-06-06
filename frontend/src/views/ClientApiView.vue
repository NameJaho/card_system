<template>
  <div>
    <div class="panel">
      <h3>软件侧 API 接入测试</h3>
      <p class="muted">这里用于模拟软件客户端调用更新检查、卡密激活/验证、云变量和软件侧用户登录。</p>
      <el-form label-position="top">
        <div class="form-grid">
          <el-form-item label="实例">
            <el-select v-model="form.softwareId">
              <el-option v-for="item in software" :key="item.softwareId" :label="item.name" :value="item.softwareId" />
            </el-select>
          </el-form-item>
          <el-form-item label="卡密"><el-input v-model="form.authId" placeholder="从网络验证页面复制卡密" /></el-form-item>
          <el-form-item label="设备码"><el-input v-model="form.macid" /></el-form-item>
          <el-form-item label="邮箱"><el-input v-model="form.email" /></el-form-item>
          <el-form-item label="密码"><el-input v-model="form.password" type="password" /></el-form-item>
        </div>
      </el-form>
      <div class="toolbar">
        <el-button type="primary" @click="call('update')">检查更新</el-button>
        <el-button @click="call('activate')">激活卡密</el-button>
        <el-button @click="call('verify')">验证卡密</el-button>
        <el-button @click="call('unbind')">解绑卡密</el-button>
        <el-button @click="call('vars')">读取云变量</el-button>
        <el-button @click="call('register')">软件用户注册</el-button>
        <el-button @click="call('login')">软件用户登录</el-button>
        <el-button @click="call('heartbeat')">用户心跳</el-button>
        <el-button @click="call('logout')">用户退出</el-button>
      </div>
    </div>
    <div class="panel">
      <h3>返回结果</h3>
      <pre class="json-box">{{ output }}</pre>
    </div>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { api } from '../services/api'

const software = ref([])
const output = ref('')
const form = reactive({ softwareId: '', authId: '', macid: 'DEMO-MACHINE-1', email: 'client@example.com', password: 'client123456', customerId: '' })

async function load() {
  const res = await api.softwareSelect()
  if (res.success) {
    software.value = res.data
    form.softwareId = software.value[0]?.softwareId || ''
  }
}
async function call(type) {
  const payload = { ...form }
  let res
  if (type === 'update') res = await api.clientUpdate(payload)
  if (type === 'activate') res = await api.clientActivate(payload)
  if (type === 'verify') res = await api.clientVerify(payload)
  if (type === 'unbind') res = await api.clientUnbind(payload)
  if (type === 'vars') res = await api.clientVars(payload)
  if (type === 'register') res = await api.clientRegister({ ...payload, nickName: '客户端用户' })
  if (type === 'login') res = await api.clientLogin(payload)
  if (type === 'heartbeat') res = await api.clientHeartbeat(payload)
  if (type === 'logout') res = await api.clientLogout(payload)
  if (res?.success && res.data?.customerId) form.customerId = res.data.customerId
  output.value = JSON.stringify(res, null, 2)
}
onMounted(load)
</script>
