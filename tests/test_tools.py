"""工具层测试：计算器安全、搜索回退、天气确定性、todo 操作、注册表契约。"""

import json

import pytest

from agent.tools.registry import ToolRegistry, build_session_registry
from agent.tools.todo import TodoStore


@pytest.fixture
def registry():
    return build_session_registry(TodoStore())


# ----------------------------------------------------------------------
# calculator


def test_calculator_basic(registry):
    r = registry.execute("calculator", {"expression": "3.14 * 5**2"})
    assert r.error is None
    assert r.output == "78.5"


def test_calculator_functions(registry):
    assert registry.execute("calculator", {"expression": "sqrt(144) + 1"}).output == "13.0"
    assert registry.execute("calculator", {"expression": "2**10"}).output == "1024"
    assert registry.execute("calculator", {"expression": "pi"}).output == "3.1415926536"


def test_calculator_division_by_zero_returns_error(registry):
    r = registry.execute("calculator", {"expression": "1/0"})
    assert r.error and "除零" in r.error
    assert "工具执行失败" in r.to_api_content()     # 错误转文本回喂模型


def test_calculator_rejects_injection(registry):
    """eval 级注入（__import__/属性访问）必须被 AST 白名单拒绝。"""
    r = registry.execute("calculator", {"expression": '__import__("os").system("dir")'})
    assert r.error
    r2 = registry.execute("calculator", {"expression": "__import__('os')"})
    assert r2.error


def test_calculator_syntax_error(registry):
    r = registry.execute("calculator", {"expression": "sqrt("})
    assert r.error


# ----------------------------------------------------------------------
# search


def test_search_with_injected_backend():
    """注入假后端：验证真实路径返回后端结果（不依赖网络）。"""
    from agent.tools.search import SearchTool

    tool = SearchTool(backend=lambda q: [{"title": f"结果-{q}", "url": "https://x/", "snippet": "摘要"}])
    rows = json.loads(tool.execute("agent"))
    assert rows[0]["title"] == "结果-agent"


def test_search_fallback_on_backend_error():
    """后端抛错 → 回退本地演示数据，不崩、不抛。"""
    from agent.tools.search import SearchTool

    def boom(q):
        raise RuntimeError("network down")

    tool = SearchTool(backend=boom)
    rows = json.loads(tool.execute("agent"))
    assert rows and rows[0]["title"]


def test_search_empty_query_rejected(registry):
    r = registry.execute("search", {"query": "  "})
    assert r.error and "不能为空" in r.error


# ----------------------------------------------------------------------
# weather


def test_weather_deterministic(registry):
    a = registry.execute("weather", {"city": "北京"}).output
    b = registry.execute("weather", {"city": "北京"}).output
    assert a == b and "北京" in a


def test_weather_missing_city(registry):
    r = registry.execute("weather", {})
    assert r.error and "必要参数" in r.error


# ----------------------------------------------------------------------
# todo


def test_todo_lifecycle(registry):
    assert "（待办为空）" in registry.execute("todo", {"operation": "list"}).output
    registry.execute("todo", {"operation": "add", "item": "写周报"})
    out = registry.execute("todo", {"operation": "list"}).output
    assert "写周报" in out and "t1" in out
    registry.execute("todo", {"operation": "complete", "id": "t1"})
    assert "[x]" in registry.execute("todo", {"operation": "list"}).output
    registry.execute("todo", {"operation": "remove", "id": "t1"})
    assert "（待办为空）" in registry.execute("todo", {"operation": "list"}).output


# ----------------------------------------------------------------------
# registry


def test_schemas_format(registry):
    schemas = registry.schemas()
    assert len(schemas) == 4
    for s in schemas:
        assert s["type"] == "function"
        assert s["function"]["name"] and s["function"]["description"]
        assert s["function"]["parameters"]["type"] == "object"


def test_unknown_tool_returns_error(registry):
    r = registry.execute("nope", {})
    assert r.error and "未知工具" in r.error


def test_register_duplicate_raises():
    reg = build_session_registry(TodoStore())
    from agent.tools.search import SearchTool
    with pytest.raises(ValueError):
        reg.register(SearchTool())
