<template>
  <div class="panel">
    <el-tabs v-model="mode" @tab-change="switchMode">
      <el-tab-pane label="v2 授权审计" name="v2" />
      <el-tab-pane label="兼容事件" name="legacy" />
    </el-tabs>
    <div class="toolbar">
      <el-date-picker v-model="query.time" type="daterange" range-separator="至" start-placeholder="开始日期" end-placeholder="结束日期" />
      <el-select v-if="mode === 'legacy'" v-model="query.type" clearable placeholder="类型" style="width: 140px">
        <el-option label="api" value="api" />
        <el-option label="login" value="login" />
      </el-select>
      <el-select v-else v-model="query.resultCode" clearable placeholder="结果" style="width: 220px">
        <el-option label="授权有效" value="LICENSE_VALID" />
        <el-option label="设备不匹配" value="LICENSE_DEVICE_MISMATCH" />
        <el-option label="设备证明无效" value="DEVICE_PROOF_INVALID" />
        <el-option label="请求重放" value="REQUEST_REPLAYED" />
        <el-option label="已撤销" value="LICENSE_REVOKED" />
        <el-option label="已过期" value="LICENSE_EXPIRED" />
      </el-select>
      <el-input v-model="query.keyword" placeholder="关键词" style="width: 220px" />
      <el-button type="primary" @click="load">搜索</el-button>
    </div>
    <el-table v-if="mode === 'legacy'" v-loading="loading" :data="rows">
      <el-table-column prop="type" label="类型" width="100" />
      <el-table-column prop="keyword" label="事件" width="130" />
      <el-table-column prop="softwareId" label="实例 ID" min-width="150" />
      <el-table-column prop="authId" label="卡记录标识" min-width="180" />
      <el-table-column prop="macid" label="设备码" min-width="150" />
      <el-table-column prop="result" label="结果" width="100" />
      <el-table-column prop="message" label="说明" min-width="160" />
      <el-table-column prop="createTime" label="时间" min-width="160" />
    </el-table>
    <el-table v-else v-loading="loading" :data="rows">
      <el-table-column prop="requestId" label="Request ID" min-width="250" show-overflow-tooltip />
      <el-table-column prop="softwareId" label="实例 ID" min-width="150" />
      <el-table-column label="卡密尾号" width="120">
        <template #default="{ row }">{{ row.licenseLast4 ? `KM••••${row.licenseLast4}` : '-' }}</template>
      </el-table-column>
      <el-table-column prop="licenseRef" label="卡记录引用" min-width="210" show-overflow-tooltip />
      <el-table-column prop="clientVersion" label="客户端" width="110" />
      <el-table-column prop="resultCode" label="结果码" min-width="210" />
      <el-table-column prop="installationHash" label="设备摘要" min-width="180" show-overflow-tooltip />
      <el-table-column prop="sourceIp" label="来源 IP" width="140" />
      <el-table-column prop="createTime" label="时间" min-width="160" />
    </el-table>
    <el-pagination v-model:current-page="page.pageNum" :total="page.count" layout="total, prev, pager, next" @current-change="load" />
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { api } from '../services/api'

const rows = ref([])
const loading = ref(false)
const mode = ref('v2')
const query = reactive({ time: null, type: null, resultCode: '', keyword: '' })
const page = reactive({ pageNum: 1, limit: 10, count: 0 })

async function load() {
  loading.value = true
  try {
    const res = mode.value === 'v2'
      ? await api.licenseAudits({ ...query, page })
      : await api.events({ ...query, page })
    if (res.success) {
      rows.value = res.data.list
      Object.assign(page, res.data.page)
    }
  } finally {
    loading.value = false
  }
}

function switchMode() {
  page.pageNum = 1
  rows.value = []
  load()
}
onMounted(load)
</script>
