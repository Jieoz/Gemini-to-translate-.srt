# 🔮 SRT 深度翻译器 Pro

[![Python](https://img.shields.io/badge/Python-3.9+-blue.svg)](https://www.python.org/)
[![Frameworks](https://img.shields.io/badge/Frameworks-FastAPI%20%7C%20Streamlit-green)](https://fastapi.tiangolo.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)

一个专业级的 SRT 字幕文件批量翻译工具，默认支持 Google Gemini，也可切换到第三方 OpenAI 兼容 API。它不仅提供高质量的翻译，还包含了智能断句、双语支持和实时流式处理等高级功能，旨在为用户提供一站式的字幕本地化解决方案。

## ✨ 核心功能

* **🧠 上下文感知翻译**: 通过智能分组，将零散的字幕行组合成完整的句子再进行翻译，极大提升了翻译的连贯性和准确性。
* **🚀 多模型 / 多提供商支持**: 默认支持 Gemini 官方接口，也可切换到第三方 OpenAI 兼容接口，平衡成本、速度与可用性。
* **✂️ 智能长句断句**: 对于时长过长的字幕，可调用AI进行二次处理，根据语义和语音停顿智能地将其拆分为多个更易于阅读的短句，并自动重新计算时间轴。
* **⚡️ bilingual 支持**: 支持生成“仅译文”或多种格式的“中英/英中”双语字幕，满足不同场景（如语言学习、专业校对）的需求。
* **⚡️ 实时流式界面**: 前端采用 Streamlit 构建，后端使用 FastAPI 流式响应。用户可以实时看到翻译进度和状态更新，无需长时间等待。
* **📦 批量处理**: 支持一次性上传和翻译多个 SRT 文件，并提供打包下载功能。
* **🎨 高度可配置**: 从翻译质量、显示格式到智能断句的触发条件，几乎所有关键参数都可以在UI界面上进行调整。
* **🔒 隐私安全**: 所有翻译处理均通过您自己的API密钥在后端完成，字幕文件内容不会被第三方服务存储。

## 🛠️ 技术栈

* **后端**: Python 3.9+, FastAPI, Uvicorn
* **前端**: Streamlit
* **AI核心**: Google Gemini / 第三方 OpenAI 兼容 API
* **依赖管理**: pip

## 🏗️ 项目架构

本工具采用前后端分离的经典架构：

1.  **前端 (Streamlit)**: 作为用户交互界面，负责文件上传、参数配置、向后端发起请求，并以流式方式接收和展示结果。
2.  **后端 (FastAPI)**: 作为核心处理引擎，负责接收文件、解析SRT、调用Google Gemini API进行翻译和智能处理，并通过流式HTTP响应将结果返回给前端。
3.  **模型提供商**: 可使用 Google Gemini，或使用支持 OpenAI Chat Completions 兼容协议的第三方服务。

```
[用户浏览器] <--> [Streamlit 前端服务] <--> [FastAPI 后端API] <--> [Gemini API / OpenAI-Compatible API]
```

## 🚀 快速开始

请按照以下步骤在您的本地计算机上部署和运行此工具。

## 当前优先改进方向

如果继续迭代这个项目，我建议优先做这几件事：

1. **补缓存机制**：减少重复字幕的 API 调用，直接降成本、提速度。
2. **收紧错误处理与并发控制**：避免批量文件或长字幕时因为并发过高导致超时或限流。
3. **把后端逻辑从 `main.py` 继续拆分**：把 SRT 解析、Gemini 调用、断句处理拆到独立模块，后续更容易维护和测试。
4. **优化分行策略**：当前仍偏按长度硬切，后面可改成优先按标点或空格断行，观感会明显更好。
5. **补 Docker 化部署**：让别人不用手配 Python 环境就能跑起来。
6. **增强第三方 API 兼容层**：逐步兼容更多 OpenAI 风格返回格式、错误格式和速率限制头。
7. **优化分行与断句策略**：在不破坏时间轴的前提下，优先按自然停顿而不是死按长度切分。

### 1. 先决条件

* 已安装 [Python 3.9](https://www.python.org/downloads/) 或更高版本。
* 已安装 `pip` 包管理器。
* 拥有一个有效的 Google Gemini API Key，或一个可用的第三方 OpenAI 兼容 API。

### 2. 克隆项目


```bash
git clone https://github.com/Jieoz/Gemini-to-translate-.srt.git
cd Gemini-to-translate-.srt
```


### 3. 安装依赖

在项目根目录下打开终端，优先使用 `requirements.txt` 安装：

```bash
pip install -r requirements.txt
```

如果你更喜欢手动安装，当前依赖等价于：

```bash
pip install fastapi "uvicorn[standard]" streamlit requests python-dotenv google-generativeai watchfiles python-multipart httpx
```

### 4. 配置API密钥

1.  先复制示例文件：

    ```bash
    cp .env.example .env
    ```

2.  在 `.env` 中选择一种提供商配置：

    **方案 A：官方 Gemini**
    ```env
    API_PROVIDER=gemini
    GEMINI_API_KEY=your_api_key_here
    ```

    **方案 B：第三方 OpenAI 兼容接口**
    ```env
    API_PROVIDER=openai_compat
    OPENAI_COMPAT_BASE_URL=https://your-provider.example/v1
    OPENAI_COMPAT_API_KEY=your_api_key_here
    OPENAI_COMPAT_MODEL=gpt-4o-mini
    OPENAI_COMPAT_MODELS=gpt-4o-mini,claude-3.5-sonnet
    MAX_TRANSLATION_BATCH_CONCURRENCY=3
    MAX_SPLIT_BATCH_CONCURRENCY=2
    ```

> `.env` 已默认视为本地私密文件，不应提交到仓库。
> `OPENAI_COMPAT_MODELS` 是可选项，用于控制前端可选模型列表。
> `MAX_TRANSLATION_BATCH_CONCURRENCY` / `MAX_SPLIT_BATCH_CONCURRENCY` 可用于在第三方 API 更容易限流时主动收紧并发。

### 5. 启动服务 (运行程序)

这个工具分为后端和前端，最省事的方式是直接运行：

```bat
run.bat
```

它会分别启动：
- FastAPI 后端：`main.py`
- Streamlit 前端：`webui.py`

您的浏览器通常会自动打开 `http://localhost:8501`。

如果你想手动启动，也可以分别运行：

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
streamlit run webui.py
```

### 6. 开始使用

现在，您可以通过浏览器界面上传SRT文件，调整设置，然后开始翻译了！

## ⚙️ 详细配置

### 后端配置 (`main.py`)

您可以直接在 `main.py` 文件中修改一些核心参数的默认值：

* **API相关**: `MAX_CHARS_PER_BATCH`, `MAX_RETRIES`, `RATE_LIMIT_DELAY`, `API_TIMEOUT_SECONDS`, `API_PROVIDER`, `MAX_TRANSLATION_BATCH_CONCURRENCY`, `MAX_SPLIT_BATCH_CONCURRENCY` 等。
* **功能默认值**: 在 `@app.get("/config")` 路由下，您可以修改所有提供给前端的默认配置，例如：
    * 默认的目标语言 (`default_target_language`)
    * 智能断句的默认参数 (`sentence_break_features`)

### 前端配置 (`webui.py`)

在前端页面的侧边栏，用户可以动态配置后端的 API 地址和请求超时时间，这在将前后端部署在不同机器上时非常有用。模型列表会根据后端当前提供商配置动态返回。

## 📚 API接口文档

本项目的后端基于 FastAPI 构建，因此它会自动生成交互式 API 文档。后端服务运行后，可访问：

* **健康检查**: [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health)
* **Swagger UI**: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
* **ReDoc**: [http://127.0.0.1:8000/redoc](http://127.0.0.1:8000/redoc)

这对于二次开发或将此翻译功能集成到其他应用中非常方便。

## 展望与贡献

我们欢迎任何形式的贡献来让这个项目变得更好！

### 未来路线图

* [ ] **缓存机制**: 为已翻译的句子添加缓存，减少重复API调用，降低成本。
* [ ] **术语表 (Glossary)**: 允许用户上传自定义术语表，确保专业词汇翻译的准确性和一致性。
* [ ] **二次精校流程**: 增加一个“审校”模式，在初翻后再次调用AI对全文进行润色。
* [ ] **Docker化部署**: 提供 `Dockerfile`，实现一键容器化部署。

### 如何贡献

1.  Fork 本仓库。
2.  创建一个新的分支 (`git checkout -b feature/YourAmazingFeature`)。
3.  提交您的代码 (`git commit -m 'Add some AmazingFeature'`)。
4.  将您的分支推送到GitHub (`git push origin feature/YourAmazingFeature`)。
5.  创建一个新的 Pull Request。

## 📄 许可证

本项目采用 [MIT License](LICENSE) 开源许可证。


## 项目借鉴


 [使用 Gemini 来翻译 .srt 字幕文件](https://linux.do/t/topic/353949)

---
*该文档最后更新于 2025年7月11日。*
