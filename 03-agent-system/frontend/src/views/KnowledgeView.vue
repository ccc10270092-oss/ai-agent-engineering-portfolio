<script setup>
import { computed, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete, DocumentCopy, Search, UploadFilled } from '@element-plus/icons-vue'
import api from '../api'
import SourceChunkCard from '../components/SourceChunkCard.vue'
import { fmtTime, store } from '../store/app'

const form = reactive({ title: '', content: '', source: '' })
const submitting = ref(false)
const loadingSample = ref(false)

// ---------- 文件上传入库 ----------
const uploading = ref(false)

function beforeUpload(file) {
  const ok = /\.(txt|md|csv|pdf|docx)$/i.test(file.name || '')
  if (!ok) ElMessage.error('仅支持 .txt / .md / .csv / .pdf / .docx 文件')
  return ok
}

async function customUpload({ file }) {
  uploading.value = true
  try {
    const res = await api.knowledgeUpload(file)
    const auto = res.entry.product ? `,已自动登记商品「${res.entry.product.name}」` : ''
    ElMessage.success(`《${res.entry.title}》已入库,切分为 ${res.chunks} 个切片${auto}`)
    await Promise.all([store.refreshKnowledge(), store.refreshStats(), store.refreshProducts()])
  } finally {
    uploading.value = false
  }
}

// ---------- 文档管理 ----------
async function removeDoc(d) {
  try {
    await ElMessageBox.confirm(`确定删除《${d.title}》?其全部切片与向量索引将同步移除。`, '删除文档', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning',
    })
  } catch {
    return
  }
  await api.deleteDoc(d.doc_id)
  ElMessage.success(`已删除《${d.title}》`)
  await Promise.all([store.refreshKnowledge(), store.refreshStats()])
}

const clearing = ref(false)

async function clearAll() {
  try {
    await ElMessageBox.confirm('确定清空整个知识库?文档登记、全文索引与向量将全部删除。', '清空知识库', {
      confirmButtonText: '清空',
      cancelButtonText: '取消',
      type: 'warning',
    })
  } catch {
    return
  }
  clearing.value = true
  try {
    await api.clearKnowledge()
    ElMessage.success('知识库已清空')
    await Promise.all([store.refreshKnowledge(), store.refreshStats()])
  } finally {
    clearing.value = false
  }
}

// ---------- 向量模式展示(来自 /api/health) ----------
const embedding = computed(() => store.health?.embedding || null)
const embeddingTagType = computed(() => {
  if (!embedding.value) return 'info'
  if (embedding.value.fallback) return 'warning'
  return { local: 'success', api: 'success', hash: 'info' }[embedding.value.mode] || 'info'
})
const embeddingLabel = computed(() => {
  const e = embedding.value
  if (!e) return '向量 —'
  const names = { local: '本地向量', api: 'API 向量', hash: '特征哈希(离线)' }
  const base = names[e.mode] || e.mode
  return e.fallback ? `${base} · 已降级` : base
})

// ---------- 手动录入 ----------
async function submit() {
  if (!form.title.trim() || !form.content.trim()) {
    ElMessage.warning('请填写文档标题与内容')
    return
  }
  submitting.value = true
  try {
    const res = await api.ingest({ ...form })
    const auto = res.entry.product ? `,已自动登记商品「${res.entry.product.name}」` : ''
    ElMessage.success(`已入库,切分为 ${res.chunks} 个切片${auto}`)
    Object.assign(form, { title: '', content: '', source: '' })
    await Promise.all([store.refreshKnowledge(), store.refreshStats(), store.refreshProducts()])
  } finally {
    submitting.value = false
  }
}

async function loadSample() {
  loadingSample.value = true
  try {
    const res = await api.ingestSample()
    await Promise.all([
      store.refreshKnowledge(),
      store.refreshStats(),
      store.refreshProducts(),
    ])
    ElMessage.success(`已载入 4 篇示例文档,共 ${res.total_chunks} 个切片`)
  } finally {
    loadingSample.value = false
  }
}

// ---------- 检索验证 ----------
const searchForm = reactive({ query: '', top_k: 5 })
const searching = ref(false)
const hits = ref(null)

async function doSearch() {
  if (!searchForm.query.trim()) return
  searching.value = true
  try {
    hits.value = await api.search(searchForm.query, searchForm.top_k)
  } finally {
    searching.value = false
  }
}
</script>

<template>
  <div class="page knowledge">
    <div class="kb-grid">
      <!-- 入库:文件上传 + 手动录入 -->
      <section class="card card-pad">
        <h3 class="card-title">文档入库</h3>
        <p class="card-desc">滑动窗口切片(默认 512 / 重叠 64),双路写入 FTS5 与向量索引</p>

        <div v-loading="uploading" class="kb-upload-wrap">
          <el-upload
            drag
            class="kb-upload"
            accept=".txt,.md,.csv,.pdf,.docx"
            :show-file-list="false"
            :http-request="customUpload"
            :before-upload="beforeUpload"
          >
            <div class="upload-inner">
              <el-icon :size="36" class="upload-icon"><UploadFilled /></el-icon>
              <div class="upload-text">拖拽知识文档到此处,或点击上传</div>
              <div class="upload-hint">
                支持 .txt / .md / .csv / .pdf / .docx,上限 10MB;CSV 问答表自动按「问 / 答」格式化
              </div>
              <div class="upload-hint">产品参数文档入库后自动登记到商品目录,内容生成页立即可选</div>
            </div>
          </el-upload>
        </div>

        <el-divider class="kb-divider" />

        <el-form label-position="top" @submit.prevent>
          <el-form-item label="文档标题">
            <el-input v-model="form.title" placeholder="如:智能门锁 S1 参数" maxlength="200" />
          </el-form-item>
          <el-form-item label="来源(可选)">
            <el-input v-model="form.source" placeholder="如:产品手册 / 官网 FAQ" maxlength="200" />
          </el-form-item>
          <el-form-item label="文档内容">
            <el-input
              v-model="form.content"
              type="textarea"
              :rows="6"
              placeholder="粘贴文档正文…"
            />
          </el-form-item>
          <div class="form-actions">
            <el-button type="primary" :loading="submitting" @click="submit">入库</el-button>
            <el-button :icon="DocumentCopy" :loading="loadingSample" @click="loadSample">
              一键载入示例知识库
            </el-button>
          </div>
        </el-form>
      </section>

      <!-- 已入库列表 -->
      <section class="card card-pad docs-card">
        <div class="docs-head">
          <div class="docs-head-left">
            <h3 class="card-title">已入库文档</h3>
            <div class="docs-count">
              <span class="num">{{ store.knowledge.total_docs }}</span> 篇 ·
              <span class="num">{{ store.knowledge.total_chunks }}</span> 切片
            </div>
          </div>
          <div class="docs-head-right">
            <el-tag v-if="embedding" :type="embeddingTagType" size="small" effect="plain">
              {{ embeddingLabel }}{{ embedding.model && embedding.mode !== 'hash' ? ` · ${embedding.model}` : '' }}
            </el-tag>
            <el-button
              v-if="store.knowledge.docs.length"
              size="small"
              type="danger"
              plain
              :icon="Delete"
              :loading="clearing"
              @click="clearAll"
            >
              清空
            </el-button>
          </div>
        </div>
        <p class="card-desc">
          知识库(文档登记 + FTS 全文 + 向量)本地持久化,重启不丢;同文档重复入库自动覆盖
        </p>
        <div class="docs-list">
          <div v-if="!store.knowledge.docs.length" class="docs-empty">
            暂无文档,左侧上传文件、手动入库或一键载入示例
          </div>
          <div v-for="d in store.knowledge.docs" :key="d.doc_id" class="doc-item">
            <div class="doc-icon"><el-icon :size="15"><DocumentCopy /></el-icon></div>
            <div class="doc-info">
              <div class="doc-title">{{ d.title }}</div>
              <div class="doc-meta">{{ d.source }} · {{ fmtTime(d.created_at) }}</div>
            </div>
            <el-tag size="small" effect="plain" type="info">{{ d.chunks }} 切片</el-tag>
            <el-button
              class="doc-del"
              size="small"
              text
              type="danger"
              :icon="Delete"
              @click="removeDoc(d)"
            />
          </div>
        </div>
      </section>
    </div>

    <!-- 检索验证 -->
    <section class="card card-pad">
      <h3 class="card-title">检索验证</h3>
      <p class="card-desc">混合检索:FTS5 全文 + 向量双路召回,各自归一化后按权重融合排序</p>
      <div class="search-bar">
        <el-input
          v-model="searchForm.query"
          placeholder="输入查询,验证知识库召回效果…"
          clearable
          @keydown.enter="doSearch"
        />
        <el-input-number v-model="searchForm.top_k" :min="1" :max="20" />
        <el-button type="primary" :icon="Search" :loading="searching" @click="doSearch">
          检索
        </el-button>
      </div>

      <div v-if="hits === null" class="search-empty">入库后输入查询词,查看命中片段与融合得分</div>
      <div v-else-if="!hits.length" class="search-empty">未命中任何切片,试试其他关键词或先入库文档</div>
      <div v-else class="hits">
        <SourceChunkCard v-for="(c, i) in hits" :key="i" :chunk="c" show-scores />
      </div>
    </section>
  </div>
</template>

<style scoped>
.knowledge {
  max-width: 1200px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.kb-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
  align-items: start;
}

.form-actions {
  display: flex;
  gap: 12px;
}

/* ---------- 上传 ---------- */
.kb-upload-wrap {
  margin-top: 4px;
}

.kb-upload :deep(.el-upload),
.kb-upload :deep(.el-upload-dragger) {
  width: 100%;
}

.upload-inner {
  padding: 22px 0;
}

.upload-icon {
  color: var(--text-3);
}

.upload-text {
  margin-top: 10px;
  font-size: 14px;
  color: var(--text-2);
}

.upload-hint {
  margin-top: 6px;
  font-size: 12px;
  color: var(--text-3);
}

.kb-divider {
  margin: 18px 0 4px;
}

/* ---------- 文档列表 ---------- */
.docs-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.docs-head .card-title {
  margin-bottom: 0;
}

.docs-count {
  font-size: 12.5px;
  color: var(--text-3);
  margin-top: 4px;
}

.docs-count .num {
  color: #22d3ee;
  font-weight: 600;
  font-size: 14px;
}

.docs-head-right {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: none;
}

.docs-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 430px;
  overflow-y: auto;
}

.docs-empty {
  padding: 36px 0;
  text-align: center;
  font-size: 13px;
  color: var(--text-3);
  border: 1px dashed var(--border-hairline);
  border-radius: 10px;
}

.doc-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 11px 14px;
  border: 1px solid var(--border-hairline);
  border-radius: 10px;
  background: var(--bg-inset);
}

.doc-icon {
  display: grid;
  place-items: center;
  width: 32px;
  height: 32px;
  border-radius: 8px;
  background: rgba(64, 158, 255, 0.12);
  color: #79bbff;
  flex: none;
}

.doc-info {
  flex: 1;
  min-width: 0;
}

.doc-title {
  font-size: 13.5px;
  font-weight: 500;
  color: var(--text-1);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.doc-meta {
  font-size: 11.5px;
  color: var(--text-3);
  margin-top: 2px;
}

.doc-del {
  flex: none;
}

/* ---------- 检索 ---------- */
.search-bar {
  display: flex;
  gap: 12px;
  margin-bottom: 16px;
}

.search-bar .el-input {
  flex: 1;
}

.search-empty {
  padding: 34px 0;
  text-align: center;
  font-size: 13px;
  color: var(--text-3);
  border: 1px dashed var(--border-hairline);
  border-radius: 10px;
}

.hits {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

@media (max-width: 1000px) {
  .kb-grid {
    grid-template-columns: 1fr;
  }
}
</style>
