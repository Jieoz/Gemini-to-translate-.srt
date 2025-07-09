import streamlit as st
import requests
import time
import os
import io
import zipfile
import uuid
import html

# --- 页面配置 ---
st.set_page_config(
    page_title="SRT 批量翻译器",
    page_icon="🎬",
    layout="wide"
)

# --- 初始化会话状态 ---
if 'run_translation' not in st.session_state:
    st.session_state.run_translation = False
if 'translation_results' not in st.session_state:
    st.session_state.translation_results = []
if 'uploaded_file_data' not in st.session_state:
    st.session_state.uploaded_file_data = []
if 'session_id' not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())[:8]  # 生成唯一会话ID

# --- 自定义CSS样式 ---
st.markdown("""
<style>
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
    .stTextArea>div>div>textarea { 
        border-radius: 10px; 
    }
    .streamlit-expanderHeader { 
        font-size: 1.1em; 
        font-weight: bold; 
    }
    div[data-testid="stExpander"] { 
        padding-bottom: 5px !important;
        margin-bottom: 5px !important;
    }
    .translation-container {
        height: 250px; 
        overflow-y: auto; 
        border: 1px solid #ddd; 
        border-radius: 5px; 
        padding: 10px; 
        background-color: #f8f9fa;
        font-family: 'Courier New', monospace;
        font-size: 12px;
        white-space: pre-wrap;
        word-wrap: break-word;
        line-height: 1.4;
    }
    .success-message {
        padding: 10px;
        background-color: #d4edda;
        border: 1px solid #c3e6cb;
        border-radius: 5px;
        color: #155724;
        margin: 10px 0;
    }
    .error-message {
        padding: 10px;
        background-color: #f8d7da;
        border: 1px solid #f5c6cb;
        border-radius: 5px;
        color: #721c24;
        margin: 10px 0;
    }
</style>
""", unsafe_allow_html=True)

def auto_scroll():
    """注入JS代码以滚动自定义div内容到底部"""
    st.components.v1.html(
        """
        <script>
            setTimeout(function() {
                // 滚动自定义的div容器到底部
                var scrollDivs = window.parent.document.querySelectorAll('.translation-container');
                if (scrollDivs.length > 0) {
                    var lastDiv = scrollDivs[scrollDivs.length - 1];
                    lastDiv.scrollTop = lastDiv.scrollHeight;
                }
            }, 50);
        </script>
        """,
        height=0,
        width=0
    )

# --- 主界面 ---
st.title("🎬 SRT 批量字幕翻译器")
st.markdown("上传一个或多个 `.srt` 文件，选择模式后即可一键翻译并下载。")

API_URL = "http://127.0.0.1:8000"

# --- 批量上传功能 ---
def on_file_change():
    """文件上传变更时重置状态"""
    st.session_state.run_translation = False
    st.session_state.translation_results = []
    st.session_state.uploaded_file_data = []
    st.session_state.session_id = str(uuid.uuid4())[:8]  # 生成新的会话ID

uploaded_files = st.file_uploader(
    "请在此处上传您的 .srt 文件",
    type=['srt'],
    accept_multiple_files=True,
    on_change=on_file_change
)

# --- 选项配置 ---
col1, col2 = st.columns(2)
with col1:
    translate_mode = st.radio(
        "**选择翻译模式**", ('流式', '非流式'), index=0,
        help="流式：实时显示每个文件的翻译状态和进度。\n非流式：等待所有文件完成后一次性显示结果。"
    )
with col2:
    display_mode_options = {
        "仅显示译文": "only_translated",
        "原文在上，译文在下": "original_above_translated",
        "译文在上，原文在下": "translated_above_original"
    }
    selected_display_mode_label = st.radio(
        "**选择显示格式**", options=list(display_mode_options.keys())
    )
    display_mode = display_mode_options[selected_display_mode_label]

# --- 开始按钮 ---
if st.button("🚀 开始翻译所有文件", disabled=not uploaded_files):
    st.session_state.run_translation = True
    # 保存文件信息以在 rerun 后使用
    st.session_state.uploaded_file_data = [
        {'name': f.name, 'data': f.getvalue()} for f in uploaded_files
    ]
    st.session_state.translation_results = []  # 清空旧的结果
    st.session_state.session_id = str(uuid.uuid4())[:8]  # 生成新的会话ID
    st.rerun()  # 重新运行脚本以进入翻译逻辑

# --- 核心翻译逻辑 ---
if st.session_state.run_translation and st.session_state.uploaded_file_data:
    st.markdown("---")
    st.subheader("翻译进度")
    
    results_container = st.container()
    
    # 循环处理每个上传的文件
    for i, file_data in enumerate(st.session_state.uploaded_file_data):
        file_name = file_data['name']
        file_bytes = file_data['data']

        with results_container:
            with st.expander(
                f"文件: **{file_name}** ({i + 1}/{len(st.session_state.uploaded_file_data)})", 
                expanded=True
            ):
                # 使用会话ID和文件索引生成唯一的key
                status_key = f"status_{st.session_state.session_id}_{i}"
                result_key = f"result_{st.session_state.session_id}_{i}"
                download_key = f"download_{st.session_state.session_id}_{i}"
                
                status_placeholder = st.empty()
                result_placeholder = st.empty()
                download_placeholder = st.empty()

                status_placeholder.info("准备翻译...")
                
                files = {'file': (file_name, file_bytes, 'text/plain')}
                params = {'display_mode': display_mode}
                full_response_text = ""

                try:
                    if translate_mode == '流式':
                        endpoint = f"{API_URL}/translate-stream"
                        status_placeholder.info("正在建立流式连接...")
                        
                        # 创建预览标题
                        result_placeholder.markdown("**翻译预览:**")
                        scroll_container = st.empty()
                        
                        with requests.post(endpoint, files=files, params=params, stream=True) as response:
                            response.raise_for_status()
                            for chunk in response.iter_content(chunk_size=None, decode_unicode=True):
                                if chunk:
                                    if chunk.startswith("[STATUS]"):
                                        status_msg = chunk.replace("[STATUS]", "").strip()
                                        status_placeholder.info(status_msg)
                                    else:
                                        full_response_text += chunk
                                        # 修复：清理响应文本，移除多余的空白行
                                        cleaned_text = '\n'.join(line for line in full_response_text.split('\n') if line.strip() or not line)
                                        # 转义HTML内容并使用CSS类
                                        escaped_text = html.escape(cleaned_text)
                                        scroll_container.markdown(
                                            f'<div class="translation-container">{escaped_text}</div>',
                                            unsafe_allow_html=True
                                        )
                    else:  # 非流式
                        endpoint = f"{API_URL}/translate"
                        status_placeholder.info("正在进行非流式翻译，请稍候...")
                        
                        response = requests.post(endpoint, files=files, params=params)
                        response.raise_for_status()
                        result_data = response.json()
                        full_response_text = result_data.get(
                            "translated_srt", 
                            f"未能获取 '{file_name}' 的翻译结果。"
                        )
                        # 非流式也使用相同的显示方式保持一致
                        result_placeholder.markdown("**翻译预览:**")
                        escaped_text = html.escape(full_response_text)
                        result_placeholder.markdown(
                            f'<div class="translation-container">{escaped_text}</div>',
                            unsafe_allow_html=True
                        )

                    status_placeholder.success("✅ 翻译完成！")

                except requests.exceptions.RequestException as e:
                    error_msg = f"网络请求错误: {str(e)}"
                    full_response_text = f"文件 '{file_name}' 翻译失败: {error_msg}"
                    status_placeholder.error(f"❌ {error_msg}")
                    result_placeholder.error(full_response_text)
                except Exception as e:
                    error_msg = f"未知错误: {str(e)}"
                    full_response_text = f"文件 '{file_name}' 翻译失败: {error_msg}"
                    status_placeholder.error(f"❌ {error_msg}")
                    result_placeholder.error(full_response_text)
                
                # 将最终结果存入会话状态
                st.session_state.translation_results.append({
                    'name': file_name,
                    'content': full_response_text
                })

                # 修复：翻译完成后立即显示下载按钮，使用force_update
                original_name, _ = os.path.splitext(file_name)
                download_filename = f"{original_name}_translated.srt"
                
                if full_response_text and not full_response_text.startswith("文件"):
                    # 使用容器来确保下载按钮立即显示
                    with download_placeholder.container():
                        st.download_button(
                            label=f"📥 下载 ({download_filename})",
                            data=full_response_text.encode('utf-8'),
                            file_name=download_filename,
                            mime='text/plain',
                            key=download_key
                        )
                else:
                    download_placeholder.error("翻译失败，无法下载")
                
                # 修复：强制刷新UI以立即显示下载按钮
                time.sleep(0.1)  # 短暂延迟确保UI更新

    # 所有文件处理完毕后，将运行标志设为False
    st.session_state.run_translation = False
    
    # 显示完成消息
    st.success("🎉 所有文件翻译完成！")

# --- "下载全部"按钮的显示逻辑 ---
if st.session_state.translation_results:
    # 过滤掉失败的翻译结果
    successful_results = [
        result for result in st.session_state.translation_results 
        if result['content'] and not result['content'].startswith("文件")
    ]
    
    if len(successful_results) > 1:
        st.markdown("---")
        st.subheader("批量下载")
        
        try:
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED, False) as zip_file:
                for result in successful_results:
                    original_name, _ = os.path.splitext(result['name'])
                    file_name_in_zip = f"{original_name}_translated.srt"
                    zip_file.writestr(file_name_in_zip, result['content'].encode('utf-8'))
            
            st.download_button(
                label=f"📥 下载全部成功的结果 ({len(successful_results)} 个文件)",
                data=zip_buffer.getvalue(),
                file_name="translated_srt_files.zip",
                mime="application/zip",
                key=f"download_all_{st.session_state.session_id}"
            )
            
            # 显示统计信息
            total_files = len(st.session_state.translation_results)
            failed_files = total_files - len(successful_results)
            
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("总文件数", total_files)
            with col2:
                st.metric("成功翻译", len(successful_results))
            with col3:
                st.metric("失败文件", failed_files)
                
        except Exception as e:
            st.error(f"创建ZIP文件时出错: {str(e)}")
    
    elif len(successful_results) == 1:
        st.info("只有一个文件成功翻译，请使用上方的单个文件下载按钮。")
    
    elif len(successful_results) == 0:
        st.warning("没有成功翻译的文件可供下载。")

# --- 使用说明 ---
with st.expander("📖 使用说明"):
    st.markdown("""
    ### 功能说明
    - **流式模式**: 实时显示翻译进度和结果，适合查看翻译过程
    - **非流式模式**: 等待完整翻译完成后显示结果，适合批量处理
    
    ### 显示格式
    - **仅显示译文**: 只显示翻译后的文本
    - **原文在上，译文在下**: 每个字幕条目显示原文和译文
    - **译文在上，原文在下**: 每个字幕条目显示译文和原文
    
    ### 注意事项
    - 确保后端API服务正在运行 (http://127.0.0.1:8000)
    - 支持批量上传多个.srt文件
    - 翻译失败的文件不会包含在批量下载中
    - 每次重新上传文件会清空之前的结果
    """)
