"""
会议纪要助手 Agent —— 独立部署版 HTTP 服务入口

提供接口：
- POST /v1/chat/completions   OpenAI 兼容接口（支持流式/非流式），通用客户端与内置 Web 界面均走此接口
- POST /run                   同步执行（返回 OpenAI chat.completion 格式 JSON）
- POST /stream_run            SSE 流式执行（OpenAI chunk 格式）
- GET  /health                健康检查
- GET  /                      内置 Web 界面

可选鉴权：设置 AUTH_API_KEY 后，业务接口需携带 Authorization: Bearer <key>
"""
import argparse
import asyncio
import json
import logging
import os
import time
import uuid
from typing import Any, AsyncGenerator, Dict, List

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    AnyMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from agents.agent import build_agent
from storage.memory.memory_saver import init_memory_saver

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("hyjy_agent")

# 全局配置（可在 .env 覆盖）
TIMEOUT_SECONDS = int(os.getenv("AGENT_TIMEOUT_SECONDS", "900"))
AUTH_API_KEY = os.getenv("AUTH_API_KEY", "")
DEFAULT_MODEL = os.getenv("LLM_MODEL", "deepseek-v4-flash")


def _require_auth(request: Request) -> None:
    """可选鉴权：未配置 AUTH_API_KEY 时放行"""
    if not AUTH_API_KEY:
        return
    if request.headers.get("Authorization", "") != f"Bearer {AUTH_API_KEY}":
        raise HTTPException(status_code=401, detail="unauthorized")


def _parse_messages(messages: List[Dict[str, Any]]) -> List[AnyMessage]:
    """OpenAI messages 格式 -> LangChain messages（支持 system/user/assistant/tool）"""
    result: List[AnyMessage] = []
    for m in messages or []:
        role = m.get("role")
        content = m.get("content", "")
        if role == "system":
            result.append(SystemMessage(content=content or ""))
        elif role == "user":
            result.append(HumanMessage(content=content or ""))
        elif role == "assistant":
            tool_calls = m.get("tool_calls")
            if tool_calls:
                result.append(AIMessage(content=content or "", tool_calls=tool_calls))
            else:
                result.append(AIMessage(content=content or ""))
        elif role == "tool":
            result.append(
                ToolMessage(content=content or "", tool_call_id=m.get("tool_call_id", ""))
            )
        else:
            raise ValueError(f"不支持的 message role: {role}")
    if not result:
        raise ValueError("messages 不能为空")
    return result


class GraphService:
    """Agent 单例管理"""

    def __init__(self):
        self._graph = None
        self._lock = asyncio.Lock()

    async def get_graph(self, persist: bool = True):
        if self._graph is not None:
            return self._graph
        async with self._lock:
            if self._graph is not None:
                return self._graph
            try:
                # 初始化本地 SQLite 记忆库（异步），再在线程池构建 Agent
                checkpointer = await init_memory_saver(persist=persist)
                self._graph = await asyncio.to_thread(build_agent, checkpointer=checkpointer)
            except Exception as e:
                logger.exception("Agent 构建失败")
                raise HTTPException(status_code=500, detail=f"Agent 构建失败: {e}")
            return self._graph

    async def stream_agent(self, messages: List[AnyMessage], thread_id: str, persist: bool = True):
        """LangGraph 消息流（stream_mode=messages）"""
        graph = await self.get_graph(persist=persist)
        config = {
            "configurable": {"thread_id": thread_id},
            "recursion_limit": 100,
        }
        return graph.astream(
            {"messages": messages},
            config=config,
            stream_mode="messages",
        )


service = GraphService()
app = FastAPI(title="会议纪要助手", version="1.0.0")


def _chat_meta(payload: Dict[str, Any], request_id: str) -> Dict[str, Any]:
    """生成响应公共字段"""
    return {
        "id": f"chatcmpl-{request_id}",
        "created": int(time.time()),
        "model": payload.get("model") or DEFAULT_MODEL,
    }


async def _handle_chat(payload: Dict[str, Any], persist: bool = True) -> Dict[str, Any]:
    """非流式：聚合完整回答"""
    messages = _parse_messages(payload.get("messages"))
    thread_id = str(payload.get("session_id") or payload.get("user") or "default")
    meta = _chat_meta(payload, uuid.uuid4().hex)

    content_parts: List[str] = []
    async for chunk, _ in await service.stream_agent(messages, thread_id, persist=persist):
        if isinstance(chunk, AIMessageChunk) and chunk.content:
            content_parts.append(chunk.content)

    return {
        **meta,
        "object": "chat.completion",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "".join(content_parts)},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


def _sse(data: Dict[str, Any]) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _stream_chat(payload: Dict[str, Any], persist: bool = True) -> AsyncGenerator[str, None]:
    """流式：OpenAI SSE chunk 格式（含工具调用 delta 透传）"""
    messages = _parse_messages(payload.get("messages"))
    thread_id = str(payload.get("session_id") or payload.get("user") or "default")
    meta = _chat_meta(payload, uuid.uuid4().hex)

    # 角色占位 chunk
    yield _sse(
        {
            **meta,
            "object": "chat.completion.chunk",
            "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}],
        }
    )

    # 累积工具调用参数（OpenAI 按增量片段传输）
    tool_acc: Dict[int, Dict[str, Any]] = {}
    async for chunk, _ in await service.stream_agent(messages, thread_id, persist=persist):
        if not isinstance(chunk, AIMessageChunk):
            continue

        delta: Dict[str, Any] = {}
        if chunk.content:
            delta["content"] = chunk.content

        tool_chunks = chunk.tool_call_chunks or []
        if tool_chunks:
            deltas = []
            for tc in tool_chunks:
                idx = tc["index"]
                acc = tool_acc.setdefault(
                    idx,
                    {
                        "id": "",
                        "type": "function",
                        "function": {"name": "", "arguments": ""},
                    },
                )
                if tc.get("id"):
                    acc["id"] = tc["id"]
                if tc.get("name"):
                    acc["function"]["name"] = tc["name"]
                if tc.get("args"):
                    acc["function"]["arguments"] += tc["args"]
                deltas.append(
                    {
                        "index": idx,
                        "id": acc["id"],
                        "type": "function",
                        "function": {
                            "name": acc["function"]["name"],
                            "arguments": tc.get("args", ""),
                        },
                    }
                )
            delta["tool_calls"] = deltas

        if delta:
            yield _sse(
                {
                    **meta,
                    "object": "chat.completion.chunk",
                    "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
                }
            )

    # 结束 chunk
    yield _sse(
        {
            **meta,
            "object": "chat.completion.chunk",
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        }
    )
    yield "data: [DONE]\n\n"


@app.get("/health")
async def health():
    return {"status": "ok", "message": "会议纪要助手服务运行中"}


@app.post("/v1/chat/completions")
async def openai_chat_completions(request: Request):
    """OpenAI Chat Completions 兼容接口"""
    _require_auth(request)
    payload = await request.json()
    try:
        if payload.get("stream"):
            return StreamingResponse(_stream_chat(payload), media_type="text/event-stream")
        return await _handle_chat(payload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/run")
async def run_endpoint(request: Request):
    """同步执行"""
    _require_auth(request)
    payload = await request.json()
    try:
        return await asyncio.wait_for(_handle_chat(payload), timeout=TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail=f"执行超时（>{TIMEOUT_SECONDS}s）")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/stream_run")
async def stream_run_endpoint(request: Request):
    """SSE 流式执行（OpenAI chunk 格式）"""
    _require_auth(request)
    payload = await request.json()
    if payload.get("stream") is False:
        try:
            return await asyncio.wait_for(_handle_chat(payload), timeout=TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            raise HTTPException(status_code=504, detail=f"执行超时（>{TIMEOUT_SECONDS}s）")
    return StreamingResponse(_stream_chat(payload), media_type="text/event-stream")


# 内置 Web 界面（必须放在 API 路由之后挂载，避免拦截 API 路径）
_web_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "web"))
app.mount("/", StaticFiles(directory=_web_dir, html=True), name="web")


def parse_args():
    parser = argparse.ArgumentParser(description="会议纪要助手独立部署服务")
    parser.add_argument("-m", type=str, default="http", help="运行模式: http / flow / agent")
    parser.add_argument("-i", type=str, default="", help="flow/agent 模式的输入 JSON 或纯文本")
    parser.add_argument("-p", type=int, default=int(os.getenv("PORT", "5000")), help="HTTP 端口")
    return parser.parse_args()


def _run_cli(input_str: str) -> None:
    """命令行模式：直接调用 Agent 并打印结果"""
    if input_str:
        try:
            data = json.loads(input_str)
        except json.JSONDecodeError:
            data = {"text": input_str}
    else:
        data = {"text": "你好"}

    if "messages" not in data and "text" in data:
        data["messages"] = [{"role": "user", "content": data["text"]}]

    async def _run():
        try:
            result = await _handle_chat(data, persist=False)
            print(result["choices"][0]["message"]["content"])
        finally:
            from storage.memory.memory_saver import close_memory_saver

            await close_memory_saver()

    asyncio.run(_run())


def main():
    args = parse_args()
    if args.m in ("flow", "agent"):
        _run_cli(args.i)
    else:
        logger.info(f"启动 HTTP 服务，端口: {args.p}")
        uvicorn.run(app, host="0.0.0.0", port=args.p, workers=1)


if __name__ == "__main__":
    main()
