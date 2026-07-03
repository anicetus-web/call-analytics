/**
 * API client — thin wrapper around axios.
 * Token is stored in localStorage and injected into every request.
 *
 * ⚠ SECURITY NOTE:
 * localStorage is readable by any JS running on the page. If an XSS
 * vulnerability exists, an attacker can steal the token. For a production-grade
 * system, migrate to httpOnly cookies: have the backend set the JWT via
 * Set-Cookie (httpOnly, Secure, SameSite=Strict) from /api/auth/token instead
 * of returning it in the response body, drop the Authorization header
 * injection below, and switch axios to `withCredentials: true`. Also drop
 * OAuth2PasswordBearer in api/auth.py in favor of reading the cookie.
 */
import axios from 'axios'

export const api = axios.create({ baseURL: '/api' })

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

api.interceptors.response.use(
  (r) => r,
  (err) => {
    if (err.response?.status === 401) {
      localStorage.removeItem('token')
      window.location.href = '/login'
    }
    if (err.response?.status === 429) {
      // Rate limit hit on login — surface a human-readable message
      err.message = 'Слишком много попыток входа. Попробуйте через несколько минут.'
    }
    return Promise.reject(err)
  }
)

// ── Auth ──────────────────────────────────────────────────────────────────────

export async function login(username: string, password: string): Promise<void> {
  const form = new URLSearchParams({ username, password })
  const { data } = await api.post('/auth/token', form, {
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
  })
  localStorage.setItem('token', data.access_token)
}

export interface CurrentUser {
  id: number
  name: string
  login: string | null
}

export const getMe = () =>
  api.get<CurrentUser>('/auth/me').then(r => r.data)

export function logout(): void {
  localStorage.removeItem('token')
  window.location.href = '/login'
}

export function isLoggedIn(): boolean {
  return !!localStorage.getItem('token')
}

// ── Projects ──────────────────────────────────────────────────────────────────

export interface Member {
  id: number
  name: string
  telegram_id: number | null
}

export interface Project {
  id: number
  name: string
  description: string | null
  is_active: boolean
  created_by: number
  members: Member[]
}

export const getProjects = (includeInactive = false) =>
  api.get<Project[]>('/projects', { params: { include_inactive: includeInactive } }).then(r => r.data)

export const getProject = (id: number) =>
  api.get<Project>(`/projects/${id}`).then(r => r.data)

export const createProject = (name: string, description?: string) =>
  api.post<Project>('/projects', { name, description }).then(r => r.data)

export const updateProject = (id: number, data: {
  name?: string
  description?: string
  clear_description?: boolean
}) => api.patch<Project>(`/projects/${id}`, data).then(r => r.data)

export const archiveProject = (id: number) =>
  api.delete(`/projects/${id}`)

export const addMember = (projectId: number, userId: number) =>
  api.post(`/projects/${projectId}/members`, { user_id: userId })

export const removeMember = (projectId: number, userId: number) =>
  api.delete(`/projects/${projectId}/members/${userId}`)

// ── Users ─────────────────────────────────────────────────────────────────────

export interface Manager {
  id: number
  name: string
  telegram_id: number | null
  login: string | null
}

export const getManagers = () =>
  api.get<Manager[]>('/users').then(r => r.data)

export const createManager = (data: { name: string; telegram_id: number; login?: string }) =>
  api.post<Manager>('/users', data).then(r => r.data)

export const updateManager = (id: number, data: { name?: string; telegram_id?: number }) =>
  api.patch<Manager>(`/users/${id}`, data).then(r => r.data)

export const deleteManager = (id: number) =>
  api.delete(`/users/${id}`)

// ── Metric groups & items ────────────────────────────────────────────────────

export type MetricGroupType = 'required_keywords' | 'forbidden_keywords' | 'script_stages'

export interface MetricItem {
  id: number
  position: number
  name: string
  description: string | null
  is_active: boolean
}

export interface MetricGroup {
  id: number
  project_id: number
  name: string
  group_type: MetricGroupType
  prompt_template: string
  items: MetricItem[]
}

export const getMetricGroups = (projectId: number) =>
  api.get<MetricGroup[]>(`/projects/${projectId}/metric-groups`).then(r => r.data)

export const createMetricGroup = (projectId: number, data: {
  name: string
  group_type: MetricGroupType
  prompt_template: string
}) => api.post<MetricGroup>(`/projects/${projectId}/metric-groups`, data).then(r => r.data)

export const updateMetricGroup = (id: number, data: { name?: string; prompt_template?: string }) =>
  api.patch<MetricGroup>(`/metric-groups/${id}`, data).then(r => r.data)

export const deleteMetricGroup = (id: number) =>
  api.delete(`/metric-groups/${id}`)

export const createMetricItem = (groupId: number, data: { name: string; description?: string }) =>
  api.post<MetricItem>(`/metric-groups/${groupId}/items`, data).then(r => r.data)

export const updateMetricItem = (id: number, data: {
  name?: string
  description?: string
  clear_description?: boolean
}) => api.patch<MetricItem>(`/metric-items/${id}`, data).then(r => r.data)

export const deleteMetricItem = (id: number) =>
  api.delete(`/metric-items/${id}`)

// ── Calls ─────────────────────────────────────────────────────────────────────

export type CallStatus = 'uploaded' | 'converting' | 'transcribing' | 'analyzing' | 'done' | 'error'

export interface CallListItem {
  id: number
  project_id: number
  user_id: number
  original_filename: string | null
  duration_seconds: number | null
  status: CallStatus
  created_at: string
}

export interface CallDetail extends CallListItem {
  comment: string | null
  language: string | null
  error_message: string | null
  transcription: { full_text: string; language: string | null } | null
  analysis_results: AnalysisResult[]
}

export interface AnalysisResult {
  metric_item_id: number
  metric_item_name: string
  position: number
  score: number
  timecode_start: number | null
}

export const getCalls = (params: {
  project_id?: number
  user_id?: number
  status?: CallStatus
  date_from?: string
  date_to?: string
  limit?: number
  offset?: number
}) => api.get<CallListItem[]>('/calls', { params }).then(r => r.data)

export const getCall = (id: number) =>
  api.get<CallDetail>(`/calls/${id}`).then(r => r.data)

export const getAudioUrl = (id: number) =>
  api.get<{ url: string; expires_in: number }>(`/calls/${id}/audio`).then(r => r.data)

export const reprocessCall = (id: number) =>
  api.post(`/calls/${id}/reprocess`).then(r => r.data)

// ── Analytics ─────────────────────────────────────────────────────────────────

export interface MetricSummary {
  metric_item_id: number
  name: string
  position: number
  avg_score: number
  call_count: number
}

export interface ManagerSummary {
  user_id: number
  name: string
  avg_score: number
  call_count: number
}

export interface TimelinePoint {
  date: string
  avg_score: number
  call_count: number
}

const analyticsParams = (dateFrom?: string, dateTo?: string) => ({
  date_from: dateFrom,
  date_to: dateTo,
})

export const getMetricSummary = (projectId: number, dateFrom?: string, dateTo?: string) =>
  api.get<MetricSummary[]>(`/analytics/projects/${projectId}/summary`, { params: analyticsParams(dateFrom, dateTo) }).then(r => r.data)

export const getManagerSummary = (projectId: number, dateFrom?: string, dateTo?: string) =>
  api.get<ManagerSummary[]>(`/analytics/projects/${projectId}/managers`, { params: analyticsParams(dateFrom, dateTo) }).then(r => r.data)

export const getTimeline = (projectId: number, dateFrom?: string, dateTo?: string) =>
  api.get<TimelinePoint[]>(`/analytics/projects/${projectId}/timeline`, { params: analyticsParams(dateFrom, dateTo) }).then(r => r.data)
