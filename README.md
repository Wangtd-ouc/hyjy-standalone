# 会议纪要助手（独立部署版）

专业处理会议记录，输出严谨、完善、可直接流转的中文会议纪要。本版本已**脱离豆包大模型与 Coze 平台**，模型使用 DeepSeek，联网搜索使用 Tavily，会话记忆使用本地 SQLite，全部能力可独立部署。

## 能力

- **会议纪要生成**：按系统提示词输出「会议背景/客户背景、会议内容、竞品与风险分析、下一步计划」四个章节，自动标注待确认项
- **联网搜索**：Tavily 搜索，支持通用搜索与指定网站搜索（如 `sites=wangsu.com` 核对网宿官网产品信息），返回 AI 摘要
- **会话记忆**：SQLite 本地持久化（默认 `data/memory.db`），同一会话可追问、多轮修正，重启不丢
- **HTTP 服务**：OpenAI 兼容接口（`/v1/chat/completions`），支持流式与工具调用，可接入任意 OpenAI 兼容客户端
- **内置 Web 界面**：无需额外前端，浏览器打开即用
- **文件解析工具**：内置 PDF / Word / Excel / PPT 文本提取模块（供后续扩展附件处理）

## 与原豆包/Coze 版的差异

| 能力 | 原版 | 本版 |
|---|---|---|
| 大模型 | 豆包 doubao-seed-2-0-lite（Coze 网关） | DeepSeek `deepseek-v4-flash`（OpenAI 兼容接口直连） |
| 联网搜索 | Coze `SearchClient` | Tavily API（`include_domains` 实现站点限定） |
| 会话记忆 | PostgreSQL（Coze 提供） | 本地 SQLite 文件 |
| 密钥/环境 | Coze Workload Identity | 本地 `.env` |
| 遥测 | cozeloop → Coze Loop | 移除（标准日志） |
| 文件存储 | Coze 代理 S3 | 移除（本地化） |
| 部署平台 | Coze Coding 沙箱 | 任意 Python 3.12+ 环境 |

系统提示词（`config/agent_llm_config.json`）与业务逻辑保持原样。

> 想深入了解内部架构、运行逻辑与设计特点，见 [ARCHITECTURE.md](./ARCHITECTURE.md)（架构详解）。

## 快速开始

### 1. 安装依赖

```bash
bash scripts/setup.sh
```

（优先使用 `uv`，未安装时回退 `pip`。）

### 2. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env`，填入：

- `LLM_API_KEY`：DeepSeek API Key（[platform.deepseek.com](https://platform.deepseek.com)）
- `TAVILY_API_KEY`：Tavily API Key（[tavily.com](https://tavily.com)）

其余参数有默认值，可按需调整。

### 3. 启动服务

```bash
bash scripts/http_run.sh
```

启动后打开 **http://localhost:5010** 即可使用内置 Web 界面。

> 注意：macOS 上 5000 端口会被系统服务（ControlCenter）占用，因此本项目默认端口为 5010。如需改端口：`PORT=8000 bash scripts/http_run.sh`。

## 使用方式

独立部署后没有 Coze 的输入输出界面，有以下几种用法：

### 方式一：内置 Web 界面（推荐，零配置）

浏览器打开 `http://localhost:5010`：

1. 左侧粘贴会议记录原文
2. 点击「生成会议纪要」（或 `Cmd/Ctrl + Enter`）
3. 右侧实时输出 Markdown 渲染的纪要，可「复制结果」
4. 会话 ID 自动生成并保存在浏览器本地，可「新会话」开启新上下文

### 方式二：任意 OpenAI 兼容客户端

服务提供标准的 `/v1/chat/completions` 接口，Cherry Studio、Chatbox、NextChat、LobeChat、Open WebUI 等均支持自定义服务地址：

- API 地址（Base URL）：`http://你的服务器:5010/v1`
- API Key：留空，或填写 `AUTH_API_KEY`（若设置了鉴权）
- 模型名：`deepseek-v4-flash`

### 方式三：命令行

```bash
# 直接输入会议记录文本
bash scripts/local_run.sh -i "会议主题：... 会议内容：..."

# 或传入 JSON
bash scripts/local_run.sh -i '{"text": "会议记录原文"}'
```

### 方式四：HTTP API

```bash
curl http://localhost:5010/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "meeting-001",
    "messages": [{"role": "user", "content": "会议记录原文"}]
  }'
```

Python：

```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:5010/v1", api_key="任意值")

resp = client.chat.completions.create(
    model="deepseek-v4-flash",
    messages=[{"role": "user", "content": "会议记录原文"}],
    extra_body={"session_id": "meeting-001"},  # 会话记忆 ID（可选）
    stream=True,
)
for chunk in resp:
    print(chunk.choices[0].delta.content or "", end="")
```

## API 说明

| 接口 | 说明 |
|---|---|
| `GET /` | 内置 Web 界面 |
| `GET /health` | 健康检查 |
| `POST /v1/chat/completions` | OpenAI 兼容，`stream=true` 时 SSE 流式；`session_id`/`user` 字段用作会话记忆 ID |
| `POST /run` | 同步执行，返回 OpenAI chat.completion 格式 JSON |
| `POST /stream_run` | SSE 流式执行（OpenAI chunk 格式） |

设置 `AUTH_API_KEY` 后，业务接口需携带 `Authorization: Bearer <key>`。

## 环境变量

| 变量 | 必填 | 默认值 | 说明 |
|---|---|---|---|
| `LLM_API_KEY` | 是 | - | DeepSeek API Key |
| `TAVILY_API_KEY` | 是 | - | Tavily 搜索 API Key |
| `LLM_MODEL` | 否 | `deepseek-v4-flash` | 模型名（任意 OpenAI 兼容模型） |
| `LLM_BASE_URL` | 否 | `https://api.deepseek.com/v1` | 模型接口地址 |
| `LLM_TEMPERATURE` | 否 | `0.7` | 采样温度 |
| `LLM_TIMEOUT` | 否 | `600` | 单次模型请求超时（秒） |
| `PORT` | 否 | `5000` | HTTP 端口 |
| `AUTH_API_KEY` | 否 | 空 | 设置后接口需 Bearer 鉴权 |
| `AGENT_TIMEOUT_SECONDS` | 否 | `900` | 单次任务整体超时（秒） |
| `MEMORY_DB_PATH` | 否 | `data/memory.db` | 会话记忆 SQLite 文件路径 |

## 部署指南

### 服务器部署

```bash
# 服务器上
git clone <仓库地址> && cd hyjy-standalone
bash scripts/setup.sh
cp .env.example .env   # 填入真实 Key
nohup bash scripts/http_run.sh > server.log 2>&1 &
```

生产环境建议：

- 对外暴露前设置 `AUTH_API_KEY`，或置于反向代理（Nginx/Caddy）后由代理负责鉴权与 HTTPS
- 用 `systemd` / `pm2` / Docker 守护进程，崩溃自动拉起
- 定期备份 `data/memory.db` 即完成会话数据备份

### Docker（示例）

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY . /app
RUN pip install -r requirements.txt  # 或用 uv
EXPOSE 5010
CMD ["python", "src/main.py", "-m", "http", "-p", "5010"]
```

## 目录结构

```text
hyjy-standalone/
├── config/agent_llm_config.json   # 系统提示词与模型默认配置
├── scripts/                       # 安装/启动/命令行脚本
├── src/
│   ├── main.py                    # FastAPI 服务入口（OpenAI 兼容）
│   ├── agents/agent.py            # Agent 构建（LangGraph + DeepSeek）
│   ├── tools/web_search_tool.py   # Tavily 联网搜索工具
│   ├── storage/memory/            # 本地 SQLite 会话记忆
│   └── utils/file/                # 文件下载与文档解析（备用）
├── web/                           # 内置 Web 界面（index.html）
├── data/                          # SQLite 记忆库（运行时生成，不入库）
├── .env / .env.example            # 环境变量
└── pyproject.toml                 # 依赖与项目元数据
```

## 安全提醒

- `.env` 已加入 `.gitignore`，请勿将 API Key 提交到任何代码仓库
- 本仓库依赖 DeepSeek 与 Tavily 两个云服务，调用按 token / 次数计费；`search_depth: advanced` 与 `max_results: 10` 是默认值，可在 `src/tools/web_search_tool.py` 调整
- 若 API Key 曾在聊天或日志中明文出现，建议在对应平台控制台轮换（重新生成）后更新 `.env`
