"""
会议纪要助手 Agent（独立部署版）
专业处理会议记录，输出严谨、完善、可直接流转的中文会议纪要。
模型：DeepSeek（OpenAI 兼容接口）；搜索：Tavily。
"""
import json
import os
from typing import Annotated, Optional

from langchain.agents import create_agent
from langchain_core.messages import AnyMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import MessagesState
from langgraph.graph.message import add_messages

from tools.web_search_tool import web_search, web_search_sites

# 配置文件相对项目根目录（运行时从项目根启动）
LLM_CONFIG = os.getenv("AGENT_LLM_CONFIG", "config/agent_llm_config.json")

# 默认保留最近 20 轮对话 (40 条消息)
MAX_MESSAGES = 40


def _windowed_messages(old, new):
    """滑动窗口: 只保留最近 MAX_MESSAGES 条消息"""
    return add_messages(old, new)[-MAX_MESSAGES:]  # type: ignore


class AgentState(MessagesState):
    messages: Annotated[list[AnyMessage], _windowed_messages]


def build_agent(ctx: Optional[object] = None, checkpointer: Optional[object] = None):
    """
    构建会议纪要助手 Agent（独立部署版）

    模型配置优先级：环境变量 > config/agent_llm_config.json
    - LLM_MODEL / LLM_API_KEY / LLM_BASE_URL / LLM_TEMPERATURE / LLM_TIMEOUT

    Returns:
        构建好的 Agent 实例
    """
    # 读取系统提示词等配置
    with open(LLM_CONFIG, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    # 环境变量优先，配置文件兜底
    model = os.getenv("LLM_MODEL") or cfg["config"].get("model", "deepseek-v4-flash")
    api_key = os.getenv("LLM_API_KEY") or ""
    base_url = os.getenv("LLM_BASE_URL", "https://api.deepseek.com/v1")
    temperature = float(os.getenv("LLM_TEMPERATURE", str(cfg["config"].get("temperature", 0.7))))
    timeout = int(os.getenv("LLM_TIMEOUT", str(cfg["config"].get("timeout", 600))))

    if not api_key:
        raise ValueError("未配置 LLM_API_KEY，请在 .env 中设置 DeepSeek API Key")

    # 初始化 LLM（OpenAI 兼容协议）
    llm = ChatOpenAI(
        model=model,
        api_key=api_key,
        base_url=base_url,
        temperature=temperature,
        streaming=True,
        timeout=timeout,
    )

    # 构建工具列表（Tavily 联网搜索）
    tools = [web_search, web_search_sites]

    # 会话记忆 checkpointer：由服务入口传入（SQLite 本地持久化），未传则用内存兜底
    if checkpointer is None:
        from langgraph.checkpoint.memory import MemorySaver

        checkpointer = MemorySaver()

    # 创建并返回 Agent（带本地 SQLite 会话记忆，未传入时内存兜底）
    return create_agent(
        model=llm,
        system_prompt=cfg.get("sp"),
        tools=tools,
        checkpointer=checkpointer,
        state_schema=AgentState,
    )
