# 向量模型与维度迁移

项目中的文本向量统一通过 `src.llm_models.embedding.embed_text` 生成。调用结果同时包含向量和
embedding profile；profile 签名由模型标识、provider、client 类型、API endpoint、模型额外参数以及
实际向量维度共同计算。持久化索引不能只记录维度，因为两个模型即使输出维度相同，也不一定处于同一个
向量空间。

## 配置约束

- `model_config.toml` 的 embedding 任务如果配置多个模型，向量调用固定使用列表中的第一个模型。
  同一索引不能通过随机或负载均衡混入不同模型生成的向量。
- `bot_config.toml` 中的 `memory.embedding_dimension` 必须与该模型实际返回的维度一致。返回维度不一致时，
  新向量写入和迁移会失败，不会把错误维度的向量写入当前索引。
- 修改模型、provider、endpoint、相关额外参数或维度后，需要按正常配置流程重启进程。启动时会重新计算
  profile 并检查现有索引。

## Qdrant 自动重建

`memory_atoms` 和 `graph_entries` 使用稳定 alias 指向版本化的物理 collection。检测到 profile 或维度变化时：

1. 保留 alias 当前指向的旧 collection，并创建符合新维度的目标 collection。
2. 暂停该索引的向量查询；记忆检索会回退到关键词路径，避免跨向量空间比较。
3. 后台任务按批次从 SQLite 源数据重新生成向量，迁移游标和错误状态保存在
   `vector_index_state` SQLite 表中，进程重启后可继续。
4. 迁移期间，新写入进入目标 collection；删除和非内容 payload 更新同时覆盖旧索引与目标索引。
5. 目标 collection 通过业务 ID、profile 签名、维度及来源文本哈希校验后，使用一个 Qdrant alias 更新请求
   原子切换到新 collection。
6. 旧 collection 默认保留，便于故障排查和人工回退；系统不会自动删除它。

Qdrant 官方说明 collection alias 的变更会原子应用，适合后台构建新 collection 后无缝切换：
https://qdrant.tech/documentation/concepts/collections/#collection-aliases

## JSON 向量缓存

表达选择、表情情感和表情使用场景的 JSON 索引会保存 profile 签名与向量维度。查询发现缓存签名或维度与
当前结果不一致时，会按各索引原有的并发和数量限制懒刷新，不需要手动删除缓存文件。

## 运维说明

- 迁移失败时旧 collection 不会被覆盖或删除，但对应向量查询保持停用，后台任务会继续重试。
- 日志事件 `memory.qdrant.migration_required`、`memory.vector_migration.*` 和
  `memory.qdrant.migration_activated` 可用于观察准备、批次、失败和切换过程。
- `GraphStore` 的实时增删目前仍以 SQLite 为准；图向量迁移会从 SQLite 完整重建，但实时图向量写入链路是
  独立的后续接入项。
