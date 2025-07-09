import streamlit as st
import requests
import os
import io
import zipfile
import uuid

# ------------------- 页面配置 -------------------
st.set_page_config(
    page_title="SRT 批量翻译器",
    page_icon="🎬",
    layout="wide"
)

# ------------------- 初始化状态 -------------------
if 'translation_results' not in st.session_state:
    st.session_state.translation_results = []
if 'session_id' not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())[:8]

# ------------------- 样式 -------------------
st.markdown("""
<style>
div[data-testid="stTextArea"] > div > div > textarea {
    height: 300px !important;
    font-family: 'Courier New', monospace !important;
    font-size: 12px !important;
    line-height: 1.4 !important;
}
</style>
""", unsafe_allow_html=True)

# ------------------- 页面结构 -------------------
st.title("🎬 SRT 批量字幕翻译器")
st.markdown("上传一个或多个 `.srt` 文件，选择模式后翻译并下载。")

API_URL = "http://127.0.0.1:8000"

uploaded_files = st.file_uploader(
    "请上传 `.srt` 文件",
    type=['srt'],
    accept_multiple_files=True,
    on_change=lambda: st.session_state.update(translation_results=[]),
    key="file_uploader_main"  # ✅ 避免重复组件报错
)

col1, col2 = st.columns(2)
with col1:
    translate_mode = st.radio("选择翻译模式", ('流式', '非流式'), index=0)
with col2:
    display_mode_options = {
        "仅显示译文": "only_translated",
        "原文在上，译文在下": "original_above_translated",
        "译文在上，原文在下": "translated_above_original"
    }
    selected_display_mode_label = st.radio("选择显示格式", list(display_mode_options.keys()))
    display_mode = display_mode_options[selected_display_mode_label]

# ------------------- 翻译按钮 -------------------
if st.button("🚀 开始翻译所有文件", disabled=not uploaded_files):
    st.session_state.translation_results = []
    st.session_state.session_id = str(uuid.uuid4())[:8]

    st.markdown("---")
    st.subheader("翻译进度")

    file_data_list = [{'name': f.name, 'data': f.getvalue()} for f in uploaded_files]

    for i, file_data in enumerate(file_data_list):
        file_name = file_data['name']
        file_bytes = file_data['data']
        full_response_text = ""

        with st.expander(f"文件: **{file_name}** ({i + 1}/{len(file_data_list)})", expanded=True):
            status_placeholder = st.empty()
            result_container = st.empty()
            download_placeholder = st.empty()

            status_placeholder.info("准备翻译...")

            files = {'file': (file_name, file_bytes, 'text/plain')}
            params = {'display_mode': display_mode}

            try:
                if translate_mode == '流式':
                    endpoint = f"{API_URL}/translate-stream"
                    status_placeholder.info("正在建立流式连接...")

                    translated_buffer = ""
                    with requests.post(endpoint, files=files, params=params, stream=True) as response:
                        response.raise_for_status()
                        for chunk in response.iter_content(chunk_size=None, decode_unicode=True):
                            if chunk:
                                if chunk.startswith("[STATUS]"):
                                    status_msg = chunk.replace("[STATUS]", "").strip()
                                    status_placeholder.info(status_msg)
                                else:
                                    translated_buffer += chunk
                                    result_container.markdown(f"```\n{translated_buffer[-3000:]}\n```")

                    full_response_text = translated_buffer
                    result_container.text_area(
                        "翻译预览",
                        value=full_response_text,
                        key=f"textarea_{st.session_state.session_id}_{i}",
                        height=300
                    )

                else:
                    endpoint = f"{API_URL}/translate"
                    status_placeholder.info("正在进行非流式翻译，请稍候...")

                    response = requests.post(endpoint, files=files, params=params)
                    response.raise_for_status()
                    result_data = response.json()
                    full_response_text = result_data.get(
                        "translated_srt",
                        f"未能获取 '{file_name}' 的翻译结果。"
                    )
                    result_container.text_area(
                        "翻译预览",
                        value=full_response_text,
                        key=f"textarea_{st.session_state.session_id}_{i}",
                        height=300
                    )

                status_placeholder.success("✅ 翻译完成！")

                # ✅ 单个文件下载按钮
                download_placeholder.download_button(
                    label="📥 下载此翻译文件",
                    data=full_response_text.encode('utf-8'),
                    file_name=f"{os.path.splitext(file_name)[0]}_translated.srt",
                    mime="text/plain",
                    key=f"download_{st.session_state.session_id}_{i}"
                )

            except requests.exceptions.RequestException as e:
                full_response_text = f"文件 '{file_name}' 翻译失败: 网络请求错误: {str(e)}"
                status_placeholder.error(f"❌ 网络请求错误: {str(e)}")
            except Exception as e:
                full_response_text = f"文件 '{file_name}' 翻译失败: 未知错误: {str(e)}"
                status_placeholder.error(f"❌ 未知错误: {str(e)}")

            st.session_state.translation_results.append({
                'name': file_name,
                'content': full_response_text
            })

    st.success("🎉 所有文件翻译完成！")

# ------------------- 批量下载 -------------------
if st.session_state.translation_results:
    successful_results = [
        result for result in st.session_state.translation_results
        if result.get('content') and not result['content'].startswith("文件")
    ]

    if len(successful_results) >= 1:
        st.markdown("---")
        st.subheader("📦 批量下载成功文件")

        try:
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED, False) as zip_file:
                for result in successful_results:
                    original_name, _ = os.path.splitext(result['name'])
                    file_name_in_zip = f"{original_name}_translated.srt"
                    zip_file.writestr(file_name_in_zip, result['content'].encode('utf-8'))

            st.download_button(
                label=f"📥 下载全部成功结果（{len(successful_results)} 个文件）",
                data=zip_buffer.getvalue(),
                file_name="translated_srt_files.zip",
                mime="application/zip",
                key=f"download_all_{st.session_state.session_id}"
            )
        except Exception as e:
            st.error(f"创建 ZIP 文件时出错: {str(e)}")

# ------------------- 使用说明 -------------------
with st.expander("📖 使用说明"):
    st.markdown("""
    ### 功能说明
    - 支持 `.srt` 字幕文件批量上传和翻译
    - 流式模式实时显示翻译进度
    - 可切换显示格式（只译文 / 原译对照）
    - 翻译完成后可单独或打包下载

    ### 注意事项
    - 确保本地或远程 API 服务已启动（默认地址: `http://127.0.0.1:8000`）
    - 翻译失败文件不会被打包下载
    """)
