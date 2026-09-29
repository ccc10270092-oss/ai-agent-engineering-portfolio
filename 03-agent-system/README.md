# 智能 AI Agent 售前服务系统

一款企业级售前客服 AI Agent 系统，打通「数据脱敏管道 → 混合检索 → 售前咨询 Agent → 内容生成 Agent → 可视化前端」的完整链路。

> 对应设计文档《智能AI-Agent售前服务系统-设计文档》，实现 PRD 的全部功能需求（FR-01 ~ FR-07）与目标（G-1 ~ G-6）。

## 特性

- **LangGraph 编排**：两个 Agent 均以 `LangGraph StateGraph` 实现（售前 ReAct 决策循环 / 内容生成多阶段工作流），工具以 LangChain `Tool` 封装，满足技术栈锁定（LangChain 1.x + LangGraph）。
- **无需 API Key 亦可跑通**：LLM 无 Key 时走离线 Mock、向量后端 chromadb 未装时自动回退内置 `simple`（特征哈希），端到端演示与跑测试不受影响。
- **本地持久化知识库**：文档登记 + FTS5 全文 + 向量三路同步落盘（`data/docs.db` / `data/fts.db` / `data/chroma/`），重启不丢；支持文件上传入库（txt / md / csv / pdf / docx）、单篇删除与一键清空；默认启用本地 embedding 模型（fastembed + bge-small-zh-v1.5，512 维，语义检索"多少钱"能召回"价格"），未装 fastembed 自动回退特征哈希，系统始终可用。
- **持久化商品目录 + 自动登记**：商品目录 SQLite 落盘（`data/products.db`），内置 P001~P003 种子；产品文档（标题/内容命中启发式）入库时自动登记商品，内容生成页立即可选；前端提供增删改查管理弹窗，手动编辑过的商品不再被文档覆盖。
- **三模块共享知识库**：知识入库 → 智能问答（检索工具）→ 内容生成（RAG 接地）全链路打通；生成时自动注入商品参数与知识库检索片段，文案 grounded 在真实数据上，前端「参考来源」面板展示引用文档。
- **六模块分层**：`app-core` 框架 / `data-pipeline` 数据管道 / `retrieval` 混合检索 / 售前咨询 Agent（ReAct）/ 内容生成 Agent（SubGraph）/ Vue 3 前端（FastAPI 网关）。
- **可靠性内置**：统一 `safe_call` 重试/退避/降级，整体故障率为 0（G-5）；`max_steps` 兜底防死循环；Checkpointer 支持断点恢复。
- **PII 脱敏 100%**（G-3）、**会话隔离 100%**（G-4）、**混合检索 FTS5 + 向量融合**（G-2，命中率 ≥85%，见 `docs/检索评测报告.md`）。

## 快速开始

```bash
cd agent-system

# 0) 安装依赖（LangGraph / LangChain 1.x 为必装）
pip install -r requirements.txt

# 1) 端到端演示（无需 API Key；首次运行自动下载本地 embedding 模型约 100MB 到 data/models/，
#    国内网络可先设镜像：export HF_ENDPOINT=https://hf-mirror.com HF_HUB_DISABLE_XET=1）
python demo.py

# 2) 运行全部单元测试（含 G-2 检索评测、G-4 会话隔离）
python run_tests.py
```

启动 Web 前端（Vue 3 + FastAPI，总览 / 智能问答 / 知识入库 / 内容生成 / 数据管道五个页面）：

```bash
pip install -r requirements.txt          # fastapi/uvicorn 等
# 双击 启动前端.bat（自动构建 frontend/dist 并启动）,或手动:
python -m uvicorn api.main:app --host 127.0.0.1 --port 8000
# 浏览器访问 http://127.0.0.1:8000

# 前端开发模式(热更新,需另一个终端):
cd frontend && npm install && npm run dev   # http://localhost:5173,/api 自动代理到 8000
```

接入真实大模型：复制 `.env.example` 为 `.env`，填入 `LLM_MODEL` / `LLM_API_KEY` / `LLM_BASE_URL`（兼容 OpenAI 接口）。
向量 embedding 默认本地模型（`EMBEDDING_BACKEND=local`，config.yaml 已配置），也可切换 API 模式或离线哈希，详见 `.env.example`。

## 目录结构

```
agent-system/
├── app_core/            # 模块 A：配置/日志/异常/模型/safe_call/LLM 客户端
├── data_pipeline/       # 模块 B：清洗/去重/会话切分/PII 脱敏
├── retrieval/           # 模块 C：FTS5 全文 + 向量 + 混合融合
├── agents/
│   ├── pre_sale/        # 模块 D：售前咨询 Agent（ReAct）
│   └── content/         # 模块 E：内容生成 Agent（SubGraph + Checkpointer）
├── frontend/            # 模块 F：Vue 3 前端（Vite + Element Plus + ECharts）
├── api/                 # 模块 F：FastAPI 网关（REST API + 托管前端静态资源）
├── tests/               # 单元测试（unittest,含 API 测试）
├── docs/                # 测试报告 / 检索评测报告 / 验收清单（G-6）
├── data/                # 运行期数据 + eval_qa.json 评测集
├── service.py           # 系统门面：统一装配各模块
├── demo.py              # 端到端演示脚本
├── run_tests.py         # 测试入口
├── config.yaml          # 非敏感配置
├── .env.example         # 敏感配置模板
└── requirements.txt     # 依赖（版本锁定）
```

## 核心设计

### 售前咨询 Agent（ReAct 状态机）

```
idle → thinking → acting → observing → responding → done
        失败 → retry(≤2) → 降级回答 → done
        超 max_steps=10 → 终止 → done
```

`ToolRouter` 按关键词路由到 `search_knowledge` / `get_product_info` / `get_stock`，调用统一走 `safe_call`。

### 内容生成 Agent（SubGraph 工作流）

```
idle → topic_generation → copy_generation → script_generation → done
        任一阶段失败 → retry(≤3) → skip_node → partial_done
        Checkpointer 记录状态，支持 resume 断点恢复
```

### 混合检索

```
query → FTS5 全文检索(归一化) ─┐
      → 向量检索(归一化)       ─┴→ final = fts_weight·f + vector_weight·v → top_k
```

### 知识库（持久化 + 三种 embedding + 文件入库）

- **持久化三件套**：`data/docs.db`（文档登记，SQLite）+ `data/fts.db`（FTS5 全文索引，SQLite）+ `data/chroma/`（向量库）同步落盘，服务重启后文档列表与检索结果不丢；同一文档重复入库自动覆盖（doc_id = 标题+内容的确定性 md5）。
- **三种 embedding 后端**（`EMBEDDING_BACKEND`）：
  - `local`（默认）：fastembed 本地 ONNX 模型 `BAAI/bge-small-zh-v1.5`（512 维），首次运行自动下载约 100MB 到 `data/models/`，之后离线可用；加载失败自动降级特征哈希并在 `/api/health` 标记 `fallback`；
  - `api`：OpenAI 兼容 `/embeddings` 接口（填 `EMBEDDING_MODEL` 等）；
  - `hash`：内置 256 维特征哈希词袋，零依赖兜底。
  - ⚠️ **切换 embedding 模型后向量维度变化会自动重置向量库**（启动日志有告警），需重新入库文档。
- **文件入库**：前端知识库页支持拖拽上传 `.txt / .md / .csv / .pdf / .docx`（上限 10MB）；CSV 问答表（表头含 问题/回答、question/answer、q/a）自动按「问：…答：…」格式化。
- **文档管理**：单篇删除（登记 + 全文 + 向量同步清理）、一键清空、幂等重复入库；单测覆盖 `tests/test_fts.py` / `test_docstore.py` / `test_file_loader.py` / `test_vector.py` / `test_local_embedding.py` / `test_kb.py`。

## 验收标准映射

| 目标 | 指标 | 对应实现/测试 |
| --- | --- | --- |
| G-1 | 三大核心模块组装可运行 | `demo.py` 端到端全链路 |
| G-2 | 混合检索准确率 ≥85% | `retrieval/eval.py`，`data/eval_qa.json`，`tests/test_retrieval_quality.py` |
| G-3 | PII 脱敏准确率 100% | `data_pipeline/masker.py`，`tests/test_masker.py` |
| G-4 | 会话隔离率 100% | `app_core/session.py`，`service.py`，`tests/test_session.py` |
| G-5 | 工具调用故障率 0 | `app_core/safe_call.py`，`tests/test_agent.py`，`tests/test_safe_call.py` |

## 关于 LangChain/LangGraph

本项目的两个 Agent **均以官方 `LangGraph StateGraph` 编排**：

- `agents/pre_sale/graph.py`：售前咨询 ReAct 状态机（`think → act → observe → respond/degrade`）。
- `agents/content/graph.py`：内容生成多阶段工作流（`topic → copy → script`），编译时挂载 `InMemorySaver`（LangGraph Checkpointer）。

工具以 `langchain_core.tools.Tool` 封装（见 `agents/pre_sale/tools.py:build_langchain_tools`）。LLM 调用仍走 `app_core.llm` 的 OpenAI 兼容封装（标准库 urllib，无额外依赖）。

> 说明：LangGraph 的持久化 Checkpointer（SQLite 后端）需额外安装 `langgraph-checkpoint-sqlite`，故内容生成任务的跨进程断点恢复复用 `agents/content/persist.py` 的 JSON Checkpointer。