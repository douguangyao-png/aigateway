# AI Gateway 设计文档

## 概述

AI Gateway 是一个 Go 语言构建的 AI API 中转网关。国内用户通过该网关调用 Claude、OpenAI 及其他 AI 模型 API，网关负责鉴权、计费、限流和请求转发。

### 核心功能

- 兼容 OpenAI 和 Claude 两种 API 格式
- 支持流式输出（SSE）
- 用户注册系统 + API Token 管理
- 按量计费 + 余额管理
- 支付宝充值 + 卡密兑换码
- 多 Provider 支持（Claude、OpenAI、国内模型通过配置接入）
- Web 管理后台（React 前端）
- HTTP 代理出海支持

### 技术栈

- **后端**: Go + Gin
- **前端**: React（前后端分离）
- **数据库**: PostgreSQL
- **缓存**: Redis
- **部署**: 海外服务器单机部署

---

## 1. 项目结构

```
aigateway/
├── cmd/
│   └── server/
│       └── main.go
├── internal/
│   ├── config/                  # 配置加载 (YAML)
│   ├── server/                  # HTTP 服务启动、路由注册
│   ├── middleware/              # 鉴权、限流、日志、计费中间件
│   ├── handler/
│   │   ├── openai/              # OpenAI 兼容接口
│   │   ├── claude/              # Claude 兼容接口
│   │   ├── admin/               # 管理后台 API
│   │   └── payment/             # 支付回调
│   ├── provider/
│   │   ├── provider.go          # Provider 接口定义
│   │   ├── registry.go          # Provider 注册表
│   │   ├── claude/              # Claude 实现
│   │   ├── openai/              # OpenAI 实现
│   │   └── compatible/          # OpenAI 兼容模型通用适配器
│   ├── model/                   # 数据模型
│   ├── store/                   # 数据库操作层
│   ├── billing/                 # 计费：余额管理、用量计算、扣费
│   ├── payment/
│   │   ├── alipay/              # 支付宝对接
│   │   └── redemption/          # 卡密/兑换码生成与兑换
│   └── ratelimit/               # 速率限制 (Redis)
├── web/                         # React 前端项目
├── configs/
│   └── config.yaml
├── go.mod
└── go.sum
```

---

## 2. 数据模型

### users - 用户表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | bigint PK | 主键 |
| username | varchar | 用户名 |
| email | varchar | 邮箱 |
| password_hash | varchar | 密码哈希 |
| role | varchar | 角色: admin / user |
| balance | bigint | 余额（分） |
| status | varchar | 状态: active / disabled |
| created_at | timestamp | 创建时间 |
| updated_at | timestamp | 更新时间 |

### api_tokens - API Token 表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | bigint PK | 主键 |
| user_id | bigint FK | 所属用户 |
| token_hash | varchar | Token 哈希 |
| name | varchar | Token 备注名 |
| rate_limit | int | 每分钟请求上限 |
| daily_quota | bigint | 每日额度上限（分） |
| status | varchar | 状态: active / revoked |
| last_used_at | timestamp | 最后使用时间 |
| created_at | timestamp | 创建时间 |

### usage_logs - 用量记录表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | bigint PK | 主键 |
| user_id | bigint FK | 用户 |
| token_id | bigint FK | 使用的 Token |
| provider | varchar | 提供商名称 |
| model | varchar | 模型名称 |
| input_tokens | int | 输入 token 数 |
| output_tokens | int | 输出 token 数 |
| cost | bigint | 扣费金额（分） |
| request_duration | int | 请求耗时（毫秒） |
| status | varchar | 状态: success / error |
| created_at | timestamp | 创建时间 |

### recharge_logs - 充值记录表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | bigint PK | 主键 |
| user_id | bigint FK | 用户 |
| amount | bigint | 充值金额（分） |
| payment_method | varchar | 支付方式: alipay / redemption_code |
| trade_no | varchar | 支付宝交易号或兑换码 |
| status | varchar | 状态: pending / paid / failed |
| created_at | timestamp | 创建时间 |

### redemption_codes - 兑换码表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | bigint PK | 主键 |
| code | varchar | 兑换码 |
| amount | bigint | 面值（分） |
| status | varchar | 状态: unused / used / disabled |
| used_by | bigint FK | 使用者 user_id |
| used_at | timestamp | 使用时间 |
| created_at | timestamp | 创建时间 |

### provider_configs - Provider 配置表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | bigint PK | 主键 |
| name | varchar | 提供商名称 |
| type | varchar | 类型: claude / openai / openai_compatible |
| base_url | varchar | API 地址 |
| api_key | varchar | API 密钥（加密存储） |
| models | jsonb | 支持的模型列表 |
| status | varchar | 状态: active / disabled |
| created_at | timestamp | 创建时间 |
| updated_at | timestamp | 更新时间 |

### model_prices - 模型价格表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | bigint PK | 主键 |
| provider_id | bigint FK | 关联 Provider |
| model_name | varchar | 模型名称 |
| input_price | bigint | 每 1K input token 价格（分） |
| output_price | bigint | 每 1K output token 价格（分） |
| created_at | timestamp | 创建时间 |
| updated_at | timestamp | 更新时间 |

---

## 3. API 接口设计

### 3.1 代理接口（面向用户）

鉴权方式：`Authorization: Bearer <api_token>`

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /v1/chat/completions | OpenAI 兼容对话（流式/非流式） |
| GET | /v1/models | 可用模型列表 |
| POST | /v1/messages | Claude 兼容对话（流式/非流式） |

### 3.2 用户接口

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /api/auth/register | 注册 |
| POST | /api/auth/login | 登录（返回 JWT） |
| GET | /api/user/profile | 个人信息 |
| PUT | /api/user/password | 修改密码 |
| GET | /api/user/tokens | API Token 列表 |
| POST | /api/user/tokens | 创建 API Token |
| DELETE | /api/user/tokens/:id | 删除 Token |
| GET | /api/user/balance | 余额查询 |
| GET | /api/user/usage | 用量记录（分页） |
| POST | /api/user/redeem | 兑换码充值 |
| POST | /api/user/recharge/alipay | 支付宝充值（返回支付链接） |

### 3.3 管理接口（需 admin 角色）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/admin/users | 用户列表 |
| PUT | /api/admin/users/:id/balance | 手动调整余额 |
| PUT | /api/admin/users/:id/status | 启用/禁用用户 |
| GET | /api/admin/providers | Provider 列表 |
| POST | /api/admin/providers | 添加 Provider |
| PUT | /api/admin/providers/:id | 修改 Provider |
| DELETE | /api/admin/providers/:id | 删除 Provider |
| GET | /api/admin/models/prices | 模型价格列表 |
| PUT | /api/admin/models/prices/:id | 修改价格 |
| POST | /api/admin/redemption-codes | 批量生成兑换码 |
| GET | /api/admin/redemption-codes | 兑换码列表 |
| GET | /api/admin/stats | 总览统计 |
| GET | /api/admin/usage | 全局用量记录 |

### 3.4 支付回调

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /api/callback/alipay | 支付宝异步通知 |

---

## 4. 核心流程

### 4.1 请求转发流程

```
用户请求 → Gin Router
  → 鉴权中间件（校验 API Token）
  → 余额检查中间件（余额 > 0？）
  → 限流中间件（Redis 检查速率）
  → Handler（识别请求格式 OpenAI/Claude）
  → Provider 适配层
      → 根据请求的 model 查找对应 Provider
      → 转换请求格式（如需要）
      → 转发到上游 API
  → 响应返回
      → 流式：逐块转发 SSE，最终统计 token
      → 非流式：直接返回，统计 token
  → 计费中间件（异步扣费 + 记录用量）
```

### 4.2 流式转发

```go
func handleStream(c *gin.Context, upstreamResp *http.Response) {
    c.Header("Content-Type", "text/event-stream")
    reader := bufio.NewReader(upstreamResp.Body)

    for {
        line, err := reader.ReadBytes('\n')
        if err == io.EOF { break }

        // 逐行转发 SSE 数据
        c.Writer.Write(line)
        c.Writer.Flush()

        // 累计 token 计数
        accumulateTokens(line)
    }

    // 请求结束后异步扣费
    go billing.Charge(userId, inputTokens, outputTokens, model)
}
```

### 4.3 Provider 接口

```go
type Provider interface {
    // 模型列表
    Models() []string

    // 非流式请求
    ChatCompletion(ctx context.Context, req *ChatRequest) (*ChatResponse, error)

    // 流式请求
    ChatCompletionStream(ctx context.Context, req *ChatRequest) (<-chan *ChatChunk, error)
}

type ChatRequest struct {
    Model    string
    Messages []Message
    Stream   bool
    // MaxTokens, Temperature 等通用参数
}
```

### 4.4 计费逻辑

1. **请求前**: 检查余额 > 0
2. **请求完成**: 统计 input_tokens + output_tokens
3. **查价格表**: `cost = input_tokens/1000 * input_price + output_tokens/1000 * output_price`
4. **扣余额**: `UPDATE users SET balance = balance - cost WHERE id = ? AND balance >= cost`
5. **写用量记录**: 插入 usage_logs
6. **余额不足**: 扣费失败，记录异常

---

## 5. 配置文件

```yaml
server:
  port: 8080
  mode: release

database:
  host: localhost
  port: 5432
  user: aigateway
  password: ""
  dbname: aigateway

redis:
  addr: localhost:6379
  password: ""

jwt:
  secret: "your-jwt-secret"
  expire: 72h

proxy:
  enabled: false
  url: "http://127.0.0.1:7890"

alipay:
  app_id: ""
  private_key: ""
  public_key: ""
  notify_url: "https://your-domain.com/api/callback/alipay"
  return_url: "https://your-domain.com/recharge/result"
  sandbox: false

log:
  level: info
  output: stdout
  file: ./logs/gateway.log

providers:
  - name: claude
    type: claude
    api_key: "sk-ant-xxx"
    base_url: "https://api.anthropic.com"
    models:
      - claude-sonnet-4-20250514
      - claude-haiku-4-5-20251001

  - name: openai
    type: openai
    api_key: "sk-xxx"
    base_url: "https://api.openai.com"
    models:
      - gpt-4o
      - gpt-4o-mini

  - name: deepseek
    type: openai_compatible
    api_key: "sk-xxx"
    base_url: "https://api.deepseek.com"
    models:
      - deepseek-chat
```

---

## 6. 部署

### 编译与运行

```bash
# 编译
go build -o aigateway ./cmd/server

# 运行
./aigateway -config ./configs/config.yaml
```

### 依赖服务

- PostgreSQL 15+
- Redis 7+

### Go 主要依赖

| 包 | 用途 |
|---|------|
| github.com/gin-gonic/gin | Web 框架 |
| github.com/go-redis/redis/v9 | Redis |
| gorm.io/gorm | ORM |
| gorm.io/driver/postgres | PostgreSQL 驱动 |
| github.com/golang-jwt/jwt/v5 | JWT |
| github.com/smartwalle/alipay/v3 | 支付宝 SDK |
| gopkg.in/yaml.v3 | 配置解析 |

---

## 7. 设计决策总结

| 决策 | 选择 | 理由 |
|------|------|------|
| 语言 | Go | 高性能，适合网关，单二进制部署 |
| 架构 | 单体 | 需求明确，避免过度设计 |
| API 格式 | OpenAI + Claude 兼容 | 最大化客户端兼容性 |
| 多 Provider | 接口抽象 + 配置驱动 | 用户可通过配置接入国内模型 |
| 计费 | 按 token 用量 | 与上游计费方式一致 |
| 支付 | 支付宝 + 卡密兑换码 | 覆盖主流场景，微信后续扩展 |
| 前端 | React 前后端分离 | 功能灵活，独立开发部署 |
| 存储 | PostgreSQL + Redis | 生产级可靠性 |
| 网络 | HTTP 代理出海 / 海外直连 | 通过配置切换 |
| 对话存储 | 客户端 cookie/localStorage | 先客户端存储，后续加数据库 |
