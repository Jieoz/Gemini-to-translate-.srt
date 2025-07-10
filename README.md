项目借鉴https://linux.do/t/topic/353949

-----

### **第零步：准备工作 (检查您的电脑)**

在开始之前，您需要确保您的电脑上安装了 **Python**。这个工具是基于Python的。

1.  **打开终端**:

      * 在 Windows 上，您可以搜索 "命令提示符" 或 "PowerShell" 并打开它。
      * 在 macOS 或 Linux 上，打开 "终端" (Terminal) 应用。

2.  **检查 Python 版本**:
    在终端里输入下面的命令，然后按回车：

    ```bash
    python --version
    ```

    或者

    ```bash
    python3 --version
    ```

    如果您看到了类似 `Python 3.x.x` 的版本号（例如 `Python 3.9.7`），说明您已经安装好了，可以进行下一步。如果没有，请先从Python官方网站 `python.org` 下载并安装最新版的Python。安装时请务必勾选 "Add Python to PATH" 的选项。

-----

### **第一步：项目设置 (创建文件夹)**

为了保持文件整洁，我们先为这个翻译工具创建一个专门的文件夹。

1.  选择一个您喜欢的位置（比如桌面或文档文件夹）。
2.  创建一个新的文件夹，并给它命名，例如 `SRT_Translator`。
3.  接下来的所有操作和文件都将保存在这个 `SRT_Translator` 文件夹里。

-----

4.  **获取 Gemini API 密钥**:

      * 这个工具使用 Google 的 Gemini 模型进行翻译，所以需要一个API密钥。
      * 访问 [Google AI Studio](https://aistudio.google.com/)。
      * 使用您的 Google 账号登录。
      * 登录后，点击页面上的 “**Get API key**”（获取API密钥）按钮。
      * 在弹出的窗口中，选择 “**Create API key in new project**”（在新项目中创建API密钥）。
      * 复制生成的这一长串字符。这就是您的API密钥，请妥善保管，不要泄露给他人。

-----

### **第二步：配置环境 (安装依赖和设置密钥)**

现在，我们要安装这个工具运行所需要的库，并把刚才获取的密钥配置好。

1.  **安装依赖库**:

      * 回到您之前打开的终端。
      * 首先，使用 `cd` 命令进入到我们创建的文件夹。例如，如果您的文件夹在桌面上，可以输入 (请根据您的实际路径修改):
        ```bash
        cd Desktop/SRT_Translator
        ```
      * 然后，复制并运行下面的命令，来安装所有必需的Python库：
        ```bash
        pip install fastapi uvicorn "google-generativeai>=0.4.0" python-dotenv python-multipart pydantic streamlit requests aiohttp
        ```
      * 等待终端完成安装过程。

2.  **配置API密钥**:

      * 在 `SRT_Translator` 文件夹中，创建一个新的文本文件。
      * **非常重要**：将这个文件命名为 `.env` (前面有一个点，没有其他名字)。
      * 用记事本或任何代码编辑器打开这个 `.env` 文件，输入以下内容：
        ```
        GEMINI_API_KEY=这里粘贴您刚刚从Google获取的API密钥
        ```
      * 将 `这里粘贴您刚刚从Google获取的API密钥` 替换成您自己的密钥字符串，然后保存文件。


-----

### **第三步：启动服务 (运行程序)**

这个工具分为后端和前端，需要`run.cmd`来分别运行它们。

-----

### **第四步：使用翻译工具**

现在，您的浏览器中应该已经显示了翻译工具的界面。

1.  **上传文件**: 点击界面上的 “**Upload an .srt file**” 按钮，选择您要翻译的SRT字幕文件。
2.  **选择模式**:
      * **翻译模式 (Translate Mode)**:
          * `Stream`: 流式模式，会一个一个地返回翻译结果，感觉上更快。
          * `Unary`: 一次性返回所有结果。
      * **显示格式 (Display Mode)**:
          * `Translated Only`: 只显示翻译后的文字。
          * `Original Top, Translated Bottom`: 上方显示原文，下方显示译文。
          * `Translated Top, Original Bottom`: 上方显示译文，下方显示原文。
3.  **开始翻译**: 点击 “**开始翻译 (Start Translation)**” 按钮。
4.  **查看结果**: 等待片刻，翻译完成的字幕内容就会出现在下方的文本框中。您可以直接从文本框中复制翻译好的内容。

-----

enjoy
