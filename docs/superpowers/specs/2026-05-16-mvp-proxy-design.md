# MVP 转发网关设计

**日期**：2026-05-16
**状态**：已批准，待实现
**关联设计**：[2026-04-12-ai-gateway-design.md](./2026-04-12-ai-gateway-design.md)（完整版设计，本 MVP 为其第一步切片）

## 目标

最短代码量验证「OpenAI 兼容请求 → 按 model 路由到 OpenAI 或 Claude 上游 → 返回响应」的可行性。本 spec 范围之外的功能（鉴权、计费、流式、用户/Token 管理、Web 后台、支付）一律不实现。

## 非目标（本 MVP 不做）

- 鉴权 / API Token
- 计费 / 余额 / 用量记录
- 流式（SSE）转发
- 数据库 / Redis
- 出海 HTTP 代理
- `GET /v1/models` 等辅助端点
- Web 管理后台

## 架构

单 Go 二进制，单进程，无外部依赖（无 DB、无 Redis）。

```
aigateway/
├── main.go            # 启动 + 路由 + handler
├── openai.go          # OpenAI 上游调用（请求/响应透传）
├── claude.go          # Claude 上游调用 + OpenAI↔Claude 格式转换
├── claude_test.go     # 格式转换单元测试
├── go.mod
└── go.sum
```

依赖：

- `github.com/gin-gonic/gin` —— HTTP 路由
- 标准库 `net/http`、`encoding/json`、`os`、`time`

## 配置

环境变量：

| 变量 | 必需 | 默认值 | 说明 |
|---|---|---|---|
| `OPENAI_API_KEY` | 否¹ | 无 | 调 OpenAI 上游所需 |
| `CLAUDE_API_KEY` | 否¹ | 无 | 调 Claude 上游所需 |
| `PORT` | 否 | `8080` | 监听端口 |

¹ 启动时至少需要其中一个。两个都缺则启动失败并打印 `at least one of OPENAI_API_KEY / CLAUDE_API_KEY must be set`。请求路由到未配置 key 的上游时返回 503。

## 端点

### `POST /v1/chat/completions`

请求体：OpenAI Chat Completions 标准 JSON（不做严格校验，原样转发或转换后转发）。

关键字段：

- `model` —— 必需，决定路由
- `stream` —— 若为 `true`，立即返回 400 `streaming not supported in MVP`
- `messages` —— 必需

### 路由规则（硬编码前缀匹配）

| `model` 前缀 | 上游 |
|---|---|
| `gpt-`, `o1-`, `o3-`, `o4-` | OpenAI |
| `claude-` | Claude |
| 其他 | 400 `unsupported model: <name>` |

## 数据流

### OpenAI 路径（透传）

```
client → handler
  → 验证 stream != true
  → 整 body 直接 POST 到 https://api.openai.com/v1/chat/completions
     Headers:
       Authorization: Bearer $OPENAI_API_KEY
       Content-Type: application/json
  → 整 response body + status code 原样返回 client
```

### Claude 路径（格式转换）

```
client → handler
  → 验证 stream != true
  → 解析 body 为 OpenAI 请求结构
  → 转换为 Claude /v1/messages 请求结构：
      - role="system" 的消息抽取拼成顶层 system 字段
      - 其余 messages 保留（role 必须为 user/assistant）
      - max_tokens 缺省时填 4096（Claude 必需字段）
  → POST 到 https://api.anthropic.com/v1/messages
     Headers:
       x-api-key: $CLAUDE_API_KEY
       anthropic-version: 2023-06-01
       Content-Type: application/json
  → 解析 Claude 响应：
      content[0].text  → choices[0].message.content
      usage.input_tokens  → usage.prompt_tokens
      usage.output_tokens → usage.completion_tokens
      stop_reason 映射 → finish_reason ("end_turn"→"stop", "max_tokens"→"length", 其他→"stop")
  → 返回 200 + OpenAI 形状 JSON
```

### 格式转换映射

**OpenAI 请求 → Claude 请求**

| OpenAI | Claude | 处理 |
|---|---|---|
| `model` | `model` | 直接拷贝 |
| `messages[role=system]` | 顶层 `system` 字段 | 多条 system 消息用 `\n\n` 拼接 |
| `messages[role∈{user,assistant}]` | `messages` | 保留顺序 |
| `max_tokens` | `max_tokens` | 缺省时填 `4096` |
| `temperature` | `temperature` | 透传 |
| `top_p` | `top_p` | 透传 |
| `stop` | `stop_sequences` | 透传（如有） |

**Claude 响应 → OpenAI 响应**

```json
// Claude 实际响应
{
  "id": "msg_xxx",
  "type": "message",
  "role": "assistant",
  "content": [{"type": "text", "text": "Hello!"}],
  "model": "claude-sonnet-4-20250514",
  "stop_reason": "end_turn",
  "usage": {"input_tokens": 10, "output_tokens": 5}
}

// 转换为 OpenAI 形状
{
  "id": "msg_xxx",
  "object": "chat.completion",
  "created": <unix_now>,
  "model": "claude-sonnet-4-20250514",
  "choices": [{
    "index": 0,
    "message": {"role": "assistant", "content": "Hello!"},
    "finish_reason": "stop"
  }],
  "usage": {
    "prompt_tokens": 10,
    "completion_tokens": 5,
    "total_tokens": 15
  }
}
```

## 错误处理

| 情景 | 状态码 | 响应体 |
|---|---|---|
| 请求体非合法 JSON | 400 | `{"error":{"message":"invalid request body","type":"invalid_request_error"}}` |
| `stream=true` | 400 | `{"error":{"message":"streaming not supported in MVP","type":"invalid_request_error"}}` |
| 不支持的 model | 400 | `{"error":{"message":"unsupported model: <name>","type":"invalid_request_error"}}` |
| 未配置对应 API key | 503 | `{"error":{"message":"provider not configured: <openai\|claude>","type":"server_error"}}` |
| 上游返回 4xx/5xx | 透传上游 status | OpenAI 路径：透传 body。Claude 路径：包成 OpenAI error 形状 `{"error":{"message":..., "type":"upstream_error"}}` |
| 上游网络错误 / 60s 超时 | 502 | `{"error":{"message":"upstream error: <detail>","type":"upstream_error"}}` |

## HTTP 客户端

- `http.Client{Timeout: 60 * time.Second}` 作为全局变量
- 不重用上游连接池配置，使用 net/http 默认
- 不重试，错误直接返回

## 测试

**单元测试** (`claude_test.go`)：

- `TestOpenAIToClaudeRequest_BasicConversion` —— 单 system + 多轮对话
- `TestOpenAIToClaudeRequest_NoSystem` —— 无 system 消息
- `TestOpenAIToClaudeRequest_MultipleSystem` —— 多条 system 用 `\n\n` 拼接
- `TestOpenAIToClaudeRequest_DefaultMaxTokens` —— 缺省 max_tokens 填 4096
- `TestClaudeToOpenAIResponse_BasicConversion` —— 基础响应转换
- `TestClaudeToOpenAIResponse_StopReasonMapping` —— end_turn / max_tokens / 其他 → 对应 finish_reason

**手动联通测试**（README 给出命令）：

```bash
# OpenAI 路径
curl -s http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-4o-mini","messages":[{"role":"user","content":"say hi"}]}'

# Claude 路径
curl -s http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"claude-haiku-4-5-20251001","messages":[{"role":"user","content":"say hi"}]}'
```

## 成功标准

1. `go build ./...` 成功
2. `go test ./...` 全部通过
3. 设置真实 API key 后，两条 curl 命令各自返回 200 + 合理回答
4. `stream=true` / 不支持的 model / 未配置 key 三类错误返回符合上表的状态码和错误形状
5. 代码总量 ≤ 600 行 Go（不含测试 fixture）

## 后续演进路径

本 MVP 完成后，下一阶段按完整设计文档添加：

1. YAML 配置文件取代环境变量
2. `internal/provider` 包结构 + `Provider` interface 抽象（把当前 openai.go / claude.go 重构进去）
3. 中间件：鉴权、限流、计费、日志
4. PostgreSQL + Redis 接入
5. 流式（SSE）转发
6. Web 后台

每一阶段都不动 MVP 的转发核心逻辑，只在外围叠加层。
