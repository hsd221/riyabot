# 📄 插件 Manifest 系统指南

## 概述

每个 RiyaBot 插件都必须包含一个 `_manifest.json` 文件，用于描述插件的基本信息、依赖关系和组件等元数据。

### 配置架构：Manifest 与 Config 的职责分离

为了避免信息重复、降低维护成本，插件元数据采用**双文件架构**：

- **`_manifest.json`** — 插件的**静态元数据**
  - 插件身份信息（名称、版本、描述）
  - 开发者信息（作者、许可证、仓库）
  - 系统信息（兼容性、组件列表、分类）

- **`config.toml`** — 插件的**运行时配置**
  - 启用状态（`enabled`）
  - 功能参数配置
  - 用户可调整的行为设置

这种分离让元数据统一管理、运行时配置灵活调整，各司其职、互不重复。

## 🔧 Manifest 文件结构

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

## 🛠️ 校验机制

插件加载时，系统会通过 `ManifestValidator`（位于 `src/plugin_system/utils/manifest_utils.py`）自动读取并校验插件目录下的 `_manifest.json`。校验结果分为两类：

- **错误**（缺少必需字段、字段为空、不支持的 manifest 版本、作者信息缺失等）会导致插件加载失败；
- **警告**（如未填写 `license`、`keywords` 等建议字段）不会阻止加载。

无需手动运行任何命令行工具——只要把正确的 `_manifest.json` 放在插件目录下，加载时就会自动校验。

### 常见校验结果

必需字段缺失会产生类似下面的错误，导致插件无法加载：

```
- 缺少必需字段: name
- 作者信息缺少name字段或为空
```

建议填写但非必需的字段只会产生警告：

```
- 建议填写字段: license
- 建议填写字段: keywords
```

## 🔄 迁移与新建

### 对于现有插件

1. 在插件目录下创建 `_manifest.json`；
2. 至少填写必需字段（`manifest_version`、`name`、`version`、`description`、`author.name`）；
3. 重新加载插件，若校验失败按错误提示修正。

### 对于新插件

1. **创建插件目录和基本文件**（放在项目根目录的 `plugins/` 下）；
2. **手写 `_manifest.json`**，可参考下方的必需/可选字段；
3. **编写插件代码**；
4. **启动 RiyaBot**，在日志中确认插件加载成功、manifest 校验通过。

## 📋 字段说明

### 基本信息

- `manifest_version`: manifest 格式版本，当前为 1
- `name`: 插件显示名称（必需）
- `version`: 插件版本号（必需）
- `description`: 插件功能描述（必需）
- `author`: 作者信息（必需）
  - `name`: 作者名称（必需）
  - `url`: 作者主页（可选）

### 许可和 URL

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

⚠️ 不填写时，插件默认支持所有版本。**（由于不同版本对插件系统做过大量重构，实际往往并非如此，建议始终声明。）**

### 国际化

- `default_locale`: 默认语言（可选）
- `locales_path`: 语言文件目录（可选）

### 插件特定信息

- `plugin_info`: 插件详细信息（可选）
  - `is_built_in`: 是否为内置插件
  - `plugin_type`: 插件类型
  - `components`: 组件列表

## ⚠️ 注意事项

1. **强制要求**：所有插件必须包含 `_manifest.json` 文件，否则无法加载；
2. **编码格式**：manifest 文件必须使用 UTF-8 编码；
3. **JSON 格式**：文件必须是有效的 JSON 格式；
4. **必需字段**：`manifest_version`、`name`、`version`、`description`、`author.name` 是必需的；
5. **版本兼容**：当前只支持 `manifest_version = 1`。

## 🔍 常见问题

### Q: 可以不填写可选字段吗？

A: 可以。所有标记为"可选"的字段都可以不填写，但建议至少填写 `license` 和 `keywords`。

### Q: manifest 校验失败怎么办？

A: 根据校验器的错误提示修复相应问题。错误会导致插件加载失败，警告不会。

## 📚 参考示例

查看内置插件的 manifest 文件作为参考：

- `src/plugins/built_in/tts_plugin/_manifest.json`
- `src/plugins/built_in/emoji_plugin/_manifest.json`
- `src/plugins/built_in/plugin_management/_manifest.json`
