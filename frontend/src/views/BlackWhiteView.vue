<template>
  <div class="panel">
    <div class="toolbar">
      <el-button v-if="canAdd" type="primary" @click="add('white')">添加白名单</el-button>
      <el-button v-if="canAdd" type="warning" @click="add('black')">添加黑名单</el-button>
      <el-button v-if="canWrite" type="success" @click="save">保存</el-button>
    </div>
    <el-table :data="rows">
      <el-table-column label="实例" width="220">
        <template #default="{ row }">
          <el-select v-model="row.softwareId" :disabled="!canAdd">
            <el-option v-for="item in software" :key="item.softwareId" :label="item.name" :value="item.softwareId" />
          </el-select>
        </template>
      </el-table-column>
      <el-table-column label="类型" width="140">
        <template #default="{ row }">
          <el-select v-model="row.type" :disabled="!canAdd"><el-option label="白名单" value="white" /><el-option label="黑名单" value="black" /></el-select>
        </template>
      </el-table-column>
      <el-table-column label="值"><template #default="{ row }"><el-input v-model="row.value" placeholder="设备码/IP/账号" :disabled="!canAdd" /></template></el-table-column>
      <el-table-column label="备注"><template #default="{ row }"><el-input v-model="row.remark" :disabled="!canAdd" /></template></el-table-column>
      <el-table-column v-if="canDelete" label="操作" width="100"><template #default="{ $index }"><el-button type="danger" size="small" @click="rows.splice($index, 1)">删除</el-button></template></el-table-column>
    </el-table>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api, hasPermission } from '../services/api'

const rows = ref([])
const software = ref([])
const canAdd = computed(() => hasPermission('blackWhiteAdd'))
const canDelete = computed(() => hasPermission('blackWhiteDelete'))
const canWrite = computed(() => canAdd.value || canDelete.value)

function add(type) {
  rows.value.push({ type, value: '', remark: '', softwareId: software.value[0]?.softwareId || '' })
}
async function load() {
  const [list, sw] = await Promise.all([api.blackWhiteList(), api.softwareSelect()])
  if (sw.success) software.value = sw.data
  if (list.success) rows.value = list.data.list || []
}
async function save() {
  const res = await api.saveBlackWhiteList({ list: rows.value.filter((item) => item.value) })
  if (res.success) ElMessage.success('保存成功')
}
onMounted(load)
</script>
