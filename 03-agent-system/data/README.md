# data 目录说明

本目录用于存放运行期数据，均在程序启动或演示时自动生成，无需手工创建：

- `fts.db` — FTS5 全文索引（SQLite，切片级倒排与原文，含锁与落盘提交）；
- `docs.db` — 知识文档登记表（SQLite，doc_id / 标题 / 来源 / 切片数 / 入库时间）；
- `products.db` — 商品目录（SQLite，product_id / 名称 / 规格 / 分类 / 价格 / 库存 / 来源 origin）；首次启动写入内置种子 P001~P003，之后产品文档入库自动登记（origin=doc）或管理界面增改（origin=manual）。**删除知识文档不会删除已登记商品**；
- `chroma/` — ChromaDB 向量持久化目录（配置 `vector_backend=chroma` 时自动创建）；
- `models/` — 本地 embedding 模型缓存（`EMBEDDING_BACKEND=local` 时 fastembed 自动下载，约 100MB，下载一次后离线可用）；
- `checkpoints/` — 内容生成 Agent 的 Checkpointer 状态文件（自动创建）。

知识库三件套（`fts.db` + `docs.db` + `chroma/`）共同构成持久化知识库：服务重启后文档列表与检索结果不丢。删除单个文档时会同步清理三处；**切换 embedding 模型后维度变化会自动重置向量库（其余不动），需重新入库文档**。

演示用的样例数据由 `demo.py:sample_records()` / `sample_knowledge()` 内联生成，
可通过前端的「数据管道」页上传自定义 CSV/JSON 进行测试。
