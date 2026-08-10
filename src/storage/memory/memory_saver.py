"""
本地会话记忆管理器（独立部署版）

使用 SQLite 文件持久化（默认 data/memory.db，重启不丢），
初始化失败时回退到进程内 MemorySaver。
"""
import logging
import os
from pathlib import Path
from typing import Optional

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver

logger = logging.getLogger(__name__)

# SQLite 记忆库路径，可用 MEMORY_DB_PATH 环境变量覆盖
MEMORY_DB_PATH = os.getenv("MEMORY_DB_PATH", "data/memory.db")

# 进程级单例
_async_saver: Optional[BaseCheckpointSaver] = None


async def init_memory_saver(persist: bool = True) -> BaseCheckpointSaver:
    """
    异步初始化本地记忆 checkpointer（单例）

    优先 AsyncSqliteSaver（文件持久化），失败回退 MemorySaver。
    必须在异步环境中调用（服务启动/Agent 构建时）。
    """
    global _async_saver
    if _async_saver is not None:
        return _async_saver

    if not persist:
        # CLI 一次性执行：使用进程内记忆，避免 aiosqlite 线程导致进程无法退出
        _async_saver = MemorySaver()
        return _async_saver

    try:
        import aiosqlite
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        # 兼容补丁：langgraph-checkpoint-sqlite 3.0.1 会调用 conn.is_alive()，
        # 而 aiosqlite 的 Connection 未提供该方法。连接由本模块持有，
        # 存活检查直接返回 True 即可，异常由调用方处理。
        if not hasattr(aiosqlite.Connection, "is_alive"):
            aiosqlite.Connection.is_alive = lambda self: True  # type: ignore

        db_path = Path(MEMORY_DB_PATH)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = await aiosqlite.connect(str(db_path))
        saver = AsyncSqliteSaver(conn)
        await saver.setup()
        _async_saver = saver
        logger.info(f"SQLite 记忆库已就绪: {db_path}")
    except Exception as e:
        logger.warning(f"SQLite 记忆库初始化失败，将回退 MemorySaver: {e}")
        _async_saver = MemorySaver()

    return _async_saver


async def close_memory_saver() -> None:
    """关闭本地记忆库连接（CLI 模式退出前调用，避免进程挂起）"""
    global _async_saver
    if _async_saver is not None:
        try:
            close = getattr(_async_saver, "close", None)
            if close:
                await close()
        except Exception as e:
            logger.warning(f"关闭记忆库失败: {e}")
        _async_saver = None
