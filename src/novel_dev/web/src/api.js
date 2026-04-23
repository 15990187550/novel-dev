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
export const uploadDocument = (id, filename, content) =>
  api.post(`/novels/${id}/documents/upload`, { filename, content }).then(r => r.data)
export const uploadDocumentsBatch = (id, items, maxConcurrency = 3) =>
  api.post(`/novels/${id}/documents/upload/batch`, { items, max_concurrency: maxConcurrency }).then(r => r.data)
export const approvePending = (id, pendingId, fieldResolutions = []) =>
  api.post(`/novels/${id}/documents/pending/approve`, { pending_id: pendingId, field_resolutions: fieldResolutions }).then(r => r.data)
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
  api.post(`/novels/${id}/chapters/${cid}/context`).then(r => r.data)
export const draftChapter = (id, cid) =>
  api.post(`/novels/${id}/chapters/${cid}/draft`).then(r => r.data)
export const advance = (id) => api.post(`/novels/${id}/advance`).then(r => r.data)
export const runLibrarian = (id) => api.post(`/novels/${id}/librarian`).then(r => r.data)
export const exportNovel = (id, format = 'md') =>
  api.post(`/novels/${id}/export`, null, { params: { format } }).then(r => r.data)
export const getLLMConfig = () => api.get('/config/llm').then(r => r.data)
export const saveLLMConfig = (config) => api.post('/config/llm', { config }).then(r => r.data)
export const getEnvConfig = () => api.get('/config/env').then(r => r.data)
export const saveEnvConfig = (env) => api.post('/config/env', env).then(r => r.data)
