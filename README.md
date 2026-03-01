# OpenAI Auto-Registrar with Dashboard 🚀

这是一个专为 **OpenAI 账号自动注册** 设计的工具，集成了高效的自动化注册脚本和现代化的 FastAPI 后端管理面板。

[![GitHub Repo](https://img.shields.io/badge/GitHub-Repository-blue?logo=github)](https://github.com/ruinny/openai-auto-registrar)
[![Python Version](https://img.shields.io/badge/Python-3.14+-green?logo=python)](https://pyproject.toml)
[![Framework](https://img.shields.io/badge/Framework-FastAPI-009688?logo=fastapi)](https://fastapi.tiangolo.com/)

---

## 🌟 功能特性

### 🤖 核心注册引擎 (`singup.py`)
- **全自动流程**: 自动生成邮箱、接收验证码、绕过 Sentinel 安全检测、填写个人资料。
- **Mail.tm 集成**: 使用临时邮箱 API，无需手动准备邮箱账号。
- **指纹模拟**: 深度集成 `curl-cffi`，完美模拟浏览器指纹，降低被拦截风险。
- **智能重试**: 内置错误处理与随机延迟，提高批量注册成功率。

### 📊 Web 控制面板 (`app.py`)
- **实时监控**: 仪表盘实时显示总注册数、成功数及失败数。
- **流式日志**: 网页端实时展示注册进度，无需查看控制台。
- **灵活配置**: 支持在页面动态设置代理地址。
- **文件管理**: 自动保存 `token_*.json` 文件，支持在线**预览**、**下载单个**、**打包下载全部**及**一键清空**。
- **响应式 UI**: 使用 Tailwind CSS 构建，完美适配桌面与移动端。

---

## 🛠️ 技术栈

- **后端**: FastAPI, Uvicorn, Python 3.14+
- **前端**: HTML5, Tailwind CSS, JavaScript (Fetch API)
- **网络层**: `curl_cffi` (用于绕过 TLS/指纹检测)
- **邮件服务**: Mail.tm API

---

## 🚀 快速上手

### 1. 克隆项目
```bash
git clone https://github.com/ruinny/openai-auto-registrar.git
cd openai-auto-registrar
```

### 2. 安装依赖
本项目推荐使用 `uv` 进行包管理（更快速、可靠）：
```bash
uv sync
```

### 3. 启动管理后台
```bash
uv run python app.py
```

### 4. 访问面板
打开浏览器，访问：
[**http://localhost:8000**](http://localhost:8000)

---

## ⚙️ 使用说明

1. **设置代理**: 由于 OpenAI 的地区限制，建议在面板中输入支持访问 OpenAI 的代理地址（如 `http://127.0.0.1:7890`）。
2. **启动服务**: 点击“启动服务”按钮，系统将开启后台线程循环执行注册逻辑。
3. **获取结果**: 注册成功后的 Token 会以 JSON 格式保存在项目根目录下，文件名格式为 `token_邮箱名_时间戳.json`。
4. **导出数据**: 使用右侧面板的“打包下载全部”功能，可以一次性导出所有账号信息。

---

## ⚠️ 免责声明

本工具仅用于学习交流和合规的自动化测试目的。请在使用过程中遵守相关法律法规及 OpenAI 的服务条款。严禁用于非法牟利或恶意攻击。

---

## 📄 开源协议

本项目基于 MIT 协议开源。

---
*Created with ❤️ by Claude Code*
