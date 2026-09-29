import { reactive } from 'vue'
import api from '../api'

const SESSION_KEY = 'agent-session-id'

/**
 * 全局状态:健康信息、会话(当前选中持久化到 localStorage)、
 * 知识库登记、商品目录、生成任务、统计指标。
 * 会话本体是服务端进程级状态,前端只保存当前选中的 session_id。
 */
export const store = reactive({
  ready: false,
  health: null,
  sessions: [],
  currentSessionId: localStorage.getItem(SESSION_KEY) || '',
  products: [],
  knowledge: { docs: [], total_docs: 0, total_chunks: 0 },
  tasks: [],
  stats: null,

  async init() {
    try {
      this.health = await api.getHealth()
      await this.refreshSessions()
      // 本地记录的会话可能已失效(服务端重启),回退到最新会话或新建
      const exists = this.sessions.some((s) => s.session_id === this.currentSessionId)
      if (!exists) {
        if (this.sessions.length) {
          this.setCurrent(this.sortedSessions[0].session_id)
        } else {
          await this.createSession()
        }
      }
      await Promise.all([
        this.refreshProducts(),
        this.refreshKnowledge(),
        this.refreshTasks(),
        this.refreshStats(),
      ])
    } catch (err) {
      console.error('初始化失败', err)
    } finally {
      this.ready = true
    }
  },

  /** 会话列表按创建时间倒序(最新在前) */
  get sortedSessions() {
    return [...this.sessions].sort((a, b) => (a.created_at < b.created_at ? 1 : -1))
  },

  setCurrent(id) {
    this.currentSessionId = id
    localStorage.setItem(SESSION_KEY, id)
  },

  async createSession() {
    const session = await api.createSession()
    this.sessions.push(session)
    this.setCurrent(session.session_id)
    return session
  },

  async refreshSessions() {
    this.sessions = await api.listSessions()
  },

  async refreshProducts() {
    this.products = await api.products()
  },

  async refreshKnowledge() {
    this.knowledge = await api.knowledge()
  },

  async refreshTasks() {
    this.tasks = await api.tasks()
  },

  async refreshStats() {
    this.stats = await api.getStats()
  },
})

/** 工具:截断 UUID 便于展示 */
export function shortId(id) {
  return id ? id.slice(0, 8) : ''
}

/** 工具:ISO 时间 → 本地可读时间 */
export function fmtTime(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getMonth() + 1}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}
