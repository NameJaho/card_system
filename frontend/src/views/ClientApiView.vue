<template>
  <div>
    <div class="panel">
      <h3>v2 官方 SDK 验证</h3>
      <p class="muted">v2 必须由设备私钥签名请求，并验证服务端 Ed25519 lease。浏览器后台不模拟设备身份，也不再调用可降级的 v1 接口。</p>
      <el-form label-position="top">
        <el-form-item label="实例">
          <el-select v-model="softwareId" class="w-full">
            <el-option v-for="item in software" :key="item.softwareId" :label="`${item.name} · ${item.softwareId}`" :value="item.softwareId" />
          </el-select>
        </el-form-item>
      </el-form>
      <el-descriptions v-if="selectedSoftware" :column="1" border>
        <el-descriptions-item label="授权协议">v2（最低 v{{ selectedSoftware.minimumProtocolVersion || 1 }}）</el-descriptions-item>
        <el-descriptions-item label="客户端版本">{{ selectedSoftware.version }}</el-descriptions-item>
        <el-descriptions-item label="复验策略">每 {{ selectedSoftware.nextCheckAfterSeconds || 60 }} 秒；lease {{ selectedSoftware.leaseTtlSeconds || 300 }} 秒</el-descriptions-item>
      </el-descriptions>
      <div class="toolbar">
        <el-button type="primary" :disabled="!softwareId" @click="downloadSdk">下载已固化信任根的 Python SDK</el-button>
      </div>
    </div>
    <div class="panel">
      <h3>安全烟雾测试</h3>
      <p class="muted">解压后安装依赖，使用专用测试卡运行。完整卡密只会在创建结果中显示一次，历史列表不会再次返回。</p>
      <pre class="json-box">pip install cryptography
python smoke_test.py</pre>
      <p class="muted">验收时还应确认：无签名假响应、错误签名、修改后的 token、复制 installation ID 但没有原设备私钥，全部被拒绝。</p>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { api, downloadFile } from '../services/api'

const software = ref([])
const softwareId = ref('')
const selectedSoftware = computed(() => software.value.find((item) => item.softwareId === softwareId.value))

async function load() {
  const res = await api.softwareSelect()
  if (res.success) {
    software.value = res.data
    softwareId.value = software.value[0]?.softwareId || ''
  }
}

async function downloadSdk() {
  if (!softwareId.value) return
  await downloadFile(
    '/api/adm/clientPackage',
    { softwareId: softwareId.value },
    `keydesk-${softwareId.value}-python-v2.zip`
  )
}

onMounted(load)
</script>

<style scoped>
.w-full { width: 100%; }
</style>
