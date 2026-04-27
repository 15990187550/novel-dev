import axios from 'axios'
import { ElMessage } from 'element-plus'

const api = axios.create({ baseURL: '/api', timeout: 30000 })
const withSilentError = (config = {}) => ({
  ...config,
  __skipGlobalErrorMessage: true,
})
const withLongTimeout = (timeout = 180000, config = {}) => ({
  ...config,
  timeout,
})

api.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.config?.__skipGlobalErrorMessage) {
      return Promise.reject(err)
    }
    const detail = err.response?.data?.detail
    ElMessage.error(detail || '请求失败')
    return Promise.reject(err)
  }
)

export const listNovels = () => api.get('/novels').then(r => r.data)
export const createNovel = (title) => api.post('/novels', { title }).then(r => r.data)
export const updateNovel = (id, title) => api.patch(`/novels/${id}`, { title }).then(r => r.data)
export const deleteNovel = (id) => api.delete(`/novels/${id}`).then(r => r.data)
export const getNovelState = (id) => api.get(`/novels/${id}/state`).then(r => r.data)
export const getArchiveStats = (id) => api.get(`/novels/${id}/archive_stats`).then(r => r.data)
export const getChapters = (id) => api.get(`/novels/${id}/chapters`).then(r => r.data)
export const getChapterText = (nid, cid) => api.get(`/novels/${nid}/chapters/${cid}/text`).then(r => r.data)
export const getEntities = (id) => api.get(`/novels/${id}/entities`).then(r => r.data)
export const searchEntities = (id, params) => api.get(`/novels/${id}/entities/search`, { params }).then(r => r.data)
export const updateEntity = (id, entityId, payload) =>
  api.patch(`/novels/${id}/entities/${entityId}`, payload).then(r => r.data)
export const updateEntityClassification = (id, entityId, payload) =>
  api.post(`/novels/${id}/entities/${entityId}/classification`, payload).then(r => r.data)
export const deleteEntity = (id, entityId) =>
  api.delete(`/novels/${id}/entities/${entityId}`).then(r => r.data)
export const getEntityRelationships = (id) => api.get(`/novels/${id}/entity_relationships`).then(r => r.data)
export const getTimelines = (id) => api.get(`/novels/${id}/timelines`).then(r => r.data)
export const getSpacelines = (id) => api.get(`/novels/${id}/spacelines`).then(r => r.data)
export const getForeshadowings = (id) => api.get(`/novels/${id}/foreshadowings`).then(r => r.data)
export const getSynopsis = (id) => api.get(`/novels/${id}/synopsis`, withSilentError()).then(r => r.data)
export const getVolumePlan = (id) => api.get(`/novels/${id}/volume_plan`, withSilentError()).then(r => r.data)
export const getOutlineWorkbench = (id, params) =>
  api.get(`/novels/${id}/outline_workbench`, { params }).then(r => r.data)
export const getOutlineWorkbenchMessages = (id, params) =>
  api.get(`/novels/${id}/outline_workbench/messages`, { params }).then(r => r.data)
export const submitOutlineFeedback = (id, payload) =>
  api.post(`/novels/${id}/outline_workbench/submit`, payload, withLongTimeout()).then(r => r.data)
export const clearOutlineContext = (id, payload) =>
  api.post(`/novels/${id}/outline_workbench/clear_context`, payload).then(r => r.data)
export const reviewOutline = (id, payload) =>
  api.post(`/novels/${id}/outline_workbench/review`, payload, withLongTimeout()).then(r => r.data)
export const startBrainstormWorkspace = (id) =>
  api.post(`/novels/${id}/brainstorm/workspace/start`).then(r => r.data)
export const getBrainstormWorkspace = (id) =>
  api.get(`/novels/${id}/brainstorm/workspace`).then(r => r.data)
export const submitBrainstormWorkspace = (id) =>
  api.post(`/novels/${id}/brainstorm/workspace/submit`).then(r => r.data)
export const getReview = (id) => api.get(`/novels/${id}/review`).then(r => r.data)
export const getFastReview = (id) => api.get(`/novels/${id}/fast_review`).then(r => r.data)
export const getPendingDocs = (id) => api.get(`/novels/${id}/documents/pending`).then(r => r.data)
export const getDocumentLibrary = (id) => api.get(`/novels/${id}/documents/library`).then(r => r.data)
export const updateLibraryDocument = (id, docId, payload) =>
  api.patch(`/novels/${id}/documents/library/${docId}`, payload).then(r => r.data)
export const uploadDocument = (id, filename, content, options = {}) =>
  api.post(`/novels/${id}/documents/upload`, { filename, content, ...options }).then(r => r.data)
export const uploadDocumentsBatch = (id, items, maxConcurrency = 3) =>
  api.post(`/novels/${id}/documents/upload/batch`, { items, max_concurrency: maxConcurrency }).then(r => r.data)
export const getKnowledgeDomains = (id, includeDisabled = false) =>
  api.get(`/novels/${id}/knowledge_domains`, { params: { include_disabled: includeDisabled } }).then(r => r.data)
export const createKnowledgeDomain = (id, payload) =>
  api.post(`/novels/${id}/knowledge_domains`, payload).then(r => r.data)
export const updateKnowledgeDomain = (id, domainId, payload) =>
  api.patch(`/novels/${id}/knowledge_domains/${domainId}`, payload).then(r => r.data)
export const confirmKnowledgeDomainScope = (id, domainId, payload) =>
  api.post(`/novels/${id}/knowledge_domains/${domainId}/confirm_scope`, payload).then(r => r.data)
export const disableKnowledgeDomain = (id, domainId) =>
  api.post(`/novels/${id}/knowledge_domains/${domainId}/disable`).then(r => r.data)
export const approvePending = (id, pendingId, fieldResolutions = []) =>
  api.post(`/novels/${id}/documents/pending/approve`, { pending_id: pendingId, field_resolutions: fieldResolutions }).then(r => r.data)
export const updatePendingDraftField = (id, pendingId, payload) =>
  api.patch(`/novels/${id}/documents/pending/${pendingId}/draft-field`, payload).then(r => r.data)
export const rejectPending = (id, pendingId) =>
  api.post(`/novels/${id}/documents/pending/reject`, { pending_id: pendingId }).then(r => r.data)
export const deletePendingDoc = (id, pendingId) =>
  api.delete(`/novels/${id}/documents/pending/${pendingId}`).then(r => r.data)
export const rollbackStyleProfile = (id, version) =>
  api.post(`/novels/${id}/style_profile/rollback`, { version }).then(r => r.data)
export const brainstorm = (id) => api.post(`/novels/${id}/brainstorm`, null, withLongTimeout()).then(r => r.data)
export const importSynopsis = (id, content) =>
  api.post(`/novels/${id}/brainstorm/import`, { content }).then(r => r.data)
export const planVolume = (id, volNum) =>
  api.post(`/novels/${id}/volume_plan`, { volume_number: volNum }, withLongTimeout()).then(r => r.data)
export const prepareContext = (id, cid) =>
  api.post(`/novels/${id}/chapters/${cid}/context`, null, withLongTimeout()).then(r => r.data)
export const draftChapter = (id, cid) =>
  api.post(`/novels/${id}/chapters/${cid}/draft`, null, withLongTimeout()).then(r => r.data)
export const advance = (id) => api.post(`/novels/${id}/advance`, null, withLongTimeout()).then(r => r.data)
export const runLibrarian = (id) => api.post(`/novels/${id}/librarian`, null, withLongTimeout()).then(r => r.data)
export const autoRunChapters = (id, options = {}) =>
  api.post(`/novels/${id}/chapters/auto-run`, {
    max_chapters: options.max_chapters ?? 1,
    stop_at_volume_end: options.stop_at_volume_end ?? true,
  }, withLongTimeout()).then(r => r.data)
export const getGenerationJob = (id, jobId) =>
  api.get(`/novels/${id}/generation_jobs/${jobId}`).then(r => r.data)
export const stopCurrentFlow = (id) => api.post(`/novels/${id}/flow/stop`).then(r => r.data)
export const clearLogs = (id) => api.delete(`/novels/${id}/logs`).then(r => r.data)
export const exportNovel = (id, format = 'md') =>
  api.post(`/novels/${id}/export`, null, { params: { format } }).then(r => r.data)
export const getLLMConfig = () => api.get('/config/llm').then(r => r.data)
export const saveLLMConfig = (config) => api.post('/config/llm', { config }).then(r => r.data)
export const getEnvConfig = () => api.get('/config/env').then(r => r.data)
export const saveEnvConfig = (env) => api.post('/config/env', env).then(r => r.data)
