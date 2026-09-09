"""Tests for the structured logging module.

Verifies:
  - JsonFormatter produces valid JSON with expected fields
  - HumanFormatter produces readable lines
  - Extra fields pass through correctly
  - Exception info serializes
  - Idempotent setup (no duplicate handlers)
"""

import io
import json
import logging
import sys

sys.path.insert(0, ".")

from app.logging_setup import (
    HumanFormatter,
    JsonFormatter,
    get_logger,
    setup_logging,
)


def make_record(name="test", level=logging.INFO, msg="hello", **extras):
    rec = logging.LogRecord(
        name=name,
        level=level,
        pathname=__file__,
        lineno=10,
        msg=msg,
        args=(),
        exc_info=None,
    )
    for k, v in extras.items():
        setattr(rec, k, v)
    return rec


# -------- JsonFormatter --------
def test_json_basic_fields():
    rec = make_record(msg="hello world")
    line = JsonFormatter().format(rec)
    obj = json.loads(line)
    assert obj["msg"] == "hello world"
    assert obj["level"] == "INFO"
    assert obj["logger"] == "test"
    assert "ts" in obj
    assert obj["ts"].endswith("+00:00")


def test_json_extra_fields_passthrough():
    rec = make_record(msg="op done", user_id=42, request_id="abc")
    obj = json.loads(JsonFormatter().format(rec))
    assert obj["user_id"] == 42
    assert obj["request_id"] == "abc"


def test_json_unicode_safe():
    rec = make_record(msg="多未来")
    obj = json.loads(JsonFormatter().format(rec))
    assert obj["msg"] == "多未来"


def test_json_exception_serializes():
    try:
        raise ValueError("boom")
    except ValueError:
        import sys as _s

        rec = logging.LogRecord(
            name="t",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="failed",
            args=(),
            exc_info=_s.exc_info(),
        )
    obj = json.loads(JsonFormatter().format(rec))
    assert obj["level"] == "ERROR"
    assert "ValueError: boom" in obj["exc"]


def test_json_non_serializable_fallback():
    class Opaque:
        def __repr__(self):
            return "<Opaque>"

    rec = make_record(msg="x", data=Opaque())
    obj = json.loads(JsonFormatter().format(rec))
    assert "Opaque" in obj["data"]


# -------- HumanFormatter --------
def test_human_basic():
    rec = make_record(msg="hello", user_id=1)
    out = HumanFormatter(use_color=False).format(rec)
    assert "INFO" in out
    assert "hello" in out
    assert "user_id=1" in out


def test_human_extra_keys_filtered():
    # msg 和 levelname 不应在 extras 列表中（避免重复）
    rec = make_record(msg="hi")
    out = HumanFormatter(use_color=False).format(rec)
    assert "msg=" not in out  # msg 已显示在主文本中


# -------- setup_logging --------
def test_setup_is_idempotent():
    buf = io.StringIO()
    setup_logging(level="INFO", fmt="json", stream=buf)
    setup_logging(level="INFO", fmt="json", stream=buf)
    root = logging.getLogger()
    assert len(list(root.handlers)) == 1, "setup_logging should not stack handlers"


def test_setup_respects_env():
    import os

    # 钉住全部相关环境变量：CI 的 step 可能预设 LOG_LEVEL=WARNING，
    # 若不显式指定 level，INFO 级测试消息会被过滤，buf 为空导致断言失败
    saved = {k: os.environ.get(k) for k in ("DUOWEILAI_LOG_FORMAT", "DUOWEILAI_LOG_LEVEL")}
    os.environ["DUOWEILAI_LOG_FORMAT"] = "json"
    os.environ["DUOWEILAI_LOG_LEVEL"] = "INFO"
    try:
        buf = io.StringIO()
        setup_logging(stream=buf)
        get_logger("test.idempotent").info("env-driven json")
        output = buf.getvalue().strip().splitlines()
        assert len(output) >= 1
        obj = json.loads(output[-1])
        assert obj["logger"] == "test.idempotent"
    finally:
        _restore_env(saved)


def test_setup_respects_level_env():
    import os

    saved = {k: os.environ.get(k) for k in ("DUOWEILAI_LOG_FORMAT", "DUOWEILAI_LOG_LEVEL")}
    os.environ["DUOWEILAI_LOG_LEVEL"] = "WARNING"
    try:
        buf = io.StringIO()
        setup_logging(stream=buf)
        get_logger("test.level").info("should not appear")
        assert "should not appear" not in buf.getvalue()
    finally:
        _restore_env(saved)


def _restore_env(saved):
    """恢复进入测试前的环境变量（预设值原样写回，未预设的移除）。"""
    import os

    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


# -------- runner --------
if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_") and callable(v)]
    passed = failed = 0
    for t in tests:
        try:
            t()
            print(f"  [PASS] {t.__name__}")
            passed += 1
        except Exception as e:
            print(f"  [FAIL] {t.__name__}: {e}")
            failed += 1
    print(f"\n=== Results: {passed} passed, {failed} failed ===")
    sys.exit(0 if failed == 0 else 1)
