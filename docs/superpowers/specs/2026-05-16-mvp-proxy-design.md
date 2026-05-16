# MVP 转发网关设计

**日期**：2026-05-16
**状态**：已批准，待实现
**关联设计**：[2026-04-12-ai-gateway-design.md](./2026-04-12-ai-gateway-design.md)（完整版设计，本 MVP 为其第一步切片）

## 目标

最短代码量验证「OpenAI 兼容请求 → 按 model 路由 → 调用 OpenAI 或 Claude 后端 → 返回响应」的可行性。Claude 路径**复用现有 Claude Pro/Max 订阅额度**（通过 Claude Agent SDK），不消耗 Anthropic API 按 token 计费的额度。本 spec 范围之外的功能（鉴权、计费、流式、用户/Token 管理、Web 后台、支付）一律不实现。

## 非目标（本 MVP 不做）

- 鉴权 / API Token
- 计费 / 余额 / 用量记录
- 流式（SSE）转发
- 数据库 / Redis
- 出海 HTTP 代理
- `GET /v1/models` 等辅助端点
- Web 管理后台
- 多轮对话状态保留（每次请求都无状态调用 SDK）

## 关键风险（实施前需知晓）

1. **合规**：用个人/团队订阅账户对外提供 API 服务可能违反 Anthropic 服务条款。本 MVP 仅用于自用/内部测试，不对外开放。
2. **SDK 可用性**：Agent SDK 的实际 API（参数名、返回结构）在实现时会以官方文档/SDK 源码为准；如有出入需调整代码。
3. **订阅速率限制**：Claude Pro/Max 订阅的速率/并发上限可能比 Anthropic API 严，并发高时会撞限制。撞限制时 SDK 会抛异常，gateway 透传为 429。
4. **依赖宿主登录态**：Claude Code 升级、OAuth 凭据过期、订阅状态变更都会让 Claude 路径失效。

## 架构

单 Python 进程，FastAPI + uvicorn。两条上游路径并存：

```
client ─── POST /v1/chat/completions (OpenAI 兼容)
            │
            ▼
       FastAPI handler
            │
   ┌────────┴────────┐
   │                 │
 OpenAI path     Claude path
 (httpx HTTP)    (claude-agent-sdk)
   │                 │
   ▼                 ▼
 api.openai.com   宿主机 Claude Code OAuth
                  → Anthropic 后端
                  (吃订阅额度)
```

## 目录结构

```
aigateway/
├── main.py              # FastAPI app + 路由 + handler
├── openai_client.py     # OpenAI 上游调用（httpx 透传）
├── claude_client.py     # Claude Agent SDK 封装
├── converters.py        # OpenAI ↔ Claude 消息/响应格式转换
├── errors.py            # 统一错误响应构造
├── tests/
│   ├── __init__.py
│   └── test_converters.py
├── requirements.txt
├── README.md
└── .gitignore           # 已存在，需补 Python 忽略项
```

## 依赖

| 包 | 用途 |
|---|---|
| `fastapi` | HTTP 框架 |
| `uvicorn[standard]` | ASGI 服务器 |
| `claude-agent-sdk` | Anthropic 官方 Python SDK，用于 Claude 路径 |
| `httpx` | OpenAI 路径的 HTTP 客户端 |
| `pytest` | 测试 |
| `pytest-asyncio` | 异步测试支持 |

Python 版本：`>=3.11`

## 部署前置条件

Claude 路径依赖宿主机以下状态：

1. 安装 Node.js（Claude Code CLI 是 Node 包）
2. 全局安装 `@anthropic-ai/claude-code`：`npm install -g @anthropic-ai/claude-code`
3. 一次性 OAuth 登录：在宿主机执行 `claude` 命令完成登录流程，绑定持有订阅的账号
4. Agent SDK 会自动复用该 OAuth 凭据，**无需 Anthropic API key**

OpenAI 路径只需环境变量 `OPENAI_API_KEY`。

## 配置

环境变量：

| 变量 | 必需 | 默认值 | 说明 |
|---|---|---|---|
| `OPENAI_API_KEY` | 否¹ | 无 | OpenAI 路径所需 |
| `PORT` | 否 | `8080` | 监听端口 |
| `CLAUDE_DEFAULT_MAX_TOKENS` | 否 | `4096` | Claude SDK 调用的 max_tokens 默认值 |

¹ 启动时不强制要求；请求路由到未配置 key 的 OpenAI 时返回 503。Claude 路径无需 API key 配置，但需要宿主机 Claude Code 已登录（启动时不检测，运行时调用失败抛错）。

## 端点

### `POST /v1/chat/completions`

请求体：OpenAI Chat Completions 标准 JSON。

关键字段：

- `model` —— 必需，决定路由
- `stream` —— 若为 `true`，立即返回 400 `streaming not supported in MVP`
- `messages` —— 必需，非空数组

### 路由规则（硬编码前缀匹配）

| `model` 前缀 | 后端 |
|---|---|
| `gpt-`, `o1-`, `o3-`, `o4-` | OpenAI（httpx） |
| `claude-` | Claude（Agent SDK） |
| 其他 | 400 `unsupported model: <name>` |

## 数据流

### OpenAI 路径（透传）

```
client → FastAPI handler
  → 验证 stream != true
  → 整 body 直接 POST 到 https://api.openai.com/v1/chat/completions
     Headers:
       Authorization: Bearer $OPENAI_API_KEY
       Content-Type: application/json
  → response body + status code 原样返回 client
```

### Claude 路径（Agent SDK）

```
client → FastAPI handler
  → 验证 stream != true
  → converters.openai_to_claude_sdk_args(body):
      - 抽取 role=system 消息（多条用 \n\n 拼接）→ system_prompt
      - 把剩余 user/assistant messages 序列化为单条 prompt 文本：
          每条以 "User: " 或 "Assistant: " 前缀，换行分隔
          最后一条必须是 user，否则 400 "last message must be user"
      - 收集 model, max_tokens, temperature → SDK 参数
  → 调用 claude_client.query(...) 异步:
      ClaudeAgentOptions(
          model=<claude-xxx>,
          system_prompt=<拼接好的>,
          max_tokens=<请求里给的 或 CLAUDE_DEFAULT_MAX_TOKENS>,
          temperature=<请求里给的，无则不传>,
          allowed_tools=[],          # 强制禁用工具
          permission_mode="default",
      )
      消费 query() 异步迭代器，累积所有 AssistantMessage 的 text block
  → converters.claude_sdk_result_to_openai(text, usage, model):
      返回 OpenAI ChatCompletion 形状 JSON
  → 200 + JSON
```

### 格式转换映射

**OpenAI 请求 → Agent SDK 调用参数**

| OpenAI | Agent SDK | 处理 |
|---|---|---|
| `messages[role=system]` | `system_prompt` | 多条用 `\n\n` 拼接 |
| `messages[role∈{user,assistant}]` | `prompt`（拼接文本） | 见上文格式 |
| `model` | `model` | 直接传 |
| `max_tokens` | `max_tokens` | 缺省时 `CLAUDE_DEFAULT_MAX_TOKENS` |
| `temperature` | `temperature` | 有则传 |
| `top_p`、`stop` 等 | — | MVP 不映射，忽略 |

**Agent SDK 响应 → OpenAI 响应**

```python
{
    "id": "chatcmpl-<uuid4>",
    "object": "chat.completion",
    "created": <unix_now>,
    "model": <请求里的 model>,
    "choices": [{
        "index": 0,
        "message": {"role": "assistant", "content": <累积的 text>},
        "finish_reason": "stop"
    }],
    "usage": {
        "prompt_tokens": <SDK 提供的 input_tokens，无则 0>,
        "completion_tokens": <SDK 提供的 output_tokens，无则 0>,
        "total_tokens": <两者之和>
    }
}
```

`finish_reason` MVP 阶段一律返回 `"stop"`，不映射 SDK 的具体停止原因。

## 错误处理

| 情景 | 状态码 | 响应体 |
|---|---|---|
| 请求体非合法 JSON | 400 | `{"error":{"message":"invalid request body","type":"invalid_request_error"}}` |
| `stream=true` | 400 | `{"error":{"message":"streaming not supported in MVP","type":"invalid_request_error"}}` |
| `messages` 为空 / 缺失 / 末条非 user | 400 | `{"error":{"message":"<具体原因>","type":"invalid_request_error"}}` |
| 不支持的 model | 400 | `{"error":{"message":"unsupported model: <name>","type":"invalid_request_error"}}` |
| OpenAI 路径未配置 `OPENAI_API_KEY` | 503 | `{"error":{"message":"provider not configured: openai","type":"server_error"}}` |
| OpenAI 上游 4xx/5xx | 透传上游 status | 透传上游 body |
| OpenAI 网络错误 / 60s 超时 | 502 | `{"error":{"message":"upstream error: <detail>","type":"upstream_error"}}` |
| Claude SDK 抛异常（OAuth 失效、订阅限速、Claude Code 未装等） | 502（429 仅当 SDK 报速率） | `{"error":{"message":"claude sdk error: <detail>","type":"upstream_error"}}` |

错误响应形状统一遵循 OpenAI error envelope：`{"error": {"message": str, "type": str}}`。

## HTTP 客户端

OpenAI 路径：模块级单例 `httpx.AsyncClient(timeout=60.0)`，FastAPI lifespan 钩子里创建/关闭。

## 并发模型

FastAPI 异步 handler。OpenAI 路径用 `httpx.AsyncClient`。Claude 路径的 SDK 调用用 `await`（SDK Python 包默认异步）。MVP 不做并发限制；订阅速率超限时由 SDK 自身抛错。

## 测试

**单元测试** (`tests/test_converters.py`)：

- `test_openai_to_claude_sdk_args_basic` —— 单 system + 多轮对话
- `test_openai_to_claude_sdk_args_no_system` —— 无 system 消息
- `test_openai_to_claude_sdk_args_multiple_system` —— 多条 system 用 `\n\n` 拼接
- `test_openai_to_claude_sdk_args_default_max_tokens` —— 缺省 max_tokens 填默认值
- `test_openai_to_claude_sdk_args_last_message_not_user_raises` —— 末条非 user 抛错
- `test_claude_sdk_result_to_openai_basic` —— 基础响应转换、usage 字段
- `test_claude_sdk_result_to_openai_missing_usage` —— usage 缺失时填 0

**手动联通测试**（README 给出命令）：

```bash
# 启动
uvicorn main:app --port 8080

# OpenAI 路径
curl -s http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-4o-mini","messages":[{"role":"user","content":"say hi"}]}'

# Claude 路径（需宿主机 Claude Code 已登录）
curl -s http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"claude-haiku-4-5-20251001","messages":[{"role":"user","content":"say hi"}]}'
```

## 成功标准

1. `pip install -r requirements.txt` 成功
2. `pytest` 全部通过
3. 设置 `OPENAI_API_KEY` 后，OpenAI curl 返回 200 + 合理回答
4. 宿主机 `claude` 已登录后，Claude curl 返回 200 + 合理回答，且响应体是 OpenAI ChatCompletion 形状
5. `stream=true` / 不支持的 model / 未配置 OpenAI key / 末条非 user 各类错误响应符合上表
6. Python 业务代码总量 ≤ 500 行（不含测试）

## 后续演进路径

本 MVP 完成后，下一阶段按完整设计文档添加：

1. 鉴权中间件（Bearer Token）
2. 用量记录（usage_logs 表）
3. 流式（SSE）转发 —— SDK 的流式响应分块转发为 OpenAI SSE 格式
4. 多轮会话状态保留（SDK session）
5. 计费 / 余额 / 支付
6. PostgreSQL + Redis 接入
7. Web 后台
8. 切换或增加按 API key 计费的 Anthropic 后端（合规商用路径）

每一阶段都不动 MVP 的转发核心逻辑，只在外围叠加层。
