# 个人信息API

个人信息API模块提供用户信息查询功能，让插件能够获取用户的相关信息。

## 导入方式

```python
from src.plugin_system.apis import person_api
# 或者
from src.plugin_system import person_api
```

## 主要功能

### 1. Person ID 获取
```python
def get_person_id(platform: str, user_id: int | str) -> str:
```
根据平台和用户ID获取person_id

**Args:**
- `platform`：平台名称，如 "qq", "telegram" 等
- `user_id`：用户ID，可以是 int 或 str

**Returns:**
- `str`：唯一的person_id（MD5哈希值）

#### 示例
```python
person_id = person_api.get_person_id("telegram", 123456)
```

### 2. 用户信息查询
```python
async def get_person_value(person_id: str, field_name: str, default: Any = None) -> Any:
```
查询单个用户信息字段值

**Args:**
- `person_id`：用户的唯一标识ID
- `field_name`：要获取的字段名
- `default`：字段值不存在时的默认值

**Returns:**
- `Any`：字段值或默认值

#### 示例
```python
nickname = await person_api.get_person_value(person_id, "nickname", "未知用户")
person_name = await person_api.get_person_value(person_id, "person_name")
```

### 3. 根据用户名获取Person ID
```python
def get_person_id_by_name(person_name: str) -> str:
```
根据用户名获取person_id

**Args:**
- `person_name`：用户名

**Returns:**
- `str`：person_id，如果未找到返回空字符串

## 常用字段说明

`get_person_value` 的 `field_name` 对应 `Person` 对象（`src.common.person_stub.Person`）的属性，当前可用字段：

- `platform`：平台标识
- `user_id`：用户ID
- `person_id`：用户唯一标识
- `person_name`：用户名
- `nickname`：用户昵称
- `is_known`：是否已知用户
- `know_times`：认识次数
- `memory_points`：记忆点列表

> 提示：`Person` 目前是过渡期的桩实现（`src/common/person_stub.py`），后续会替换为完整的用户画像系统。字段以源码中 `Person` 类的属性为准。

## 注意事项

1. **异步操作**：`get_person_value` 是异步函数，需要使用 `await`
2. **数据一致性**：person_id 是用户的唯一标识，应妥善保存和使用
3. **隐私保护**：确保用户信息的使用符合隐私政策
