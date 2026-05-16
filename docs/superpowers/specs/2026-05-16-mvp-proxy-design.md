# MVP 转发网关设计

**日期**：2026-05-16
**状态**：已批准，待实现
**关联设计**：[2026-04-12-ai-gateway-design.md](./2026-04-12-ai-gateway-design.md)（完整版设计，本 MVP 为其第一步切片）

## 目标

最短代码量验证「请求 → 调用 Claude 后端 → 返回响应」的可行性，并提供一个简单的网页用于人工试用。Claude 后端**复用现有 Claude Pro/Max 订阅额度**（通过 Claude Agent SDK），不消耗 Anthropic API 按 token 计费的额度。本 spec 范围之外的功能一律不实现。

提供两个面向：

1. **机器面**：`POST /v1/chat/completions`，OpenAI 兼容请求/响应形状，给 SDK/curl 用。
2. **人面**：`GET /`，一个单页 HTML 试用页面，浏览器里能选模型、输入问题、看回复和 token 用量。

## 非目标（本 MVP 不做）

- **OpenAI 后端**（留给第二阶段）
- 鉴权 / API Token / 用户系统 / 登录
- 计费 / 余额 / 用量记录
- 流式（SSE）转发
- 多轮对话历史保存
- 数据库 / Redis
- 出海 HTTP 代理
- `GET /v1/models` 等辅助端点
- Web 管理后台
- 前端框架 / 打包工具（试用页用单文件 HTML + 原生 JS）

## 关键风险（实施前需知晓）

1. **合规**：用个人/团队订阅账户对外提供 API 服务可能违反 Anthropic 服务条款。本 MVP 仅用于自用/内部测试，不对外开放。
2. **订阅速率限制**：Claude Pro/Max 订阅的速率/并发上限可能比 Anthropic API 严，并发高时会撞限制。撞限制时 SDK 会抛异常，gateway 透传为 429。
3. **依赖宿主登录态**：Claude Code 升级、OAuth 凭据过期、订阅状态变更都会让服务失效。

## SDK 实测发现（已通过 smoke test 验证）

实际安装 `claude-agent-sdk==0.2.82` 并跑了端到端验证，发现：

1. **SDK 用的是 agent 框架，不是裸 Claude API**。`ClaudeAgentOptions` **没有 `max_tokens` 和 `temperature` 字段**——这两个客户端请求里的字段需要被忽略。
2. **每次请求约 25k token 的 agent 系统上下文 prefill**（即使 `allowed_tools=[]`），首次创建 cache，后续命中。这是固有开销，无法消除。
3. **首次响应延迟约 13 秒**（含 agent 启动 + prefill），后续同会话能命中缓存会更快。
4. **没传 `model` 默认 Opus**。handler 必须把请求里的 model 显式传给 SDK。
5. **usage 字段格式确认**：SDK 的 `ResultMessage.usage` 是 dict，含 `input_tokens` / `output_tokens` / `cache_creation_input_tokens` / `cache_read_input_tokens`。

## 架构

单 Python 进程，FastAPI + uvicorn。两个端点：

```
                    ┌─ GET /                       → 返回 static/index.html（试用页）
client ────────────►│
                    └─ POST /v1/chat/completions   → 调 Claude Agent SDK
                                                     │
                                                     ▼
                                          宿主机 Claude Code OAuth
                                          → Anthropic 后端 (吃订阅额度)
```

## 目录结构

```
aigateway/
├── main.py              # FastAPI app + 路由 + handler
├── claude_client.py     # Claude Agent SDK 封装
├── converters.py        # OpenAI ↔ Claude SDK 消息/响应格式转换
├── errors.py            # 统一错误响应构造
├── static/
│   └── index.html       # 单页试用 UI（HTML + 原生 JS + CSS 全在一个文件）
├── tests/
│   ├── __init__.py
│   └── test_converters.py
├── requirements.txt
├── README.md
└── .gitignore           # 已存在
```

## 依赖

| 包 | 用途 |
|---|---|
| `fastapi` | HTTP 框架 |
| `uvicorn[standard]` | ASGI 服务器 |
| `claude-agent-sdk` | Anthropic 官方 Python SDK（已实测） |
| `anyio` | SDK 自带异步运行时（passthrough） |
| `pytest` | 测试 |
| `pytest-asyncio` | 异步测试支持 |

Python 版本：`>=3.11`（实测在 3.11 venv 中工作正常）。

## 部署前置条件

1. 安装 Node.js（Claude Code CLI 是 Node 包）
2. 全局安装 `@anthropic-ai/claude-code`：`npm install -g @anthropic-ai/claude-code`
3. 一次性 OAuth 登录：宿主机执行 `claude` 命令完成登录流程，绑定持有订阅的账号
4. 安装本项目依赖：`pip install -r requirements.txt`
5. Agent SDK 会自动复用 OAuth 凭据，**无需 Anthropic API key**

## 配置

环境变量：

| 变量 | 必需 | 默认值 | 说明 |
|---|---|---|---|
| `PORT` | 否 | `8090` | 监听端口 |

启动时不检测 Claude Code 登录状态；运行时调用失败按错误表返回。

## 端点

### `POST /v1/chat/completions`

请求体：OpenAI Chat Completions 标准 JSON。

关键字段：

- `model` —— 必需，必须以 `claude-` 开头
- `stream` —— 若为 `true`，立即返回 400 `streaming not supported in MVP`
- `messages` —— 必需，非空数组，末条必须 role=user
- `max_tokens` / `temperature` / `top_p` / `stop` 等 —— **静默忽略**（SDK 不支持）

路由规则：

| `model` 前缀 | 处理 |
|---|---|
| `claude-` | 调用 Agent SDK |
| 其他 | 400 `unsupported model: <name>` |

### `GET /`

返回 `static/index.html` 静态内容（FastAPI `FileResponse`）。页面内容由前端章节描述。

### `GET /static/*`（可选）

FastAPI `StaticFiles` 挂载 `/static`，方便后续扩展。MVP 阶段 `index.html` 是唯一资源。

## 数据流（API 路径）

```
client → FastAPI handler
  → 验证 stream != true
  → 验证 model 以 claude- 开头，否则 400
  → converters.openai_to_claude_sdk_args(body):
      - 抽取 role=system 消息（多条用 \n\n 拼接）→ system_prompt
      - 把剩余 user/assistant messages 序列化为单条 prompt 文本：
          每条以 "User: " 或 "Assistant: " 前缀，换行分隔
          最后一条必须是 user，否则 400 "last message must be user"
      - 收集 model → SDK 参数
  → 调用 claude_client.query(...) 异步:
      ClaudeAgentOptions(
          model=<claude-xxx>,
          system_prompt=<拼接好的，无 system 则 None>,
          max_turns=1,                  # 单轮，禁止 agent 自主多轮
          allowed_tools=[],             # 禁用所有工具
          permission_mode="default",
          setting_sources=None,         # 不加载用户/项目/本地设置
      )
      消费 query() 异步迭代器：
        - AssistantMessage 累积 TextBlock 文本
        - ResultMessage 抓 usage / is_error / stop_reason
        - 其他类型（ThinkingBlock 等）忽略
  → 如果 is_error=True → 返回 502 + error
  → converters.claude_sdk_result_to_openai(text, usage, model):
      返回 OpenAI ChatCompletion 形状 JSON
  → 200 + JSON
```

### 格式转换映射

**OpenAI 请求 → Agent SDK 调用参数**

| OpenAI | Agent SDK | 处理 |
|---|---|---|
| `messages[role=system]` | `system_prompt` | 多条用 `\n\n` 拼接；无则 None |
| `messages[role∈{user,assistant}]` | `prompt`（拼接文本） | `"User: ..."` / `"Assistant: ..."` 换行分隔 |
| `model` | `model` | 直接传 |

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
        "prompt_tokens": <usage.input_tokens 或 0>,
        "completion_tokens": <usage.output_tokens 或 0>,
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
| 不支持的 model（非 claude- 前缀） | 400 | `{"error":{"message":"unsupported model: <name>","type":"invalid_request_error"}}` |
| SDK 抛 rate limit 异常 | 429 | `{"error":{"message":"rate limit: <detail>","type":"rate_limit_error"}}` |
| SDK ResultMessage.is_error=True | 502 | `{"error":{"message":"claude error: <detail>","type":"upstream_error"}}` |
| SDK 抛其他异常（CLINotFoundError、CLIConnectionError 等） | 502 | `{"error":{"message":"claude sdk error: <detail>","type":"upstream_error"}}` |

错误响应形状统一遵循 OpenAI error envelope：`{"error": {"message": str, "type": str}}`。

## 前端（试用页面）

单文件 `static/index.html`。布局：

```
┌────────────────────────────────────────────────┐
│  AI Gateway 试用                                │
│                                                │
│  模型: [ claude-haiku-4-5-20251001       ▼ ]    │
│                                                │
│  ┌──────────────────────────────────────────┐  │
│  │ (textarea, 多行输入)                      │  │
│  │                                          │  │
│  └──────────────────────────────────────────┘  │
│  [发送]                                         │
│                                                │
│  ── 回复 ──                                     │
│  ┌──────────────────────────────────────────┐  │
│  │ (输出区，pre-wrap)                        │  │
│  └──────────────────────────────────────────┘  │
│                                                │
│  用量: prompt=12  completion=45  total=57       │
│  耗时: 12.3s                                    │
└────────────────────────────────────────────────┘
```

**模型下拉选项**（硬编码）：

- `claude-haiku-4-5-20251001`（默认，最快/最便宜）
- `claude-sonnet-4-6`
- `claude-opus-4-7`

**前端行为**：

- 点"发送" → 禁用按钮 + 显示"…" 占位
- `fetch('/v1/chat/completions', { method: 'POST', body: JSON.stringify({model, messages: [{role:'user', content:<textarea>}]}) })`
- 拿到响应：
  - 成功：把 `choices[0].message.content` 显示在输出区；usage 三项 + 客户端计时显示
  - 失败：显示 `error.message`
- 恢复按钮，输入框不清空，方便修改重发

**样式**：极简内联 CSS，无外部依赖，无图标库。深色或浅色一种即可（推荐浅色）。

## 并发模型

FastAPI 异步 handler。SDK 调用用 `await`/`async for`。MVP 不做并发限制；订阅速率超限时由 SDK 抛错。

## 测试

**单元测试** (`tests/test_converters.py`)：

- `test_openai_to_claude_sdk_args_basic` —— 单 system + 多轮对话
- `test_openai_to_claude_sdk_args_no_system` —— 无 system 消息（system_prompt=None）
- `test_openai_to_claude_sdk_args_multiple_system` —— 多条 system 用 `\n\n` 拼接
- `test_openai_to_claude_sdk_args_last_message_not_user_raises` —— 末条非 user 抛错
- `test_openai_to_claude_sdk_args_empty_messages_raises` —— 空 messages 抛错
- `test_claude_sdk_result_to_openai_basic` —— 基础响应转换、usage 字段
- `test_claude_sdk_result_to_openai_missing_usage` —— usage 为 None 时填 0

**手动联通测试**：

```bash
# 启动
uvicorn main:app --port 8090

# API 路径
curl -s http://localhost:8090/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"claude-haiku-4-5-20251001","messages":[{"role":"user","content":"say hi"}]}'

# 浏览器试用页
open http://localhost:8090/
```

## 成功标准

1. `pip install -r requirements.txt` 成功
2. `pytest` 全部通过
3. 宿主机 `claude` 已登录后，API curl 返回 200 + 合理回答，响应体是 OpenAI ChatCompletion 形状，usage 字段有真实值
4. 浏览器访问 `http://localhost:8090/`：能选模型、输入问题、看到回复和 token 用量
5. `stream=true` / 非 claude- model / 末条非 user 各类错误响应符合上表
6. Python 业务代码 ≤ 400 行（不含测试和 HTML）；HTML ≤ 200 行

## 第二阶段及之后

本 MVP 完成后，按完整设计文档加（按优先级）：

1. **OpenAI 后端** —— 加 `openai_client.py`，model 前缀路由扩展到 `gpt-*`、`o1-*`、`o3-*`、`o4-*`
2. 鉴权中间件（Bearer Token）+ 用户系统
3. 用量记录（usage_logs 表）
4. 流式（SSE）转发
5. 多轮会话状态保留（SDK session）
6. 计费 / 余额 / 支付
7. PostgreSQL + Redis 接入
8. Web 后台
9. 切换或增加按 API key 计费的 Anthropic 后端（合规商用路径）

每一阶段都不动 MVP 的转发核心逻辑，只在外围叠加层。
