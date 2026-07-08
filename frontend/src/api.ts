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

export const updateMe = (name: string) =>
  api.patch<CurrentUser>('/auth/me', { name }).then(r => r.data)

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
  // Telegram bot session (set via /start, cleared via /finish). session_started_at
  // is the source of truth for "active" — session_project_id may be stale otherwise.
  session_project_id: number | null
  session_started_at: string | null
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

export interface GroupAnalysis {
  metric_group_id: number
  metric_group_name: string
  pains_found: string[]
  pains_addressed: string
  weak_spots: string[]
  summary: string
}

export interface CallDetail extends CallListItem {
  comment: string | null
  language: string | null
  error_message: string | null
  transcription: {
    full_text: string
    language: string | null
    segments: { start: number; end: number; text: string }[]
  } | null
  analysis_results: AnalysisResult[]
  group_analyses: GroupAnalysis[]
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
  metric_group_id: number
  metric_group_name: string
  metric_group_type: 'required_keywords' | 'forbidden_keywords' | 'script_stages'
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

// ── Global analytics dashboard ("Аналитика") ───────────────────────────────
// All accept an optional projectId (omitted = across every project).

export interface AnalyticsOverview {
  total_calls: number
  avg_duration_seconds: number
  avg_score: number
  calls_last_7_days: number
}

export interface CallsTimelinePoint {
  date: string
  call_count: number
}

export interface DurationBucket {
  label: string
  call_count: number
}

export interface HeatmapCell {
  weekday: number
  hour: number
  call_count: number
}

interface GlobalAnalyticsParams {
  projectId?: number
  userId?: number
  dateFrom?: string
  dateTo?: string
}

const globalParams = ({ projectId, userId, dateFrom, dateTo }: GlobalAnalyticsParams) => ({
  project_id: projectId,
  user_id: userId,
  date_from: dateFrom,
  date_to: dateTo,
})

export const getAnalyticsOverview = (params: GlobalAnalyticsParams = {}) =>
  api.get<AnalyticsOverview>('/analytics/overview', { params: globalParams(params) }).then(r => r.data)

export const getCallsTimeline = (params: GlobalAnalyticsParams = {}) =>
  api.get<CallsTimelinePoint[]>('/analytics/timeline', { params: globalParams(params) }).then(r => r.data)

export const getDurationBuckets = (params: GlobalAnalyticsParams = {}) =>
  api.get<DurationBucket[]>('/analytics/duration-buckets', { params: globalParams(params) }).then(r => r.data)

export const getHeatmap = (params: GlobalAnalyticsParams = {}) =>
  api.get<HeatmapCell[]>('/analytics/heatmap', { params: globalParams(params) }).then(r => r.data)

export const getGlobalManagerSummary = (params: GlobalAnalyticsParams = {}) =>
  api.get<ManagerSummary[]>('/analytics/managers', { params: globalParams(params) }).then(r => r.data)

export interface TopErrorItem {
  metric_item_id: number
  metric_name: string
  project_id: number
  project_name: string
  fail_count: number
  total_count: number
  fail_rate: number
}

export interface QualityDistribution {
  high: number
  medium: number
  low: number
  total: number
}

export interface ManagerTrendItem {
  user_id: number
  name: string
  avg_score: number
  call_count: number
  prev_avg_score: number | null
  delta: number | null
}

export interface Kpi {
  avg_score: number
  avg_score_delta: number | null
  calls_analyzed: number
  best_manager: ManagerTrendItem | null
  main_problem: TopErrorItem | null
}

export interface KeywordItem {
  word: string
  count: number
}

export const getKpi = (projectId?: number, userId?: number) =>
  api.get<Kpi>('/analytics/kpi', { params: { project_id: projectId, user_id: userId } }).then(r => r.data)

export const getTopErrors = (params: GlobalAnalyticsParams = {}, limit = 5) =>
  api.get<TopErrorItem[]>('/analytics/top-errors', { params: { ...globalParams(params), limit } }).then(r => r.data)

export interface TopErrorCallItem {
  call_id: number
  user_id: number
  manager_name: string
  created_at: string
  duration_seconds: number | null
  score: number
}

export const getTopErrorCalls = (metricItemId: number, params: GlobalAnalyticsParams = {}, limit = 20) =>
  api.get<TopErrorCallItem[]>(`/analytics/top-errors/${metricItemId}/calls`, {
    params: { user_id: params.userId, date_from: params.dateFrom, date_to: params.dateTo, limit },
  }).then(r => r.data)

export interface ErrorManagerItem {
  user_id: number
  name: string
  fail_count: number
}

export const getTopErrorManagers = (metricItemId: number, params: GlobalAnalyticsParams = {}) =>
  api.get<ErrorManagerItem[]>(`/analytics/top-errors/${metricItemId}/managers`, {
    params: { project_id: params.projectId, date_from: params.dateFrom, date_to: params.dateTo },
  }).then(r => r.data)

export interface ManagerErrorSummary {
  user_id: number
  name: string
  call_count: number
  total_errors: number
  top_errors: TopErrorItem[]
}

export const getManagerErrorSummary = (userId: number, params: GlobalAnalyticsParams = {}, limit = 5) =>
  api.get<ManagerErrorSummary>(`/analytics/managers/${userId}/error-summary`, {
    params: { project_id: params.projectId, date_from: params.dateFrom, date_to: params.dateTo, limit },
  }).then(r => r.data)

export const getQualityDistribution = (params: GlobalAnalyticsParams = {}) =>
  api.get<QualityDistribution>('/analytics/quality-distribution', { params: globalParams(params) }).then(r => r.data)

export const getManagersTrend = (projectId?: number) =>
  api.get<ManagerTrendItem[]>('/analytics/managers/trend', { params: { project_id: projectId } }).then(r => r.data)

export const getKeywords = (params: GlobalAnalyticsParams = {}, limit = 15) =>
  api.get<KeywordItem[]>('/analytics/keywords', { params: { ...globalParams(params), limit } }).then(r => r.data)

// ── Per-manager analytics (manager detail page) ────────────────────────────

export interface ManagerOverview {
  total_calls: number
  avg_duration_seconds: number
  avg_score: number
  active_days: number
  last_call_at: string | null
}

export const getManagerOverview = (userId: number, params: GlobalAnalyticsParams = {}) =>
  api.get<ManagerOverview>(`/analytics/managers/${userId}/overview`, { params: globalParams(params) }).then(r => r.data)

export const getManagerMetrics = (userId: number, projectId: number, dateFrom?: string, dateTo?: string) =>
  api.get<MetricSummary[]>(`/analytics/managers/${userId}/metrics`, {
    params: { project_id: projectId, date_from: dateFrom, date_to: dateTo },
  }).then(r => r.data)

export const getManagerTimeline = (userId: number, params: GlobalAnalyticsParams = {}) =>
  api.get<CallsTimelinePoint[]>(`/analytics/managers/${userId}/timeline`, { params: globalParams(params) }).then(r => r.data)

export interface QualitativeCallSummary {
  call_id: number
  project_id: number
  manager_id: number
  manager_name: string
  metric_group_id: number
  metric_group_name: string
  created_at: string
  pains_found: string[]
  pains_addressed: string
  weak_spots: string[]
  summary: string
}

export const getManagerQualitative = (userId: number, params: GlobalAnalyticsParams = {}) =>
  api.get<QualitativeCallSummary[]>(`/analytics/managers/${userId}/qualitative`, { params: globalParams(params) }).then(r => r.data)

export const getProjectQualitative = (projectId: number, params: GlobalAnalyticsParams = {}) =>
  api.get<QualitativeCallSummary[]>(`/analytics/projects/${projectId}/qualitative`, { params: globalParams(params) }).then(r => r.data)

export const getManagerScoreTimeline = (userId: number, params: GlobalAnalyticsParams = {}) =>
  api.get<TimelinePoint[]>(`/analytics/managers/${userId}/score-timeline`, { params: globalParams(params) }).then(r => r.data)

export const getManagerHeatmap = (userId: number, params: GlobalAnalyticsParams = {}) =>
  api.get<HeatmapCell[]>(`/analytics/managers/${userId}/heatmap`, { params: globalParams(params) }).then(r => r.data)
