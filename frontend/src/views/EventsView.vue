<template>
  <div class="panel">
    <div class="toolbar">
      <el-date-picker v-model="query.time" type="daterange" range-separator="至" start-placeholder="开始日期" end-placeholder="结束日期" />
      <el-select v-model="query.type" clearable placeholder="类型" style="width: 140px">
        <el-option label="api" value="api" />
        <el-option label="login" value="login" />
      </el-select>
      <el-input v-model="query.keyword" placeholder="关键词" style="width: 220px" />
      <el-button type="primary" @click="load">搜索</el-button>
    </div>
    <el-table v-loading="loading" :data="rows">
      <el-table-column prop="type" label="类型" width="100" />
      <el-table-column prop="keyword" label="事件" width="130" />
      <el-table-column prop="softwareId" label="实例 ID" min-width="150" />
      <el-table-column prop="authId" label="卡密" min-width="180" />
      <el-table-column prop="macid" label="设备码" min-width="150" />
      <el-table-column prop="result" label="结果" width="100" />
      <el-table-column prop="message" label="说明" min-width="160" />
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
const query = reactive({ time: null, type: null, keyword: '' })
const page = reactive({ pageNum: 1, limit: 10, count: 0 })

async function load() {
  loading.value = true
  try {
    const res = await api.events({ ...query, page })
    if (res.success) {
      rows.value = res.data.list
      Object.assign(page, res.data.page)
    }
  } finally {
    loading.value = false
  }
}
onMounted(load)
</script>
