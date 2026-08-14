"""输出解析器测试：结构化 / 文本两条路径 + 容错。"""

import pytest

from agent.llm.client import RawLLMResponse
from agent.llm.parser import parse_response


def _tc(name, args, id="c1"):
    return {"id": id, "function": {"name": name, "arguments": args}}


def test_structured_tool_calls():
    raw = RawLLMResponse(tool_calls=[_tc("weather", '{"city": "北京"}')])
    step = parse_response(raw)
    assert step.has_tool_calls
    assert step.tool_calls[0].name == "weather"
    assert step.tool_calls[0].arguments == {"city": "北京"}


def test_invalid_json_arguments_is_salvaged():
    """模型不一定生成合法 JSON：解析失败保留原文，不抛异常。"""
    raw = RawLLMResponse(tool_calls=[_tc("weather", '{"city": "北京"')])   # 缺右括号
    step = parse_response(raw)
    assert step.has_tool_calls
    assert step.tool_calls[0].name == "weather"     # 名字仍可取到


def test_arguments_as_object():
    """部分实现直接返回 dict。"""
    raw = RawLLMResponse(tool_calls=[{"id": "c", "function": {"name": "todo", "arguments": {"operation": "list"}}}])
    step = parse_response(raw)
    assert step.tool_calls[0].arguments == {"operation": "list"}


def test_text_tool_call_with_thinking():
    raw = RawLLMResponse(content="<thinking>用户要查天气</thinking>\n<tool_call>{\"name\":\"weather\",\"arguments\":{\"city\":\"上海\"}}</tool_call>\n根据结果回答")
    step = parse_response(raw)
    assert step.thought == "用户要查天气"
    assert step.tool_calls[0].name == "weather"
    assert step.tool_calls[0].arguments == {"city": "上海"}


def test_text_tool_call_xml_style():
    raw = RawLLMResponse(content='<tool_call><name>calculator</name><arguments>{"expression": "1+2"}</arguments></tool_call>')
    step = parse_response(raw)
    assert step.tool_calls[0].name == "calculator"
    assert step.tool_calls[0].arguments == {"expression": "1+2"}


def test_multiple_text_tool_calls():
    raw = RawLLMResponse(
        content='<tool_call>{"name":"a","arguments":{}}</tool_call><tool_call>{"name":"b","arguments":{}}</tool_call>'
    )
    step = parse_response(raw)
    assert [t.name for t in step.tool_calls] == ["a", "b"]


def test_reasoning_content_plain_answer():
    raw = RawLLMResponse(reasoning="先想一下", content="这是答案", finish_reason="stop")
    step = parse_response(raw)
    assert step.thought == "先想一下"
    assert step.final_answer == "这是答案"
    assert not step.has_tool_calls


def test_empty_content_only_tool_calls():
    raw = RawLLMResponse(content=None, tool_calls=[_tc("todo", '{"operation": "list"}')])
    step = parse_response(raw)
    assert step.has_tool_calls
    assert step.final_answer is None
