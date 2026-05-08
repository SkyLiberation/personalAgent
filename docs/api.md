# 后端接口

主要接口定义位于 [api.py](../src/personal_agent/api.py)。

## `GET /api/health`

返回服务状态与图谱配置状态。

示例响应：

```json
{
  "status": "ok",
  "graphiti": {
    "enabled": true,
    "configured": true,
    "base_url": "https://api.deepseek.com",
    "model": "deepseek-v4-flash",
    "embedding_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "embedding_model": "text-embedding-v4"
  }
}
```

## `POST /api/capture`

请求体：

```json
{
  "text": "Bob 在搜索系统升级项目里决定先上 BM25 + 向量召回",
  "source_type": "note",
  "user_id": "default"
}
```

## `POST /api/capture/upload`

使用 `multipart/form-data` 上传文件。

表单字段：

- `file`
- `user_id`

说明：

- 上传接口会先返回本地 capture 结果
- 如果 Graphiti 已配置，图谱同步会在后台继续执行
- 返回的 `note.graph_sync_status` 初始通常为 `pending`
- 后续可通过 `GET /api/notes` 观察是否变为 `synced` 或 `failed`

## `POST /api/notes/{note_id}/graph-sync`

手动重试某条笔记的图谱同步。

行为：

- 先把笔记状态置为 `pending`
- 然后在后台执行图谱同步

示例响应：

```json
{
  "note": {
    "id": "76ac8451-3c16-4259-80d8-256a072e0304",
    "graph_sync_status": "pending"
  },
  "queued": true
}
```

## `POST /api/ask`

请求体：

```json
{
  "question": "搜索系统升级项目里，Bob 先决定采用什么方案？",
  "user_id": "default"
}
```

说明：

- 普通问答完成后会自动写入服务端 `ask history`
- 如果已配置 `Postgres`，历史会持久化保存

## `GET /api/ask/stream`

基于 `SSE` 返回实时问答结果。

查询参数：

- `question`
- `user_id`

事件类型：

- `status`
- `metadata`
- `answer_delta`
- `done`

## `GET /api/ask-history`

返回指定用户最近的问答历史。

查询参数：

- `user_id`
- `limit`

示例响应：

```json
{
  "items": [
    {
      "id": "0f0b8fe7-3e4d-4b95-8bb5-2ab4e6f0c99a",
      "user_id": "default",
      "question": "支付系统重构项目第一阶段方案包括什么？",
      "answer": "图谱里最相关的实体：支付系统重构项目、第一阶段方案...",
      "citations": [],
      "graph_enabled": true,
      "created_at": "2026-05-08T15:10:00.000000Z"
    }
  ]
}
```

## `GET /api/digest`

返回最近笔记与到期复习任务。

## `GET /api/notes`

返回当前用户的全部本地笔记。
