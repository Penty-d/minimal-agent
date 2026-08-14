"""weather 工具：天气查询（演示环境为 mock 数据）。

用 crc32(城市名) 做确定性哈希：同一城市每次结果一致，便于测试与演示。
接入真实天气 API（高德 / 和风）时替换 execute 实现即可。
"""

from __future__ import annotations

import zlib

from agent.tools.base import Tool, ToolError, ToolSpec

_CONDITIONS = ["晴", "多云", "小雨", "阴", "阵雨", "晴转多云"]


class WeatherTool(Tool):
    spec = ToolSpec(
        name="weather",
        description=(
            "查询城市当天天气（气温、天气状况、风力、湿度）。"
            "用户问天气、气温、要不要带伞时使用。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "城市名，如 '北京'"},
            },
            "required": ["city"],
        },
    )

    def execute(self, city: str = "") -> str:
        if not city.strip():
            raise ToolError("city 不能为空")
        h = zlib.crc32(city.strip().encode("utf-8"))
        temp = 15 + h % 20                     # 15~34 度
        cond = _CONDITIONS[h % len(_CONDITIONS)]
        wind = (h // 10) % 6 + 1               # 1~6 级
        humidity = 40 + (h // 100) % 50        # 40~89%
        return (
            f"{city} 今天：{cond}，气温 {temp}°C，风力 {wind} 级，"
            f"相对湿度 {humidity}%。"
        )
