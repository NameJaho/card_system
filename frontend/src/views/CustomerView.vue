<template>
  <div class="panel customer-panel">
    <div class="customer-toolbar">
      <div class="toolbar-copy">
        <span class="summary-kicker">Client Users</span>
        <strong>终端用户</strong>
        <span>查看软件侧注册用户和关联实例数据。</span>
      </div>
      <div class="customer-filters">
        <el-input v-model="query.email" :prefix-icon="Message" placeholder="邮箱" clearable @keyup.enter="search" />
        <el-input v-model="query.customerId" :prefix-icon="User" placeholder="用户编号" clearable @keyup.enter="search" />
        <el-button type="primary" :icon="Search" @click="search">搜索</el-button>
        <el-button :icon="Refresh" @click="reset">重置</el-button>
      </div>
    </div>

    <el-table class="desktop-data-table" v-loading="loading" :data="rows">
      <el-table-column label="用户" min-width="230">
        <template #default="{ row }">
          <div class="account-cell">
            <span class="account-avatar">{{ initialOf(row.nickName || row.email) }}</span>
            <div>
              <strong>{{ row.nickName || '未设置昵称' }}</strong>
              <span>{{ row.email || '未设置邮箱' }}</span>
            </div>
          </div>
        </template>
      </el-table-column>
      <el-table-column prop="customerId" label="用户编号" min-width="170" />
      <el-table-column prop="createTime" label="注册时间" min-width="160" />
      <el-table-column label="关联软件" min-width="180">
        <template #default="{ row }">
          <div class="permission-tags">
            <el-tag v-for="(value, key) in row.keys" :key="key">{{ key }}: {{ value }}</el-tag>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="120">
        <template #default="{ row }"><el-button size="small" type="danger" :icon="Delete" @click="remove(row)">删除</el-button></template>
      </el-table-column>
    </el-table>

    <div v-loading="loading" class="mobile-card-list customer-mobile-list">
      <article v-for="row in rows" :key="row.customerId" class="mobile-record-card customer-record-card">
        <div class="mobile-record-head">
          <div class="account-cell">
            <span class="account-avatar">{{ initialOf(row.nickName || row.email) }}</span>
            <div>
              <strong>{{ row.nickName || '未设置昵称' }}</strong>
              <span>{{ row.email || '未设置邮箱' }}</span>
            </div>
          </div>
        </div>
        <div class="mobile-record-meta">
          <span><b>编号</b><em>{{ row.customerId }}</em></span>
          <span><b>注册</b><em>{{ row.createTime || '未知' }}</em></span>
        </div>
        <div class="mobile-chip-section">
          <span>关联软件</span>
          <div class="permission-tags">
            <el-tag v-for="(value, key) in row.keys" :key="key">{{ key }}: {{ value }}</el-tag>
            <span v-if="!row.keys || Object.keys(row.keys).length === 0" class="permission-more">暂无关联</span>
          </div>
        </div>
        <div class="mobile-record-actions">
          <el-button size="small" type="danger" :icon="Delete" @click="remove(row)">删除用户</el-button>
        </div>
      </article>
      <el-empty v-if="!loading && rows.length === 0" description="暂无终端用户" />
    </div>

    <el-pagination
      v-model:current-page="page.pageNum"
      :total="page.count"
      layout="total, prev, pager, next"
      @current-change="load"
    />
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessageBox } from 'element-plus'
import { Delete, Message, Refresh, Search, User } from '@element-plus/icons-vue'
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
function search() {
  page.pageNum = 1
  load()
}
function reset() {
  query.email = ''
  query.customerId = ''
  search()
}
async function remove(row) {
  await ElMessageBox.confirm(`确定删除用户 ${row.email}？`, '确认删除', { type: 'warning' })
  const res = await api.deleteCustomer({ customerId: row.customerId })
  if (res.success) load()
}

function initialOf(value) {
  return String(value || '?').slice(0, 1).toUpperCase()
}

onMounted(load)
</script>
