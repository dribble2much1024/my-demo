# 请求头捕获 Chrome 插件 — 设计文档

**日期**：2026-06-30
**状态**：已确认

## 概述

一个 Manifest V3 Chrome 插件，捕获当前页面匹配的 API 请求头，并以 Apifox 可直接识别的格式复制到剪贴板。

## 目标

- 零依赖、零构建步骤 — 拖入 Chrome 扩展管理页面即可运行
- 最小权限范围
- 不注入 Content Script — 对目标页面零侵入

## 非目标

- 不与 Apifox 实时同步（不依赖 Apifox API）
- 不支持 HAR 导出、cURL 导出等高级导出格式
- 不做多标签页协调（各标签页的请求会混在同一个捕获缓冲区中 — 当前范围内可接受）

---

## 架构

```
┌─────────────────────────────────────────────────┐
│                  Chrome 插件                      │
│                                                  │
│  ┌──────────────┐     ┌───────────────────────┐  │
│  │  Popup UI    │◀───▶│   Service Worker      │  │
│  │  (popup/)    │     │   (background.js)     │  │
│  │              │     │                       │  │
│  │ - 字段配置   │     │ - webRequest 监听     │  │
│  │ - 请求列表   │     │ - 规则匹配引擎        │  │
│  │ - 一键复制   │     │ - 环形缓冲区管理      │  │
│  └──────────────┘     └───────────────────────┘  │
│         │                        │               │
│         ▼                        ▼               │
│  ┌──────────────────────────────────────────┐     │
│  │          chrome.storage.local             │     │
│  │  - 用户配置 (URL 匹配规则, 字段白名单)   │     │
│  │  - 捕获的请求头缓存 (环形缓冲)            │     │
│  └──────────────────────────────────────────┘     │
└─────────────────────────────────────────────────┘
```

### 数据流

1. 用户在 Popup 中配置 URL 匹配规则 + 请求头字段白名单 → 写入 `chrome.storage.local`
2. 页面发出 API 请求 → Service Worker 通过 `webRequest.onBeforeSendHeaders` 拦截
3. 将请求 URL 与配置的规则匹配；匹配成功后按字段白名单过滤请求头
4. 若请求中至少包含一个白名单内的请求头字段，记录存入 `chrome.storage.local` 环形缓冲区
5. 用户打开 Popup → 从 storage 读取缓冲区 → 渲染列表 → 点击"复制" → 以 Apifox 兼容格式写入剪贴板

---

## 组件设计

### Service Worker（`background.js`）

- 注册 `chrome.webRequest.onBeforeSendHeaders`，`extraInfoSpec: ["requestHeaders"]`
- 每次拦截请求时：
  1. 从 storage 读取 `settings.urlPatterns`（内存缓存，配置变更时刷新）
  2. 将 glob 通配符转为正则，与请求 URL 匹配
  3. 匹配成功后，读取 `settings.headerFields`
  4. 过滤请求头 — 只提取白名单中存在的字段
  5. 若过滤后的请求头非空，将捕获记录推入环形缓冲区
  6. 去重：同一 URL + 相同请求头值组合 5 秒内不重复记录
- 通过 `chrome.runtime.onMessage` 暴露接口，供 Popup 查询/清空捕获记录和更新配置

### Popup UI（`popup/`）

单页面弹窗，三个区域（无页面跳转）：

**顶部 — 标题栏**

- 插件名称 + 当前捕获数量

**中部 — 捕获列表（可滚动）**

- 每行展示：HTTP 方法标签、URL（截断显示）、捕获到的请求头字段名
- 点击行或"复制"按钮 → 以 `请求头名: 值\n` 格式写入剪贴板
- "全部复制"按钮一键复制所有记录
- 空状态提示："暂无捕获记录，请检查 URL 匹配规则"
- "清空"按钮清除缓冲区

**底部 — 配置区（可折叠）**

- URL 匹配规则输入框（每行一条，支持 `*.example.com/api/*` 通配符语法）
- 请求头字段输入框（逗号分隔，如 `Authorization, Cookie, X-Token`）
- "保存"按钮 → 写入 `chrome.storage.local`，通知 Service Worker 刷新规则

### 存储模型

```json
// chrome.storage.local 键结构
{
  "settings": {
    "urlPatterns": ["*.example.com/api/*"],
    "headerFields": ["Authorization", "Cookie", "X-Token"],
    "bufferSize": 50
  },
  "captures": [
    {
      "id": "uuid-v4",
      "url": "https://api.example.com/user/login",
      "method": "POST",
      "headers": { "Authorization": "Bearer eyJ...", "Cookie": "session=abc" },
      "timestamp": 1719740800000
    }
  ]
}
```

### 剪贴板输出格式

主格式（直接粘贴到 Apifox 请求头批量编辑区域）：

```
Authorization: Bearer eyJhbGciOi...
Cookie: session=abc123
Content-Type: application/json
```

备用格式（JSON，右键菜单可选）：

```json
[{"name":"Authorization","value":"Bearer eyJhbGciOi..."},{"name":"Cookie","value":"session=abc123"}]
```

### Glob 转正则转换

`background.js` 内置简单工具函数：

- `*` → `.*`
- `.` → `\\.`
- 首尾包裹 `^...$`

---

## 边缘情况

| 场景 | 处理方式 |
|---|---|
| 无匹配的捕获记录 | 显示空状态，提示检查 URL 规则 |
| URL 规则为空 | Service Worker 不拦截任何请求 |
| 请求头字段白名单为空 | 跳过所有请求，不捕获 |
| 环形缓冲区满 | 淘汰最旧记录，写入新记录 |
| 5 秒内重复请求 | 跳过（去重） |
| `webRequest` 权限未授予 | 插件安装失败，Chrome 提示用户确认 |
| 剪贴板写入失败（旧浏览器） | 降级显示可选中的文本供手动复制 |

---

## 项目结构

```
my-tool/
├── manifest.json
├── background.js            # Service Worker
├── popup/
│   ├── popup.html
│   ├── popup.js
│   └── popup.css
└── icons/
    ├── icon16.png
    ├── icon48.png
    └── icon128.png
```

---

## 权限声明

```json
{
  "permissions": ["storage", "webRequest"],
  "host_permissions": ["<all_urls>"]
}
```

`<all_urls>` 是 `webRequest` 拦截任意来源请求的必要条件，安装时由用户确认。

---

## 技术决策

| 决策 | 理由 |
|---|---|
| 不使用 UI 框架 | 弹窗简单 — 单 HTML 文件 + 约 200 行原生 JS 即可 |
| 不使用构建工具 | 零依赖，直接作为未打包扩展加载 |
| 不注入 Content Script | `webRequest` 可捕获全部所需请求头，无需页面注入 |
| 环形缓冲区存于 storage | 可跨 Service Worker 重启存活；有界大小防止存储膨胀 |
