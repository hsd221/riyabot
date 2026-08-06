# 🔧 Tool 组件详解

## Tool 在当前架构中的定位

Tool 是 RiyaBot 的原生 LLM 工具组件。插件通过 `BaseTool` 注册结构化参数和执行函数，工具启用后会直接进入原生工具目录，模型按需发起 Tool Call。

聊天层还会把内置 `reply` 和兼容 `BaseAction` 放进同一个目录。因此，Tool 是原生组件契约；Action 是仍然可用的旧组件契约，二者共享 Tool Call 的执行协议，但不是同一个基类。

### Tool 的特点

- 🔍 **结构化调用**：使用参数定义约束模型传入的数据
- 📊 **原生目录**：启用后直接注册到 LLM 可用工具列表
- 🔌 **插件式架构**：支持独立开发和注册新工具
- ⚡ **结果可追踪**：执行结果作为 Tool Result 返回聊天流程

### Tool、Action 与 Command 的区别

| 特征 | Action | Command | Tool |
|-----|-------|---------|------|
| **组件基类** | `BaseAction` | `BaseCommand` | `BaseTool` |
| **主要用途** | 兼容现有的自主聊天动作 | 响应用户明确指令 | 提供原生结构化能力 |
| **触发方式** | 激活筛选后由模型通过 Tool Call 选择 | 正则表达式匹配用户输入 | 模型按工具定义发起 Tool Call |
| **执行入口** | `ActionManager` 创建 Action 实例 | Command 运行时 | `ToolExecutor` 创建 Tool 实例 |
| **适合场景** | 表情、语音等已有 Action 行为 | 管理、查询和确定性命令 | 信息查询或其他需要结构化参数的能力 |

新插件需要被模型直接调用时，优先从 `BaseTool` 开始。只有需要 Action 的激活机制，或需要延续已有 Action 插件时，才选择 `BaseAction`。

## 🏗️ Tool组件的基本结构

每个工具必须继承 `BaseTool` 基类并实现以下属性和方法：
```python
from typing import Any

from src.plugin_system import BaseTool, ToolParamType

class MyTool(BaseTool):
    # 工具名称，必须唯一
    name = "my_tool"
    
    # 工具描述，告诉LLM这个工具的用途
    description = "这个工具用于获取特定类型的信息"
    
    # 参数定义，仅定义参数
    # 比如想要定义一个类似下面的openai格式的参数表，则可以这么定义:
    # {
    #     "type": "object",
    #     "properties": {
    #         "query": {
    #             "type": "string",
    #             "description": "查询参数"
    #         },
    #         "limit": {
    #             "type": "integer", 
    #             "description": "结果数量限制"
    #             "enum": [10, 20, 50]  # 可选值
    #         }
    #     },
    #     "required": ["query"]
    # }
    parameters = [
        ("query", ToolParamType.STRING, "查询参数", True, None),  # 必填参数
        ("limit", ToolParamType.INTEGER, "结果数量限制", False, ["10", "20", "50"])  # 可选参数
    ]

    available_for_llm = True  # 是否对LLM可用
    
    async def execute(self, function_args: dict[str, Any]) -> dict[str, Any]:
        """执行工具逻辑"""
        # 实现工具功能
        result = f"查询结果: {function_args.get('query')}"
        
        return {
            "name": self.name,
            "content": result
        }
```

### 属性说明

| 属性 | 类型 | 说明 |
|-----|------|------|
| `name` | str | 工具的唯一标识名称 |
| `description` | str | 工具功能描述，帮助LLM理解用途 |
| `parameters` | list[tuple] | 参数定义 |

其构造而成的工具定义为:
```python
definition: dict[str, Any] = {"name": cls.name, "description": cls.description, "parameters": cls.parameters}
```

### 方法说明

| 方法 | 参数 | 返回值 | 说明 |
|-----|------|--------|------|
| `execute` | `function_args` | `dict` | 执行工具核心逻辑 |

---

## 🎨 完整工具示例

完成一个天气查询工具

```python
from typing import Any

from src.plugin_system import BaseTool, ToolParamType
import aiohttp

class WeatherTool(BaseTool):
    """天气查询工具 - 获取指定城市的实时天气信息"""
    
    name = "weather_query"
    description = "查询指定城市的实时天气信息，包括温度、湿度、天气状况等"
    available_for_llm = True  # 允许LLM调用此工具
    parameters = [
        ("city", ToolParamType.STRING, "要查询天气的城市名称，如：北京、上海、纽约", True, None),
        ("country", ToolParamType.STRING, "国家代码，如：CN、US，可选参数", False, None)
    ]
    
    async def execute(self, function_args: dict[str, Any]) -> dict[str, Any]:
        """执行天气查询"""
        try:
            city = function_args.get("city")
            country = function_args.get("country", "")
            
            # 构建查询参数
            location = f"{city},{country}" if country else city
            
            # 调用天气API（示例）
            weather_data = await self._fetch_weather(location)
            
            # 格式化结果
            result = self._format_weather_data(weather_data)
            
            return {
                "name": self.name,
                "content": result
            }
            
        except Exception:
            return {
                "name": self.name,
                "content": "天气查询失败，请稍后重试。"
            }
    
    async def _fetch_weather(self, location: str) -> dict:
        """获取天气数据"""
        # 这里是示例，实际需要接入真实的天气API
        api_url = "https://api.weather.com/v1/current"

        async with aiohttp.ClientSession() as session:
            async with session.get(api_url, params={"q": location}, timeout=10) as response:
                response.raise_for_status()
                return await response.json()
    
    def _format_weather_data(self, data: dict) -> str:
        """格式化天气数据"""
        if not data:
            return "暂无天气数据"
        
        # 提取关键信息
        city = data.get("location", {}).get("name", "未知城市")
        temp = data.get("current", {}).get("temp_c", "未知")
        condition = data.get("current", {}).get("condition", {}).get("text", "未知")
        humidity = data.get("current", {}).get("humidity", "未知")
        
        # 格式化输出
        return f"""
🌤️ {city} 实时天气
━━━━━━━━━━━━━━━━━━
🌡️ 温度: {temp}°C
☁️ 天气: {condition}
💧 湿度: {humidity}%
━━━━━━━━━━━━━━━━━━
        """.strip()
```

---

## 🚨 注意事项和限制

### 使用边界

1. **启用要求**：只有 `available_for_llm = True` 的 Tool 会进入 LLM 工具目录。
2. **参数校验**：`parameters` 描述模型输入格式，执行函数仍需校验外部数据，不能把模型返回值当作可信输入。
3. **聊天上下文**：`BaseTool` 提供 `chat_stream` 和配置访问能力；发送消息、读取消息等操作应通过 `src.plugin_system.apis` 门面完成。

### 开发建议

1. **功能专一**：每个工具专注单一功能
2. **参数明确**：清晰定义工具参数和用途
3. **错误处理**：完善的异常处理和错误反馈
4. **性能考虑**：避免长时间阻塞操作
5. **信息准确**：确保获取信息的准确性和时效性

## 🎯 最佳实践

### 1. 工具命名规范
#### ✅ 好的命名
```python
name = "weather_query"        # 清晰表达功能
name = "knowledge_search"     # 描述性强
name = "stock_price_check"    # 功能明确
```
#### ❌ 避免的命名
```python
name = "tool1"               # 无意义
name = "wq"                  # 过于简短
name = "weather_and_news"    # 功能过于复杂
```

### 2. 描述规范
#### ✅ 良好的描述
```python
description = "查询指定城市的实时天气信息，包括温度、湿度、天气状况"
```
#### ❌ 避免的描述
```python
description = "天气"         # 过于简单
description = "获取信息"      # 不够具体
```

### 3. 参数设计

#### ✅ 合理的参数设计
```python
parameters = [
    ("city", ToolParamType.STRING, "城市名称，如：北京、上海", True, None),
    ("unit", ToolParamType.STRING, "温度单位：celsius 或 fahrenheit", False, ["celsius", "fahrenheit"])
]
```
#### ❌ 避免的参数设计
```python
parameters = [
    ("data", "string", "数据", True)  # 参数过于模糊
]
```

### 4. 结果格式化
#### ✅ 良好的结果格式
```python
def _format_result(self, data):
    return f"""
🔍 查询结果
━━━━━━━━━━━━
📊 数据: {data['value']}
📅 时间: {data['timestamp']}
📝 说明: {data['description']}
━━━━━━━━━━━━
    """.strip()
```
#### ❌ 避免的结果格式
```python
def _format_result(self, data):
    return str(data)  # 直接返回原始数据
```

## Action 兼容说明

`BaseAction` 不再作为新插件的独立主组件介绍。它仍然由聊天层转换为 Tool Call，并通过原有的 `ActionManager` 执行，主要用于维护已有插件或需要激活机制的组件。

需要维护或迁移现有 Action 时，再阅读 [Action 组件（兼容层）](./action-components.md)。新插件请从本页的 `BaseTool` 开始。

## 相关文档

- [Command 组件](./command-components.md) — 响应用户明确输入的命令。
- [插件快速开始](./quick-start.md) — 从插件骨架开始了解组件注册方式。
