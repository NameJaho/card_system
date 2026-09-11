import { createRouter, createWebHashHistory } from 'vue-router'
import { getToken, hasAnyPermission, hasPermission } from '../services/api'
import LoginView from '../views/LoginView.vue'
import DashboardView from '../views/DashboardView.vue'
import SoftwareView from '../views/SoftwareView.vue'
import AuthView from '../views/AuthView.vue'
import CustomerView from '../views/CustomerView.vue'
import CloudVariablesView from '../views/CloudVariablesView.vue'
import BlackWhiteView from '../views/BlackWhiteView.vue'
import EventsView from '../views/EventsView.vue'
import ProfileView from '../views/ProfileView.vue'
import ProxyView from '../views/ProxyView.vue'
import ClientApiView from '../views/ClientApiView.vue'

const routes = [
  { path: '/login', name: 'login', component: LoginView, meta: { public: true } },
  { path: '/', redirect: '/dashboard' },
  { path: '/dashboard', name: 'dashboard', component: DashboardView },
  { path: '/softWare', name: 'softWare', component: SoftwareView, meta: { permission: 'softView' } },
  { path: '/auth', name: 'auth', component: AuthView, meta: { permissionAny: ['authCreate', 'authDelete', 'authExport', 'authUnbind'] } },
  { path: '/customer', name: 'customer', component: CustomerView, meta: { permission: 'userView' } },
  { path: '/cloudVariables', name: 'cloudVariables', component: CloudVariablesView, meta: { permission: 'cloudVarView' } },
  { path: '/blackWhiteList', name: 'blackWhiteList', component: BlackWhiteView, meta: { permission: 'blackWhiteView' } },
  { path: '/evenList', name: 'evenList', component: EventsView, meta: { permission: 'eventView' } },
  { path: '/user', name: 'user', component: ProfileView },
  { path: '/proxy', name: 'proxy', component: ProxyView, meta: { permission: 'accountManage' } },
  { path: '/client-api', name: 'client-api', component: ClientApiView, meta: { permission: 'softView' } },
  { path: '/:pathMatch(.*)*', redirect: '/dashboard' }
]

const router = createRouter({ history: createWebHashHistory(), routes })

router.beforeEach((to) => {
  if (!to.meta.public && !getToken()) return '/login'
  if (!to.meta.public && to.meta.permission && !hasPermission(to.meta.permission)) return '/dashboard'
  if (!to.meta.public && to.meta.permissionAny && !hasAnyPermission(to.meta.permissionAny)) return '/dashboard'
  return true
})

export default router
