# Providers — 详细规范 / Detailed Spec

## 1. 抽象层契约 / Abstraction contract

### 1.1 统一调用形态 / Unified call shape

所有 provider 在 OpsPilot 内被调用时，必须能映射到统一的"chat completion"形态：

```
ProviderCall {
  provider_id      : 注册表中的 id
  model            : 模型名（不含版本，版本走 model_version）
  model_version    : 锁定版本（不允许 latest）
  messages         : [{role, content, ...}]
  tools            : 可选；统一格式（见 §4）
  params           : {temperature, top_p, max_tokens, seed, stop, ...}
  timeouts         : {connect_ms, read_ms, total_ms}
  budget_usd       : 单次预算上限
  capabilities_req : 此次调用所需能力（用于 routing 校验）
}
```

返回形态：

```
ProviderResponse {
  provider_id      : 实际命中的 provider（routing 后）
  model_ref        : "<provider_id>/<model>@<model_version>"
  finish_reason    : stop | length | tool_call | content_filter | error
  content          : 文本或工具调用列表
  usage            : {input_tokens, output_tokens, cached_tokens?, cost_usd}
  latency_ms       : {ttfb, total}
  raw              : 厂商原始 payload（可选，artifact 引用）
}
```

### 1.2 Model ref 格式 / Model ref format

**强约束**：`<provider_id>/<model_name>@<model_version>`，例：

```
ollama/qwen2.5:14b@2024-09
openrouter/anthropic/claude-sonnet-4-6@2026-04
openai/gpt-4o@2024-11-20
anthropic/claude-sonnet-4-6@2026-04
gemini/gemini-2.5-pro@2025-03
grok/grok-3@2025-02
```

- `provider_id` 必须出现在 `provider-registry.template.yaml`
- `model_name` 与该 provider 的 catalog 一致
- `model_version`：禁用 `latest`、`auto`、`stable`；必须是厂商显式版本字符串或日期字符串
- 通过 OpenRouter 等聚合网关时，仍需写出**真实底层 model**（审计）：`openrouter/<vendor>/<model>@<ver>`

## 2. Provider 配置必填字段 / Required config fields

权威定义见 `schemas/provider-config.schema.json`。核心字段：

| 字段 | 必填 | 说明 |
|---|---|---|
| `id` | ✓ | provider 实例 id（同一厂商可注册多实例，例如 `ollama-gpu1` / `ollama-cpu`） |
| `kind` | ✓ | enum：`ollama` / `openrouter` / `openai` / `anthropic` / `gemini` / `grok` / `openai_compatible` |
| `display_name` | ✓ | 人类可读名 |
| `base_url` | ✓ | 完整 URL（可被 routing 强制覆盖） |
| `auth` | ✓ | 见 §3 |
| `default_headers` | ✗ | 厂商必需 header（如 `anthropic-version`） |
| `capabilities` | ✓ | 见 §4 |
| `limits` | ✓ | rate limit、context window、max_output |
| `cost` | ✓ | 计费模型 + 月度预算 |
| `retry` | ✓ | 重试策略 |
| `compliance` | ✗ | 数据驻留、telemetry、训练用途 opt-out |
| `enabled` | ✓ | bool；下线时设 false 而非删除 |

## 3. 鉴权 / Authentication

允许的鉴权类型：

```yaml
auth:
  type: "api_key_header"          # 见下表
  env: "OPENAI_API_KEY"           # 实际值从环境变量读，不入库
  header: "Authorization"
  prefix: "Bearer "
```

支持的 `auth.type`：

| type | 适配厂商 | 注入方式 |
|---|---|---|
| `none` | Ollama（默认） | 不发送鉴权头 |
| `api_key_header` | OpenAI / OpenRouter / Grok / Ollama-served | `Authorization: Bearer <key>` |
| `api_key_custom_header` | Anthropic | `x-api-key: <key>` + `anthropic-version: <ver>` |
| `api_key_query` | Gemini（API key 模式） | URL `?key=<key>` |
| `oauth2_service_account` | Vertex AI（Gemini 企业模式） | 短期 token 自动刷新 |

**强约束**：
- API key 一律 `env:` 占位；不允许 `value:` 直接内联
- `oauth2_service_account` 必须配 `key_file_env` 指向凭证 JSON 路径
- Provider 不得读取 `~/.aws`、`~/.kube`、`~/.ssh` 等"非本 provider"的凭证目录

## 4. 能力声明 / Capabilities

`capabilities` 是一组 bool 标志 + 数值上限。playbook 声明 `capabilities_req` 时与之比对。

```yaml
capabilities:
  streaming: true
  tools: true                       # function calling / tool use
  vision: true
  audio_in: false
  audio_out: false
  json_mode: true                   # 结构化输出
  prompt_caching: false             # Anthropic 与部分模型支持
  long_context_tokens: 200000
  max_output_tokens: 8192
  reasoning_mode: false             # OpenAI o1/o3 / Gemini thinking 等
  computer_use: false               # 仅部分 Anthropic 模型
  embeddings: false                 # 该 provider 是否同时提供 embedding
```

声明原则：
- **保守**：能力字段填**当前 catalog 中实际可用**的，不是"理论支持"
- **可降级**：`tools=false` 的 provider 不应被路由到声明 `tools_req=true` 的 playbook
- **不交叉申报**：一个 provider 配置实例只代表一类访问形态（不要既本地又云）

## 5. 速率与上下文上限 / Limits

```yaml
limits:
  context_window_tokens: 200000
  max_output_tokens: 8192
  rpm: 60                            # requests per minute
  tpm: 200000                        # tokens per minute
  concurrent: 8                      # 并发请求上限（client side throttle）
```

OpsPilot 在客户端侧做令牌桶；厂商真实限速以厂商为准（429 时按 `retry` 策略处理）。

## 6. 成本与预算 / Cost & budget

```yaml
cost:
  pricing:
    input_per_1k_usd: 0.0           # 信息日期 + 来源必须在 catalogs.md 记录
    output_per_1k_usd: 0.0
    cached_input_per_1k_usd: null    # 可选；prompt cache 折扣价
    pricing_as_of: "2026-05-01"
  monthly_budget_usd: 50             # 月度硬预算
  per_call_budget_usd: 0.5           # 单次调用上限（超出阻断）
  on_budget_exceeded: "block"        # block | warn | downgrade
  downgrade_to: null                 # provider_id；on_budget_exceeded=downgrade 时使用
```

## 7. 重试与超时 / Retry & timeouts

```yaml
retry:
  max_attempts: 3
  initial_backoff_ms: 500
  max_backoff_ms: 8000
  jitter: "full"                     # full | none
  retry_on:
    - "http_429"
    - "http_500"
    - "http_502"
    - "http_503"
    - "http_504"
    - "timeout_read"
  give_up_on:
    - "http_400"
    - "http_401"
    - "http_403"
    - "http_404"
    - "http_413"                     # 上下文超限不重试
timeouts:
  connect_ms: 5000
  read_ms: 60000
  total_ms: 90000
```

**幂等性提醒**：tool_call 与 sandbox 执行分离 —— provider 重试只重试模型生成，不重试 sandbox 动作。

## 8. 合规与隐私 / Compliance

```yaml
compliance:
  data_residency: "unspecified"      # us | eu | apac | unspecified
  telemetry_optout: true             # 是否要求关闭厂商训练用途/日志保留
  zero_data_retention: false         # 厂商是否承诺零数据保留（按合同）
  pii_allowed: false                 # 该 provider 是否允许处理 PII（governance 决定）
  red_lines:
    - "不发送未脱敏 PII"
    - "不发送内部代号"
```

`pii_allowed=false` 的 provider 在 routing 时不允许接收含有 redaction 警告的 Session（防泄漏）。

## 9. Provider Registry 语义 / Registry semantics

`provider-registry.template.yaml` 是顶层入口：
- `providers[]`：注册的 provider 实例
- `default_provider`：未声明 routing 时使用
- `routing`：策略与规则集
- `aliases`：模型简称 → `model_ref`（让 playbook 引用 `@chat-strong` 而非具体模型）

策略优先级（高 → 低）：
```
session.model_override
  > playbook.preferred_provider
    > registry.routing rule
      > registry.default_provider
```

## 10. 与 Session / Harness 的字段映射 / Field mapping

| Session（meta.yaml） | Providers |
|---|---|
| `model.vendor` | provider_id 的 kind |
| `model.name` | model_name |
| `model.version` | model_version |
| `extensions.provider_config_hash` | 实际命中的 provider config 的 sha256（审计用） |

| Harness（eval-config） | Providers |
|---|---|
| `models[]` | 一律 `<provider_id>/<model>@<version>` |
| 评估器 `judge.llm.judge_model` | 同上；judge provider 建议与被测 provider 不同 |

## 11. 强约束 / Hard requirements

- 任何 provider 实例必须能通过"健康检查 + 一次最小 prompt 调用"才算 enabled
- API key 一律环境变量；提交带 key 的配置文件视为安全事件
- `model_version` 不允许 `latest`/`auto`/`stable`
- pricing/limits/capabilities 任一项与 `catalogs.md` 不一致时，以 catalog 为权威，并在 audit 中标记 drift
- 自托管（Ollama / vLLM）部署的 base_url 不允许指向公网域名（避免误用）

## 12. 扩展点 / Extensions

- `extensions.<vendor>` —— 厂商特性（如 Anthropic 的 `cache_control`、Gemini 的 `safety_settings`）
- 新增 provider 类型：通过 `kind: "openai_compatible"` 接入兼容层（vLLM、TGI、LiteLLM proxy、本地 OpenRouter）
