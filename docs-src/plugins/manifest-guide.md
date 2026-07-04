# 📄 插件Manifest系统指南

## 概述

RiyaBot插件系统现在强制要求每个插件都必须包含一个 `_manifest.json` 文件。这个文件描述了插件的基本信息、依赖关系、组件等重要元数据。

### 🔄 配置架构：Manifest与Config的职责分离

为了避免信息重复和提高维护性，我们采用了**双文件架构**：

- **`_manifest.json`** - 插件的**静态元数据**
  - 插件身份信息（名称、版本、描述）
  - 开发者信息（作者、许可证、仓库）
  - 系统信息（兼容性、组件列表、分类）
  
- **`config.toml`** - 插件的**运行时配置**
  - 启用状态 (`enabled`)
  - 功能参数配置
  - 用户可调整的行为设置

这种分离确保了：
- ✅ 元数据信息统一管理
- ✅ 运行时配置灵活调整  
- ✅ 避免重复维护
- ✅ 更清晰的职责划分

## 🔧 Manifest文件结构

### 必需字段

以下字段是必需的，不能为空：

```json
{
  "manifest_version": 1,
  "name": "插件显示名称",
  "version": "1.0.0",
  "description": "插件功能描述",
  "author": {
    "name": "作者名称"
  }
}
```

### 可选字段

以下字段都是可选的，可以根据需要添加：

```json
{
  "license": "MIT",
  "host_application": {
    "min_version": "1.0.0",
    "max_version": "4.0.0"
  },
  "homepage_url": "https://github.com/your-repo",
  "repository_url": "https://github.com/your-repo",
  "keywords": ["关键词1", "关键词2"],
  "categories": ["分类1", "分类2"],
  "default_locale": "zh-CN",
  "locales_path": "_locales",
  "plugin_info": {
    "is_built_in": false,
    "plugin_type": "general",
    "components": [
      {
        "type": "action",
        "name": "组件名称",
        "description": "组件描述"
      }
    ]
  }
}
```

## 🛠️ 管理工具

### 使用manifest_tool.py

我们提供了一个命令行工具来帮助管理manifest文件：

```bash
# 扫描缺少manifest的插件
python scripts/manifest_tool.py scan src/plugins

# 为插件创建最小化manifest文件
python scripts/manifest_tool.py create-minimal src/plugins/my_plugin --name "我的插件" --author "作者"

# 为插件创建完整manifest模板
python scripts/manifest_tool.py create-complete src/plugins/my_plugin --name "我的插件"

# 验证manifest文件
python scripts/manifest_tool.py validate src/plugins/my_plugin
```

### 验证示例

验证通过的示例：
```
✅ Manifest文件验证通过
```

验证失败的示例：
```
❌ 验证错误:
  - 缺少必需字段: name
  - 作者信息缺少name字段或为空
⚠️ 验证警告:
  - 建议填写字段: license
  - 建议填写字段: keywords
```

## 🔄 迁移指南

### 对于现有插件

1. **检查缺少manifest的插件**：
   ```bash
   python scripts/manifest_tool.py scan src/plugins
   ```

2. **为每个插件创建manifest**：
   ```bash
   python scripts/manifest_tool.py create-minimal src/plugins/your_plugin
   ```

3. **编辑manifest文件**，填写正确的信息。

4. **验证manifest**：
   ```bash
   python scripts/manifest_tool.py validate src/plugins/your_plugin
   ```

### 对于新插件

创建新插件时，建议的步骤：

1. **创建插件目录和基本文件**
2. **创建完整manifest模板**：
   ```bash
   python scripts/manifest_tool.py create-complete src/plugins/new_plugin
   ```
3. **根据实际情况修改manifest文件**
4. **编写插件代码**
5. **验证manifest文件**

## 📋 字段说明

### 基本信息
- `manifest_version`: manifest格式版本，当前为1
- `name`: 插件显示名称（必需）
- `version`: 插件版本号（必需）
- `description`: 插件功能描述（必需）
- `author`: 作者信息（必需）
  - `name`: 作者名称（必需）
  - `url`: 作者主页（可选）

### 许可和URL
- `license`: 插件许可证（可选，建议填写）
- `homepage_url`: 插件主页（可选）
- `repository_url`: 源码仓库地址（可选）

### 分类和标签
- `keywords`: 关键词数组（可选，建议填写）
- `categories`: 分类数组（可选，建议填写）

### 兼容性
- `host_application`: 主机应用兼容性（可选，建议填写）
  - `min_version`: 最低兼容版本
  - `max_version`: 最高兼容版本

⚠️ 在不填写的情况下，插件将默认支持所有版本。**（由于我们在不同版本对插件系统进行了大量的重构，这种情况几乎不可能。）**

### 国际化
- `default_locale`: 默认语言（可选）
- `locales_path`: 语言文件目录（可选）

### 插件特定信息
- `plugin_info`: 插件详细信息（可选）
  - `is_built_in`: 是否为内置插件
  - `plugin_type`: 插件类型
  - `components`: 组件列表

## ⚠️ 注意事项

1. **强制要求**：所有插件必须包含`_manifest.json`文件，否则无法加载
2. **编码格式**：manifest文件必须使用UTF-8编码
3. **JSON格式**：文件必须是有效的JSON格式
4. **必需字段**：`manifest_version`、`name`、`version`、`description`、`author.name`是必需的
5. **版本兼容**：当前只支持`manifest_version = 1`

## 🔍 常见问题

### Q: 可以不填写可选字段吗？
A: 可以。所有标记为"可选"的字段都可以不填写，但建议至少填写`license`和`keywords`。

### Q: manifest验证失败怎么办？
A: 根据验证器的错误提示修复相应问题。错误会导致插件加载失败，警告不会。

## 📚 参考示例

查看内置插件的manifest文件作为参考：
- `src/plugins/built_in/core_actions/_manifest.json`
- `src/plugins/built_in/tts_plugin/_manifest.json`
- `src/plugins/hello_world_plugin/_manifest.json`
