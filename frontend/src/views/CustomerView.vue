<template>
  <div class="panel">
    <div class="toolbar">
      <el-input v-model="query.email" placeholder="邮箱" style="width: 220px" />
      <el-input v-model="query.customerId" placeholder="用户编号" style="width: 220px" />
      <el-button type="primary" @click="load">搜索</el-button>
      <el-button @click="reset">重置</el-button>
    </div>
    <el-table v-loading="loading" :data="rows">
      <el-table-column prop="nickName" label="昵称" />
      <el-table-column prop="customerId" label="用户编号" min-width="160" />
      <el-table-column prop="email" label="邮箱" min-width="180" />
      <el-table-column prop="createTime" label="注册时间" min-width="160" />
      <el-table-column label="关联软件" min-width="180">
        <template #default="{ row }">
          <el-tag v-for="(value, key) in row.keys" :key="key" style="margin-right: 6px">{{ key }}: {{ value }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="120">
        <template #default="{ row }"><el-button size="small" type="danger" @click="remove(row)">删除</el-button></template>
      </el-table-column>
    </el-table>
    <el-pagination v-model:current-page="page.pageNum" :total="page.count" layout="total, prev, pager, next" @current-change="load" />
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessageBox } from 'element-plus'
import { api } from '../services/api'

const rows = ref([])
const loading = ref(false)
const query = reactive({ email: '', customerId: '' })
const page = reactive({ pageNum: 1, limit: 10, count: 0 })

async function load() {
  loading.value = true
  try {
    const res = await api.customerList({ ...query, page })
    if (res.success) {
      rows.value = res.data.list
      Object.assign(page, res.data.page)
    }
  } finally {
    loading.value = false
  }
}
function reset() { query.email = ''; query.customerId = ''; page.pageNum = 1; load() }
async function remove(row) {
  await ElMessageBox.confirm(`确定删除用户 ${row.email}？`, '确认删除', { type: 'warning' })
  const res = await api.deleteCustomer({ customerId: row.customerId })
  if (res.success) load()
}
onMounted(load)
</script>
