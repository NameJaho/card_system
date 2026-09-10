<template>
  <div>
    <div class="panel">
      <h3>v1 授权接入测试</h3>
      <p class="muted">使用单一幂等 validate 接口；不会隐式换绑，也不需要桌面端保存实例密钥。</p>
      <el-form label-position="top">
        <div class="form-grid">
          <el-form-item label="实例">
            <el-select v-model="form.softwareId">
              <el-option v-for="item in software" :key="item.softwareId" :label="item.name" :value="item.softwareId" />
            </el-select>
          </el-form-item>
          <el-form-item label="卡密"><el-input v-model="form.authId" placeholder="从网络验证页面复制卡密" /></el-form-item>
          <el-form-item label="安装 ID"><el-input v-model="form.installationId" /></el-form-item>
          <el-form-item label="客户端版本"><el-input v-model="form.clientVersion" /></el-form-item>
        </div>
      </el-form>
      <div class="toolbar">
        <el-button type="primary" @click="validateLicense">激活 / 验证授权</el-button>
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
const form = reactive({ softwareId: '', authId: '', installationId: 'INST-DEMO-MACHINE-1', clientVersion: '1.0.0' })

async function load() {
  const res = await api.softwareSelect()
  if (res.success) {
    software.value = res.data
    form.softwareId = software.value[0]?.softwareId || ''
    form.clientVersion = software.value[0]?.version || '1.0.0'
  }
}
async function validateLicense() {
  const res = await api.clientValidate({
    softwareId: form.softwareId,
    licenseKey: form.authId,
    installationId: form.installationId,
    clientVersion: form.clientVersion
  })
  output.value = JSON.stringify(res, null, 2)
}
onMounted(load)
</script>
