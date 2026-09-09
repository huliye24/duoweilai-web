"""Duoweilai 结构化日志配置。

两种格式：
  - LOG_FORMAT=human  → 终端友好、彩色、可读（开发默认）
  - LOG_FORMAT=json   → 每行 JSON、便于日志聚合（Loki/ELK/Datadog）

环境变量：
  DUOWEILAI_LOG_LEVEL  DEBUG / INFO / WARNING / ERROR（默认 INFO）
  DUOWEILAI_LOG_FORMAT human / json                       （默认 human）

设计原则：
  - 仅依赖 Python 标准库（无 loguru 等重依赖）
  - 不绑定 Flask 框架，但提供便捷 Flask 集成
  - 字段透传：logger.info("msg", extra={...}) → JSON 中作为顶层字段
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import sys
import time
from datetime import datetime, timezone
from typing import Any

# 标准 logging.LogRecord 字段白名单（其他字段视为自定义）
_STANDARD_RECORD_KEYS = frozenset(
    {
        "name",
        "msg",
        "args",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "processName",
        "process",
        "asctime",
        "taskName",
        "message",
    }
)


# ============================================================
# Formatters
# ============================================================
class JsonFormatter(logging.Formatter):
    """JSON 行格式：每条日志 = 一行 JSON。

    示例输出：
      {"ts":"2026-09-10T04:00:00.123+00:00","level":"INFO","logger":"duoweilai",
       "msg":"request completed","request_id":"abc12345","status":200,
       "duration_ms":12.34,"path":"/api/health"}
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }

        # 附加用户字段（通过 extra= 传入）
        for key, value in record.__dict__.items():
            if key not in _STANDARD_RECORD_KEYS and not key.startswith("_"):
                try:
                    json.dumps(value)
                    payload[key] = value
                except (TypeError, ValueError):
                    payload[key] = repr(value)

        # 异常信息
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack"] = self.formatStack(record.stack_info)

        return json.dumps(payload, ensure_ascii=False, default=str)


class HumanFormatter(logging.Formatter):
    """人类可读格式：彩色 + 时间戳 + 字段紧凑追加。

    示例输出：
      04:00:00.123 INFO     duoweilai.request: request completed status=200 duration_ms=12.3
    """

    _COLORS = {
        "DEBUG": "\033[36m",  # cyan
        "INFO": "\033[32m",  # green
        "WARNING": "\033[33m",  # yellow
        "ERROR": "\033[31m",  # red
        "CRITICAL": "\033[35m",  # magenta
    }
    _RESET = "\033[0m"
    _BOLD = "\033[1m"

    def __init__(self, use_color: bool = True):
        super().__init__()
        self.use_color = use_color and sys.stderr.isatty()

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, tz=timezone.utc).strftime("%H:%M:%S.%f")[:-3]

        color = self._COLORS.get(record.levelname, "") if self.use_color else ""
        reset = self._RESET if self.use_color else ""

        line = f"{color}{ts} {record.levelname:<7}{reset} {record.name}: {record.getMessage()}"

        # 附加字段紧凑输出
        extras = []
        for key, value in record.__dict__.items():
            if key not in _STANDARD_RECORD_KEYS and not key.startswith("_"):
                extras.append(f"{key}={value}")
        if extras:
            line += " " + " ".join(extras)

        if record.exc_info:
            line += "\n" + self.formatException(record.exc_info)
        return line


# ============================================================
# Setup
# ============================================================
_CONFIGURED = False


def setup_logging(
    level: str | None = None,
    fmt: str | None = None,
    stream: Any = None,
) -> None:
    """配置根 logger（幂等：重复调用不会叠加 handler）。

    Args:
        level: 日志级别，默认读 $DUOWEILAI_LOG_LEVEL，否则 INFO
        fmt:   'human' 或 'json'，默认读 $DUOWEILAI_LOG_FORMAT，否则 human
        stream: 输出流，默认 sys.stdout
    """
    global _CONFIGURED

    level = (level or os.environ.get("DUOWEILAI_LOG_LEVEL") or "INFO").upper()
    fmt = (fmt or os.environ.get("DUOWEILAI_LOG_FORMAT") or "human").lower()
    if fmt not in ("human", "json"):
        fmt = "human"

    handler = logging.StreamHandler(stream or sys.stdout)
    handler.setFormatter(JsonFormatter() if fmt == "json" else HumanFormatter(use_color=True))
    handler.setLevel(level)

    root = logging.getLogger()
    root.setLevel(level)

    # 幂等：清掉旧 handler 避免重复日志
    if _CONFIGURED:
        for h in list(root.handlers):
            root.removeHandler(h)
    root.addHandler(handler)

    # Werkzeug (Flask dev server) 默认 access log 很吵，生产模式下关掉
    logging.getLogger("werkzeug").setLevel("WARNING")

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """便捷别名：等价于 logging.getLogger(name)。"""
    return logging.getLogger(name)


# ============================================================
# Flask 集成（可选）
# ============================================================
def install_request_logging(app, *, level: str = "INFO") -> None:
    """为 Flask app 安装请求生命周期日志中间件。

    日志点：
      - 请求开始：method/path/ip/user_agent
      - 请求结束：method/path/status/duration_ms/user_id
      - 异常：exc_info（带 request_id 关联）

    每条请求分配一个 8 字节 request_id，可通过 flask.g.request_id 访问。
    """
    setup_logging(level=level)
    log = get_logger("duoweilai.request")

    @app.before_request
    def _log_request_start():
        from flask import g, request

        g._req_start = time.perf_counter()
        g.request_id = secrets.token_hex(4)
        log.info(
            "request start",
            extra={
                "request_id": g.request_id,
                "method": request.method,
                "path": request.path,
                "ip": request.remote_addr or "?",
                "ua": request.headers.get("User-Agent", ""),
            },
        )

    @app.after_request
    def _log_request_end(resp):
        from flask import g, request

        duration_ms = (time.perf_counter() - g._req_start) * 1000
        user_id = getattr(getattr(g, "user", None), "id", None)
        log.info(
            "request done",
            extra={
                "request_id": getattr(g, "request_id", "?"),
                "method": request.method,
                "path": request.path,
                "status": resp.status_code,
                "duration_ms": round(duration_ms, 2),
                "bytes": resp.calculate_content_length() or 0,
                "user_id": user_id,
            },
        )
        resp.headers.setdefault("X-Request-ID", getattr(g, "request_id", ""))
        return resp

    @app.errorhandler(Exception)
    def _log_exception(e):
        from flask import g

        log.exception(
            "unhandled exception",
            extra={
                "request_id": getattr(g, "request_id", "?"),
                "exc_type": type(e).__name__,
            },
        )
        # 重新抛出让 Flask 走默认 500 处理
        raise
