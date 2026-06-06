<template>
  <router-view v-if="$route.meta.public" />
  <div v-else class="shell">
    <div class="ambient-grid" aria-hidden="true"></div>
    <div class="ambient-matrix" aria-hidden="true">
      <span class="data-beam beam-a"></span>
      <span class="data-beam beam-b"></span>
      <span class="data-beam beam-c"></span>
      <span class="mesh-node mesh-a"></span>
      <span class="mesh-node mesh-b"></span>
      <span class="mesh-node mesh-c"></span>
      <span class="mesh-node mesh-d"></span>
    </div>
    <aside class="sidebar">
      <div class="brand">
        <div class="brand-mark">
          <span class="brand-ring"></span>
          <el-icon><Key /></el-icon>
        </div>
        <div>
          <strong>KeyDesk</strong>
          <span>License Ops</span>
        </div>
      </div>
      <div class="side-section">Main</div>
      <nav>
        <router-link v-for="item in navItems" :key="item.path" :to="item.path" class="nav-item">
          <el-icon><component :is="item.icon" /></el-icon>
          <span>{{ item.label }}</span>
        </router-link>
      </nav>
      <div class="sidebar-footer">
        <span class="status-dot"></span>
        <div>
          <strong>API Online</strong>
          <span>Local instance</span>
        </div>
      </div>
    </aside>
    <main class="workspace">
      <header class="topbar">
        <div class="page-heading">
          <span class="eyebrow">{{ route.name }}</span>
          <h1>{{ pageTitle }}</h1>
        </div>
        <div class="top-actions">
          <div class="ops-chip">
            <span class="radar-core"><i></i></span>
            <span class="signal-bars"><i></i><i></i><i></i></span>
            <span>Live Ops</span>
          </div>
          <el-button :icon="Refresh" circle @click="$router.go(0)" />
          <div class="top-user" @click="$router.push('/user')">
            <el-avatar :size="34">{{ userInitial }}</el-avatar>
            <div>
              <strong>{{ user }}</strong>
              <span>{{ roleLabel }}</span>
            </div>
          </div>
        </div>
      </header>
      <section class="content">
        <router-view v-slot="{ Component }">
          <transition name="route-fade" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </section>
    </main>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { Key, Refresh } from '@element-plus/icons-vue'
import { hasAnyPermission, hasPermission, session } from './services/api'

const route = useRoute()
const user = computed(() => session.user || '未登录')
const userInitial = computed(() => user.value.slice(0, 1).toUpperCase())
const roleLabel = computed(() => session.roleLabel || '未授权')

const allNavItems = [
  { path: '/dashboard', label: '我的数据', icon: 'DataAnalysis' },
  { path: '/softWare', label: '实例列表', icon: 'Box', permission: 'softView' },
  { path: '/auth', label: '网络验证', icon: 'Key', permissionAny: ['authCreate', 'authDelete', 'authExport', 'authUnbind'] },
  { path: '/customer', label: '用户管理', icon: 'User', permission: 'userView' },
  { path: '/cloudVariables', label: '云变量', icon: 'Files', permission: 'cloudVarView' },
  { path: '/blackWhiteList', label: '黑白名单', icon: 'List', permission: 'blackWhiteView' },
  { path: '/evenList', label: '事件日志', icon: 'Tickets', permission: 'eventView' },
  { path: '/proxy', label: '账号管理', icon: 'Connection', permission: 'accountManage' },
  { path: '/client-api', label: '接入测试', icon: 'Cpu' },
  { path: '/user', label: '个人中心', icon: 'Setting' }
]

const navItems = computed(() => allNavItems.filter((item) => {
  if (item.permission) return hasPermission(item.permission)
  if (item.permissionAny) return hasAnyPermission(item.permissionAny)
  return true
}))

const pageTitle = computed(() => {
  const item = allNavItems.find((entry) => entry.path === route.path)
  return item ? item.label : '管理后台'
})
</script>
