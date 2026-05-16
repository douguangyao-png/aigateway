# MVP 转发网关设计

**日期**：2026-05-16
**状态**：已批准，待实现
**关联设计**：[2026-04-12-ai-gateway-design.md](./2026-04-12-ai-gateway-design.md)（完整版设计，本 MVP 为其第一步切片）

## 目标

最短代码量验证「OpenAI 兼容请求 → 调用 Claude 后端 → 返回响应」的可行性。Claude 后端**复用现有 Claude Pro/Max 订阅额度**（通过 Claude Agent SDK），不消耗 Anthropic API 按 token 计费的额度。本 spec 范围之外的功能（鉴权、计费、流式、OpenAI 后端、用户/Token 管理、Web 后台、支付）一律不实现。

## 非目标（本 MVP 不做）

- **OpenAI 后端**（留给第二阶段）
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
4. **依赖宿主登录态**：Claude Code 升级、OAuth 凭据过期、订阅状态变更都会让服务失效。

## 架构

单 Python 进程，FastAPI + uvicorn。仅一条上游路径：

```
client ─── POST /v1/chat/completions (OpenAI 兼容请求/响应形状)
            │
            ▼
       FastAPI handler
            │
            ▼
       claude-agent-sdk
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
| `claude-agent-sdk` | Anthropic 官方 Python SDK |
| `pytest` | 测试 |
| `pytest-asyncio` | 异步测试支持 |

Python 版本：`>=3.11`

## 部署前置条件

1. 安装 Node.js（Claude Code CLI 是 Node 包）
2. 全局安装 `@anthropic-ai/claude-code`：`npm install -g @anthropic-ai/claude-code`
3. 一次性 OAuth 登录：在宿主机执行 `claude` 命令完成登录流程，绑定持有订阅的账号
4. Agent SDK 会自动复用该 OAuth 凭据，**无需 Anthropic API key**

## 配置

环境变量：

| 变量 | 必需 | 默认值 | 说明 |
|---|---|---|---|
| `PORT` | 否 | `8080` | 监听端口 |
| `CLAUDE_DEFAULT_MAX_TOKENS` | 否 | `4096` | Claude SDK 调用的 max_tokens 默认值 |

启动时不检测 Claude Code 登录状态；运行时调用失败会抛错并按错误表返回。

## 端点

### `POST /v1/chat/completions`

请求体：OpenAI Chat Completions 标准 JSON。

关键字段：

- `model` —— 必需，必须以 `claude-` 开头
- `stream` —— 若为 `true`，立即返回 400 `streaming not supported in MVP`
- `messages` —— 必需，非空数组，末条必须 role=user

### 路由规则

| `model` 前缀 | 处理 |
|---|---|
| `claude-` | 调用 Agent SDK |
| 其他 | 400 `unsupported model: <name>`（含将来的 `gpt-*` 等，留给第二阶段） |

## 数据流

```
client → FastAPI handler
  → 验证 stream != true
  → 验证 model 以 claude- 开头，否则 400
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
| 不支持的 model（非 claude- 前缀） | 400 | `{"error":{"message":"unsupported model: <name>","type":"invalid_request_error"}}` |
| Claude SDK 抛速率限制异常 | 429 | `{"error":{"message":"rate limit: <detail>","type":"rate_limit_error"}}` |
| Claude SDK 抛其他异常（OAuth 失效、Claude Code 未装等） | 502 | `{"error":{"message":"claude sdk error: <detail>","type":"upstream_error"}}` |

错误响应形状统一遵循 OpenAI error envelope：`{"error": {"message": str, "type": str}}`。

## 并发模型

FastAPI 异步 handler。Claude SDK 调用用 `await`（SDK Python 包默认异步）。MVP 不做并发限制；订阅速率超限时由 SDK 自身抛错。

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

# Claude 路径（需宿主机 Claude Code 已登录）
curl -s http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"claude-haiku-4-5-20251001","messages":[{"role":"user","content":"say hi"}]}'

# 错误情景验证
curl -s http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-4o","messages":[{"role":"user","content":"hi"}]}'
# → 400 unsupported model
```

## 成功标准

1. `pip install -r requirements.txt` 成功
2. `pytest` 全部通过
3. 宿主机 `claude` 已登录后，Claude curl 返回 200 + 合理回答，且响应体是 OpenAI ChatCompletion 形状
4. `stream=true` / 非 claude- model / 末条非 user 各类错误响应符合上表
5. Python 业务代码总量 ≤ 350 行（不含测试）

## 第二阶段及之后

本 MVP 完成后，下一阶段按完整设计文档添加（按优先级）：

1. **OpenAI 后端** —— 加 `openai_client.py`，model 前缀路由扩展到 `gpt-*`、`o1-*`、`o3-*`、`o4-*`
2. 鉴权中间件（Bearer Token）
3. 用量记录（usage_logs 表）
4. 流式（SSE）转发
5. 多轮会话状态保留（SDK session）
6. 计费 / 余额 / 支付
7. PostgreSQL + Redis 接入
8. Web 后台
9. 切换或增加按 API key 计费的 Anthropic 后端（合规商用路径）

每一阶段都不动 MVP 的转发核心逻辑，只在外围叠加层。
