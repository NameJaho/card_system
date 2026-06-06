<template>
  <div class="panel">
    <div class="toolbar">
      <el-button v-if="canAdd" type="primary" @click="add('')">添加全局变量</el-button>
      <el-select v-model="selectedSoftware" placeholder="按实例添加" clearable style="width: 220px">
        <el-option v-for="item in software" :key="item.softwareId" :label="item.name" :value="item.softwareId" />
      </el-select>
      <el-button v-if="canAdd" @click="add(selectedSoftware)">添加实例变量</el-button>
      <el-button v-if="canWrite" type="success" @click="save">保存</el-button>
    </div>
    <el-table :data="rows">
      <el-table-column label="实例" width="220">
        <template #default="{ row }">
          <el-select v-model="row.softwareId" clearable placeholder="全局" :disabled="!canAdd">
            <el-option label="全局" value="" />
            <el-option v-for="item in software" :key="item.softwareId" :label="item.name" :value="item.softwareId" />
          </el-select>
        </template>
      </el-table-column>
      <el-table-column label="变量名"><template #default="{ row }"><el-input v-model="row.key" :disabled="!canAdd" /></template></el-table-column>
      <el-table-column label="变量值"><template #default="{ row }"><el-input v-model="row.value" :disabled="!canAdd" /></template></el-table-column>
      <el-table-column label="启用" width="100"><template #default="{ row }"><el-switch v-model="row.status" active-value="y" inactive-value="n" :disabled="!canAdd" /></template></el-table-column>
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
const selectedSoftware = ref('')
const canAdd = computed(() => hasPermission('cloudVarAdd'))
const canDelete = computed(() => hasPermission('cloudVarDelete'))
const canWrite = computed(() => canAdd.value || canDelete.value)

function add(softwareId = '') {
  rows.value.push({ key: '', value: '', status: 'y', softwareId: softwareId || '' })
}
async function load() {
  const [vars, sw] = await Promise.all([api.cloudVariables(), api.softwareSelect()])
  if (sw.success) software.value = sw.data
  if (vars.success) rows.value = vars.data?.variables ? JSON.parse(vars.data.variables) : []
}
async function save() {
  const res = await api.saveCloudVariables({ variables: rows.value.filter((item) => item.key) })
  if (res.success) ElMessage.success('保存成功')
}
onMounted(load)
</script>
