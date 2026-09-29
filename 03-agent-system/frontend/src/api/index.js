import axios from 'axios'
import { ElMessage } from 'element-plus'

const http = axios.create({ baseURL: '/api', timeout: 30000 })

http.interceptors.response.use(
  (res) => res.data,
  (err) => {
    const detail = err.response?.data?.detail
    let msg = err.message || '请求失败'
    if (typeof detail === 'string') msg = detail
    else if (Array.isArray(detail)) msg = detail.map((d) => d.msg).join('；')
    ElMessage.error(msg)
    return Promise.reject(err)
  },
)

export default {
  // 系统
  getHealth: () => http.get('/health'),
  getStats: () => http.get('/stats'),

  // 会话
  listSessions: () => http.get('/sessions'),
  createSession: (user_id = '') => http.post('/sessions', { user_id }),
  history: (sessionId) => http.get(`/sessions/${sessionId}/history`),

  // 知识库
  knowledge: () => http.get('/knowledge'),
  ingest: (data) => http.post('/knowledge/ingest', data),
  ingestSample: () => http.post('/knowledge/sample'),
  search: (query, top_k) => http.post('/knowledge/search', { query, top_k }),
  knowledgeUpload: (file) => {
    const fd = new FormData()
    fd.append('file', file)
    return http.post('/knowledge/upload', fd, { timeout: 60000 })
  },
  deleteDoc: (docId) => http.delete(`/knowledge/${docId}`),
  clearKnowledge: () => http.post('/knowledge/clear'),

  // 智能问答(真实模型单次推理最长约 2 分钟)
  ask: (payload) => http.post('/ask', payload, { timeout: 180000 }),

  // 商品目录（持久化管理）
  products: () => http.get('/products'),
  createProduct: (data) => http.post('/products', data),
  updateProduct: (productId, fields) => http.put(`/products/${productId}`, fields),
  deleteProduct: (productId) => http.delete(`/products/${productId}`),

  // 内容生成任务
  generate: (payload) => http.post('/content/generate', payload),
  resumeTask: (task_id) => http.post('/content/resume', { task_id }),
  tasks: (session_id) =>
    http.get('/content/tasks', { params: session_id ? { session_id } : {} }),
  task: (taskId) => http.get(`/content/tasks/${taskId}`),

  // 数据管道
  pipelineRun: (records) => http.post('/pipeline/run', { records }),
  pipelineSample: () => http.post('/pipeline/sample'),
  pipelineUpload: (file) => {
    const fd = new FormData()
    fd.append('file', file)
    return http.post('/pipeline/upload', fd, { timeout: 60000 })
  },
}
