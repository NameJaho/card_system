import { ElMessage } from 'element-plus'
import { reactive } from 'vue'

const API_BASE = import.meta.env.VITE_API_BASE || ''
const SESSION_KEYS = ['token', 'user', 'role', 'roleLabel', 'isSubUser', 'permissions']

function readStoredPermissions() {
  try {
    return JSON.parse(localStorage.getItem('permissions') || '{}')
  } catch {
    return {}
  }
}

export const session = reactive({
  token: localStorage.getItem('token') || '',
  user: localStorage.getItem('user') || '',
  role: localStorage.getItem('role') || '',
  roleLabel: localStorage.getItem('roleLabel') || '',
  isSubUser: localStorage.getItem('isSubUser') === 'true',
  permissions: readStoredPermissions()
})

export function getToken() {
  return session.token || localStorage.getItem('token') || ''
}

export function setSession(data) {
  const next = {
    token: data.token || '',
    user: data.user || '',
    role: data.role || '',
    roleLabel: data.roleLabel || '',
    isSubUser: Boolean(data.isSubUser),
    permissions: data.permissions || {}
  }
  localStorage.setItem('token', next.token)
  localStorage.setItem('user', next.user)
  localStorage.setItem('role', next.role)
  localStorage.setItem('roleLabel', next.roleLabel)
  localStorage.setItem('isSubUser', next.isSubUser ? 'true' : 'false')
  localStorage.setItem('permissions', JSON.stringify(next.permissions))
  Object.assign(session, next)
}

export function clearSession() {
  SESSION_KEYS.forEach((key) => localStorage.removeItem(key))
  Object.assign(session, { token: '', user: '', role: '', roleLabel: '', isSubUser: false, permissions: {} })
}

export function permissions() {
  return session.permissions || {}
}

export function hasPermission(code) {
  const current = permissions()
  return Array.isArray(current.permissionTypes) && current.permissionTypes.includes(code)
}

export function hasAnyPermission(codes) {
  return codes.some((code) => hasPermission(code))
}

export async function request(path, body = {}, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    method: options.method || 'POST',
    headers: {
      'Content-Type': 'application/json;charset=UTF-8',
      Authorization: `Bearer ${getToken()}`,
      ...(options.headers || {})
    },
    body: options.method === 'GET' ? undefined : JSON.stringify(body)
  })
  const data = await response.json().catch(() => ({}))
  if (response.status === 401) {
    clearSession()
    location.hash = '#/login'
    throw new Error(data.detail || data.message || 'token 失效了')
  }
  if (!response.ok) {
    const message = data.error?.message || data.detail || data.message || '请求失败'
    ElMessage.warning(message)
    return { ...data, success: false, message, data: data.data }
  }
  if (data && data.success === false) {
    ElMessage.warning(data.message || '请求失败')
  }
  return data
}

export async function downloadCsv(path, body = {}, filename = 'export.csv') {
  const response = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json;charset=UTF-8',
      Authorization: `Bearer ${getToken()}`
    },
    body: JSON.stringify(body)
  })
  const blob = await response.blob()
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  URL.revokeObjectURL(url)
}

export async function downloadFile(path, body = {}, filename = 'download.bin') {
  const response = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json;charset=UTF-8', Authorization: `Bearer ${getToken()}` },
    body: JSON.stringify(body)
  })
  if (!response.ok) {
    const data = await response.json().catch(() => ({}))
    const message = data.error?.message || data.detail || data.message || '下载失败'
    ElMessage.warning(message)
    return false
  }
  const blob = await response.blob()
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  URL.revokeObjectURL(url)
  return true
}

export const api = {
  login: (body) => request('/api/adm/login', body),
  forgotPassword: (body) => request('/api/adm/forgotPassword', body),
  me: () => request('/api/adm/user', {}),
  userConfig: () => request('/api/adm/user-config', {}),
  updateUser: (body) => request('/api/adm/updateUserInfo', body),
  clearFinger: () => request('/api/adm/clearFingerId', {}),
  dataCount: () => request('/api/adm/dataCount', {}),
  softwareList: (body) => request('/api/adm/softwareList', body),
  softwareSelect: () => request('/api/adm/softwareSelect', {}),
  createSoftware: (body) => request('/api/adm/createSoftware', body),
  updateSoftware: (body) => request('/api/adm/updateSoftware', body),
  rotateInstanceKey: (body) => request('/api/adm/rotateInstanceKey', body),
  deleteSoftware: (body) => request('/api/adm/delSoftware', body),
  authList: (body) => request('/api/adm/authList', body),
  createAuth: (body) => request('/api/adm/createAuth', body),
  editAuth: (body) => request('/api/adm/editAuth', body),
  unbindAuth: (body) => request('/api/adm/commitUnBind', body),
  revokeAuth: (body) => request('/api/adm/revokeAuth', body),
  updateAuthRemark: (body) => request('/api/adm/updateAuthRemark', body),
  deleteAuth: (body) => request('/api/adm/delAuth', body),
  batchDeleteAuth: (body) => request('/api/adm/batchDelAuth', body),
  customerList: (body) => request('/api/adm/customerList', body),
  deleteCustomer: (body) => request('/api/adm/delCustomer', body),
  cloudVariables: () => request('/api/adm/cloudVariablesList', {}),
  saveCloudVariables: (body) => request('/api/adm/saveCloudVariables', body),
  blackWhiteList: () => request('/api/adm/blackWhiteList', {}),
  saveBlackWhiteList: (body) => request('/api/adm/saveBlackWhiteList', body),
  events: (body) => request('/api/adm/message/event', body),
  licenseAudits: (body) => request('/api/adm/licenseAuditList', body),
  messages: () => request('/api/adm/message/list', {}),
  sendMessage: (body) => request('/api/adm/message/send', body),
  subUsers: (body) => request('/api/adm/subUserList', body),
  createSubUser: (body) => request('/api/adm/createSubUser', body),
  updateSubUser: (body) => request('/api/adm/updateSubUser', body),
  deleteSubUser: (body) => request('/api/adm/deleteSubUser', body),
  clientUpdate: (body) => request('/api/client/software/checkUpdate', body),
  clientActivate: (body) => request('/api/client/auth/activate', body),
  clientVerify: (body) => request('/api/client/auth/verify', body),
  clientValidate: (body) => request('/api/client/v1/license/validate', body),
  clientUnbind: (body) => request('/api/client/auth/unbind', body),
  clientVars: (body) => request('/api/client/cloudVariables/list', body),
  clientRegister: (body) => request('/api/client/user/register', body),
  clientLogin: (body) => request('/api/client/user/login', body),
  clientHeartbeat: (body) => request('/api/client/user/heartbeat', body),
  clientLogout: (body) => request('/api/client/user/logout', body)
}
