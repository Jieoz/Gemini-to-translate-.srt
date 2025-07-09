import streamlit as st
import requests
import time
import os

# --- 页面配置 ---
st.set_page_config(
    page_title="SRT 批量翻译器",
    page_icon="🎬",
    layout="wide"
)

# --- 自定义CSS样式，美化界面 ---
st.markdown("""
<style>
    /* 主按钮样式 */
    .stButton>button {
        width: 100%;
        border-radius: 10px;
        border: 2px solid #4A90E2;
        background-color: #F0F8FF;
        color: #4A90E2;
        font-weight: bold;
    }
    .stButton>button:hover {
        border-color: #357ABD;
        background-color: #E0F0FF;
    }
    /* 下载按钮样式 */
    .stDownloadButton>button {
        width: 100%;
        border-radius: 10px;
        border: 2px solid #28a745;
        background-color: #E8F5E9;
        color: #28a745;
    }
    .stDownloadButton>button:hover {
        border-color: #218838;
        background-color: #D9EDDA;
    }
    /* 文本区域样式 */
    .stTextArea>div>div>textarea {
        border-radius: 10px;
    }
    /* Expander 样式 */
    .streamlit-expanderHeader {
        font-size: 1.1em;
        font-weight: bold;
    }
</style>
""", unsafe_allow_html=True)


# --- 自动滚动组件 ---
def auto_scroll():
    # --- 代码修正: 使用 setTimeout 确保在 DOM 更新后执行滚动 ---
    st.components.v1.html(
        """
        <script>
            // 使用一个小的延迟来确保 Streamlit 完成了 DOM 的重绘
            setTimeout(function() {
                // 在父级窗口中找到所有的文本区域(textarea)元素
                var textAreas = window.parent.document.querySelectorAll('textarea');
                if (textAreas.length > 0) {
                    // 将最后一个文本区域（即当前正在更新的结果框）滚动到底部
                    var lastTextArea = textAreas[textAreas.length - 1];
                    lastTextArea.scrollTop = lastTextArea.scrollHeight;
                }
            }, 150); // 150毫秒的延迟
        </script>
        """,
        height=0,
    )

# --- 主界面 ---
st.title("🎬 SRT 批量字幕翻译器")
st.markdown("上传一个或多个 `.srt` 文件，选择模式后即可一键翻译并下载。")

# 后端API的地址
API_URL = "http://127.0.0.1:8000"

# --- 批量上传功能 ---
uploaded_files = st.file_uploader(
    "请在此处上传您的 .srt 文件",
    type=['srt'],
    accept_multiple_files=True
)

# --- 选项配置 ---
col1, col2 = st.columns(2)
with col1:
    translate_mode = st.radio(
        "**选择翻译模式**",
        ('流式', '非流式'),
        index=0,
        help="流式：实时显示翻译进度，体验更佳。\n非流式：等待所有字幕翻译完成后一次性显示。"
    )
with col2:
    display_mode_options = {
        "仅显示译文": "only_translated",
        "原文在上，译文在下": "original_above_translated",
        "译文在上，原文在下": "translated_above_original"
    }
    selected_display_mode = st.radio(
        "**选择显示格式**",
        options=list(display_mode_options.keys())
    )
    display_mode = display_mode_options[selected_display_mode]

# --- 开始按钮 ---
start_button = st.button("🚀 开始翻译所有文件")

# --- 翻译逻辑 ---
if start_button and uploaded_files:
    st.markdown("---")
    st.subheader("整体翻译进度")
    progress_bar = st.progress(0)
    total_files = len(uploaded_files)

    # --- 循环处理每个上传的文件 ---
    for i, uploaded_file in enumerate(uploaded_files):
        # --- 优化: 为每个文件创建一个可折叠的容器 ---
        with st.expander(f"文件: **{uploaded_file.name}** ({i + 1}/{total_files})", expanded=True):
            
            # 为当前文件的状态和结果创建独立的占位符
            status_placeholder = st.empty()
            result_placeholder = st.empty()

            status_placeholder.info("准备翻译...")
            # --- 代码修正: 仅在初始创建时使用key，或完全由容器管理 ---
            result_placeholder.text_area("翻译预览", "等待翻译开始...", height=300, key=f"initial_text_area_{i}")

            files = {'file': (uploaded_file.name, uploaded_file.getvalue(), 'text/plain')}
            params = {'display_mode': display_mode}

            try:
                full_response_text = ""
                # --- 流式模式逻辑 ---
                if translate_mode == '流式':
                    endpoint = f"{API_URL}/translate-stream"
                    with requests.post(endpoint, files=files, params=params, stream=True) as response:
                        response.raise_for_status()
                        for chunk in response.iter_content(chunk_size=None, decode_unicode=True):
                            if chunk:
                                if chunk.startswith("[STATUS]"):
                                    status_placeholder.info(chunk.replace("[STATUS]", "").strip())
                                else:
                                    full_response_text += chunk
                                    # --- 代码修正: 更新时不再传递 key 参数 ---
                                    result_placeholder.text_area("翻译预览", full_response_text, height=300)
                                    auto_scroll()
                
                # --- 非流式模式逻辑 ---
                else:
                    endpoint = f"{API_URL}/translate"
                    status_placeholder.info("正在进行非流式翻译，请稍候...")
                    response = requests.post(endpoint, files=files, params=params)
                    response.raise_for_status()
                    result_data = response.json()
                    full_response_text = result_data.get("translated_srt", "未能获取翻译结果。")
                    # --- 代码修正: 更新时不再传递 key 参数 ---
                    result_placeholder.text_area("翻译预览", full_response_text, height=300)

                status_placeholder.success("翻译完成！")
                
                # --- 优化: 添加下载按钮 ---
                original_name, _ = os.path.splitext(uploaded_file.name)
                st.download_button(
                    label=f"📥 下载翻译后的文件 ({original_name}_translated.srt)",
                    data=full_response_text.encode('utf-8'),
                    file_name=f"{original_name}_translated.srt",
                    mime='text/plain',
                    key=f"download_{i}" # 为每个下载按钮设置唯一key
                )

            except requests.exceptions.RequestException as e:
                status_placeholder.error(f"连接后端失败: {e}")
            except Exception as e:
                status_placeholder.error(f"翻译过程中发生错误: {e}")
        
        # 更新整体进度条
        progress_bar.progress((i + 1) / total_files)

elif start_button and not uploaded_files:
    st.warning("请先上传至少一个 .srt 文件。")
