"""
网页搜索工具（Tavily），用于会议纪要助手的背景信息补充和产品信息核对。
Tavily 支持 include_domains（站点限定）与 AI 摘要（answer）。
"""
import os
from urllib.parse import urlparse

import requests
from langchain.tools import ToolRuntime, tool

TAVILY_API_URL = "https://api.tavily.com/search"
DEFAULT_MAX_RESULTS = 10


def _tavily_search(query: str, include_domains=None, max_results: int = DEFAULT_MAX_RESULTS) -> str:
    """调用 Tavily 搜索 API，返回与原先格式一致的摘要文本"""
    api_key = os.getenv("TAVILY_API_KEY", "")
    if not api_key:
        return "搜索失败: 未配置 TAVILY_API_KEY 环境变量"

    payload = {
        "api_key": api_key,
        "query": query,
        "search_depth": "advanced",
        "max_results": max_results,
        "include_answer": True,  # Tavily 服务端生成的 AI 摘要
        "include_raw_content": False,
    }
    if include_domains:
        payload["include_domains"] = include_domains

    try:
        resp = requests.post(TAVILY_API_URL, json=payload, timeout=60)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        return f"搜索失败: {str(e)}"

    result_parts = []

    # AI 摘要（Tavily answer）
    answer = data.get("answer")
    if answer:
        result_parts.append(f"AI 摘要:\n{answer}\n")

    # 搜索结果列表
    results = data.get("results") or []
    if results:
        prefix = f"指定网站搜索结果 ({len(results)} 条):" if include_domains else f"搜索结果 ({len(results)} 条):"
        result_parts.append(prefix)
        for i, item in enumerate(results, 1):
            title = item.get("title", "")
            url = item.get("url", "")
            site_name = urlparse(url).netloc if url else ""
            snippet = (item.get("content") or "")[:200]
            publish_time = item.get("published_date") or "未知"
            result_parts.append(
                f"{i}. {title}\n"
                f"   来源: {site_name}\n"
                f"   URL: {url}\n"
                f"   摘要: {snippet}...\n"
                f"   发布时间: {publish_time}\n"
            )

    if not result_parts:
        return "未找到相关搜索结果"

    return "\n".join(result_parts)


@tool
def web_search(query: str, runtime: ToolRuntime = None) -> str:
    """
    执行网页搜索，用于补充客户/项目背景、产品信息和竞品分析。

    参数:
        query: 搜索关键词或查询语句

    返回:
        搜索结果的摘要信息，包括 AI 摘要、标题、来源、URL 和关键内容
    """
    return _tavily_search(query=query)


@tool
def web_search_sites(query: str, sites: str, runtime: ToolRuntime = None) -> str:
    """
    在指定网站范围内执行网页搜索，用于精准获取特定来源的信息。

    参数:
        query: 搜索关键词或查询语句
        sites: 指定搜索的网站域名列表，用逗号分隔（如：wangsu.com,baidu.com）

    返回:
        搜索结果的摘要信息
    """
    domains = [s.strip() for s in sites.split(",") if s.strip()]
    if not domains:
        return "搜索失败: sites 参数不能为空"
    return _tavily_search(query=query, include_domains=domains)
