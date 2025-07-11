# 🔮 SRT 深度翻译器 Pro

[![Python](https://img.shields.io/badge/Python-3.9+-blue.svg)](https://www.python.org/)
[![Frameworks](https://img.shields.io/badge/Frameworks-FastAPI%20%7C%20Streamlit-green)](https://fastapi.tiangolo.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)

一个由 Google Gemini 模型驱动的、专业级的 SRT 字幕文件批量翻译工具。它不仅提供高质量的翻译，还包含了智能断句、双语支持和实时流式处理等高级功能，旨在为用户提供一站式的字幕本地化解决方案。

## ✨ 核心功能

* **🧠 上下文感知翻译**: 通过智能分组，将零散的字幕行组合成完整的句子再进行翻译，极大提升了翻译的连贯性和准确性。
* **🚀 双模型支持**: 可在 `Gemini 1.5 Flash` (高速经济) 和 `Gemini 1.5 Pro` (高质量) 之间自由切换，平衡成本与效果。
* **✂️ 智能长句断句**: 对于时长过长的字幕，可调用AI进行二次处理，根据语义和语音停顿智能地将其拆分为多个更易于阅读的短句，并自动重新计算时间轴。
* ** bilingual 支持 **: 支持生成“仅译文”或多种格式的“中英/英中”双语字幕，满足不同场景（如语言学习、专业校对）的需求。
* **⚡️ 实时流式界面**: 前端采用 Streamlit 构建，后端使用 FastAPI 流式响应。用户可以实时看到翻译进度和状态更新，无需长时间等待。
* **📦 批量处理**: 支持一次性上传和翻译多个 SRT 文件，并提供打包下载功能。
* **🎨 高度可配置**: 从翻译质量、显示格式到智能断句的触发条件，几乎所有关键参数都可以在UI界面上进行调整。
* **🔒 隐私安全**: 所有翻译处理均通过您自己的API密钥在后端完成，字幕文件内容不会被第三方服务存储。

## 🛠️ 技术栈

* **后端**: Python 3.9+, FastAPI, Uvicorn
* **前端**: Streamlit
* **AI核心**: Google Generative AI (Gemini)
* **依赖管理**: pip

## 🏗️ 项目架构

本工具采用前后端分离的经典架构：

1.  **前端 (Streamlit)**: 作为用户交互界面，负责文件上传、参数配置、向后端发起请求，并以流式方式接收和展示结果。
2.  **后端 (FastAPI)**: 作为核心处理引擎，负责接收文件、解析SRT、调用Google Gemini API进行翻译和智能处理，并通过流式HTTP响应将结果返回给前端。
3.  **Google AI**: 实际执行翻译和自然语言处理任务的云服务。

```
[用户浏览器] <--> [Streamlit 前端服务] <--> [FastAPI 后端API] <--> [Google Gemini API]
```

## 🚀 快速开始

请按照以下步骤在您的本地计算机上部署和运行此工具。

### 1. 先决条件

* 已安装 [Python 3.9](https://www.python.org/downloads/) 或更高版本。
* 已安装 `pip` 包管理器。
* 拥有一个有效的 [Google AI Studio API Key](https://aistudio.google.com/app/apikey)。

### 2. 克隆项目

```bash
git clone [https://github.com/your-username/your-repo-name.git](https://github.com/your-username/your-repo-name.git)
cd your-repo-name
```

### 3. 安装依赖

在项目根目录下打开终端，运行下面这**一行代码**来安装所有必需的Python库，无需创建新文件：

```bash
pip install fastapi "uvicorn[standard]" streamlit requests python-dotenv google-generativeai
```
*(提示: 我们将 `uvicorn[standard]` 加上引号，以确保在所有类型的终端中都能正确安装。)*

### 4. 配置API密钥

1.  在项目根目录下，创建一个名为 `.env` 的文件。
2.  在该文件中添加您的Google Gemini API密钥，格式如下：

    ```
    GEMINI_API_KEY="在这里填入您的API密钥"
    ```

### 5. 启动后端服务

在终端中运行以下命令来启动FastAPI后端服务器：

```bash
uvicorn main:app --host 127.0.0.1 --port 8000
```

您应该会看到类似 `Application startup complete.` 的输出，表示后端已成功运行在 `http://127.0.0.1:8000`。

### 6. 启动前端界面

**新开一个终端窗口**，进入项目根目录，然后运行以下命令来启动Streamlit前端应用：

```bash
streamlit run streamlit_app.py
```

您的浏览器会自动打开一个新的标签页，地址通常是 `http://localhost:8501`。

### 7. 开始使用

现在，您可以通过浏览器界面上传SRT文件，调整设置，然后开始翻译了！

## ⚙️ 详细配置

### 后端配置 (`main.py`)

您可以直接在 `main.py` 文件中修改一些核心参数的默认值：

* **API相关**: `MAX_CHARS_PER_BATCH`, `MAX_RETRIES`, `RATE_LIMIT_DELAY`, `API_TIMEOUT_SECONDS` 等。
* **功能默认值**: 在 `@app.get("/config")` 路由下，您可以修改所有提供给前端的默认配置，例如：
    * 默认的目标语言 (`default_target_language`)
    * 智能断句的默认参数 (`sentence_break_features`)

### 前端配置 (`streamlit_app.py`)

在前端页面的侧边栏，用户可以动态配置后端的API地址和请求超时时间，这在将前后端部署在不同机器上时非常有用。

## 📚 API接口文档

本项目的后端基于FastAPI构建，因此它**自动生成了交互式的API文档**。当后端服务运行时，您可以通过访问以下地址来查看和测试API：

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

[使用 Gemini 来翻译 .srt 字幕文件]https://linux.do/t/topic/353949

---
*该文档最后更新于 2025年7月11日。*
