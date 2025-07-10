import streamlit as st
import requests
import os
import io
import zipfile
import uuid
import time
from typing import List, Dict, Any, Optional

# ------------------- 页面配置 -------------------
st.set_page_config(
    page_title="SRT 批量翻译器",
    page_icon="🎬",
    layout="wide"
)

# ------------------- 初始化/获取后端配置 -------------------
@st.cache_data(ttl=3600)
def get_api_config(api_url: str) -> Optional[Dict[str, Any]]:
    try:
        response = requests.get(f"{api_url}/config", timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        st.error(f"无法从API获取配置: {e}")
        return None

def init_session_state():
    if 'session_id' not in st.session_state:
        st.session_state.session_id = str(uuid.uuid4())[:8]
    if 'translation_results' not in st.session_state:
        st.session_state.translation_results = []
    if 'api_settings' not in st.session_state:
        st.session_state.api_settings = {'url': 'http://127.0.0.1:8000', 'timeout': 300}
    if 'api_config' not in st.session_state:
        st.session_state.api_config = get_api_config(st.session_state.api_settings['url'])

init_session_state()

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

# ------------------- 主界面 -------------------
st.title("🎬 SRT 批量字幕翻译器")
st.markdown("上传一个或多个 `.srt` 文件，配置选项后即可一键翻译。")

# ------------------- 侧边栏设置 -------------------
with st.sidebar:
    st.header("⚙️ API设置")
    api_url = st.text_input("API地址", value=st.session_state.api_settings['url'])
    api_timeout = st.number_input("请求超时(秒)", min_value=30, max_value=600, value=st.session_state.api_settings['timeout'])
    if st.button("💾 保存并刷新配置"):
        st.session_state.api_settings = {'url': api_url, 'timeout': api_timeout}
        st.cache_data.clear()
        st.session_state.api_config = get_api_config(st.session_state.api_settings['url'])
        st.success("设置已保存，配置已刷新！")
        st.rerun()

# ------------------- 主要配置区域 -------------------
uploaded_files = st.file_uploader(
    "请上传 `.srt` 文件",
    type=['srt'],
    accept_multiple_files=True,
    on_change=lambda: st.session_state.update(translation_results=[]),
    key="file_uploader_main"
)

if uploaded_files:
    st.markdown("---")
    st.subheader("📄 文件概览")
    total_subs, total_chars, total_time_est = 0, 0, 0
    # Simplified file stats logic for brevity
    for f in uploaded_files:
        content_str = f.getvalue().decode('utf-8-sig', errors='ignore')
        lines = content_str.strip().split('\n')
        subtitle_count = sum(1 for line in lines if line.strip().isdigit())
        total_subs += subtitle_count
        total_time_est += max(1, subtitle_count // 100)
    col1, col2, col3 = st.columns(3)
    col1.metric("总文件数", len(uploaded_files))
    col2.metric("总字幕条数", f"{total_subs:,}")
    col3.metric("总预估时间", f"~ {total_time_est} 分钟")

if not st.session_state.api_config:
    st.error("API配置加载失败，请检查侧边栏中的API地址并刷新配置。")
else:
    lang_map = st.session_state.api_config.get("supported_languages", {"Simplified Chinese": "简体中文"})
    quality_modes = st.session_state.api_config.get("quality_modes", ["标准", "高质量", "快速"])
    default_lang = st.session_state.api_config.get("default_target_language", "Simplified Chinese")
    supported_models = st.session_state.api_config.get("supported_models", ["gemini-1.5-flash", "gemini-1.5-pro"])
    lang_display_map = {v: k for k, v in lang_map.items()}

    st.markdown("### ⚙️ 翻译配置")
    col1, col2 = st.columns(2)
    with col1:
        target_language_display = st.selectbox("目标语言", options=list(lang_display_map.keys()), index=list(lang_display_map.values()).index(default_lang) if default_lang in lang_display_map.values() else 0)
        target_language = lang_display_map[target_language_display]
    with col2:
        quality_mode = st.selectbox("翻译质量", options=quality_modes, index=1)
    
    display_mode_options = {"仅显示译文": "only_translated", "原文在上，译文在下": "original_above_translated", "译文在上，原文在下": "translated_above_original"}
    selected_display_mode_label = st.radio("选择显示格式", list(display_mode_options.keys()))
    display_mode = display_mode_options[selected_display_mode_label]
    font_size = None
    if display_mode != "only_translated":
        font_size = st.number_input("**设置原文的字体大小 (可选)**", min_value=1, max_value=7, value=2)

    with st.expander("更多高级选项"):
        model_name = st.selectbox("选择AI模型", options=supported_models, index=0)
        split_long_lines = st.checkbox("自动分割过长的译文行", value=True)
        max_line_length = st.number_input("每行译文最大字符数", min_value=20, max_value=100, value=40, disabled=not split_long_lines)

    # ------------------- 翻译按钮和处理逻辑 -------------------
    if st.button("🚀 开始翻译所有文件", disabled=not uploaded_files):
        st.session_state.translation_results = []
        st.session_state.session_id = str(uuid.uuid4())[:8]
        file_data_list = [{'name': f.name, 'data': f.getvalue()} for f in uploaded_files]
        params = {
            'display_mode': display_mode, 'target_language': target_language, 'quality_mode': quality_mode,
            'split_long_lines': split_long_lines, 'max_line_length': max_line_length, 'model_name': model_name
        }
        if font_size is not None and display_mode != "only_translated":
            params['font_size'] = font_size

        progress_bar = st.progress(0, "准备开始...")
        status_text = st.empty()
        results_placeholder = st.empty()

        for i, file_data in enumerate(file_data_list):
            file_name = file_data['name']
            status_text.info(f"正在处理第 {i + 1}/{len(file_data_list)} 个文件: {file_name}")
            try:
                endpoint = f"{st.session_state.api_settings['url']}/translate-stream"
                files = {'file': (file_name, file_data['data'], 'text/plain')}
                translated_buffer = ""
                with requests.post(endpoint, files=files, params=params, stream=True, timeout=st.session_state.api_settings['timeout']) as response:
                    response.raise_for_status()
                    for chunk in response.iter_content(chunk_size=None, decode_unicode=True):
                        if chunk and not chunk.startswith("[STATUS]"):
                            translated_buffer += chunk
                st.session_state.translation_results.append({'name': file_name, 'content': translated_buffer, 'success': True, 'error': None})
            except Exception as e:
                st.session_state.translation_results.append({'name': file_name, 'content': None, 'success': False, 'error': f"处理文件时出错: {e}"})

            with results_placeholder.container():
                st.markdown("---")
                st.subheader("📝 翻译结果 (实时更新)")
                for j, result in enumerate(st.session_state.translation_results):
                    with st.expander(f"文件: **{result['name']}** ({'成功' if result['success'] else '失败'})", expanded=True):
                        if result['success']:
                            st.text_area(
                                "翻译预览", value=result['content'],
                                key=f"live_textarea_{st.session_state.session_id}_{i}_{j}",
                                height=300
                            )
                            st.download_button(
                                label="📥 下载此翻译文件", data=result['content'].encode('utf-8'),
                                file_name=f"{os.path.splitext(result['name'])[0]}_translated.srt", mime="text/plain",
                                key=f"live_download_single_{st.session_state.session_id}_{i}_{j}"
                            )
                        else:
                            st.error(f"❌ 翻译失败: {result['error']}")
            progress_bar.progress((i + 1) / len(file_data_list), f"已完成 {i + 1}/{len(file_data_list)}")

        status_text.success("🎉 所有文件处理完成！")
        time.sleep(1)
        status_text.empty()
        progress_bar.empty()
        # 清空占位符，以便下面的最终结果区可以完整地接管显示
        results_placeholder.empty()

# ------------------- 最终结果与总结区域 (重要修正) -------------------
# 这个区域现在负责持久化地显示所有结果和总结
if st.session_state.translation_results:
    st.markdown("---")
    st.subheader("📝 翻译结果")

    # [重要修正] 在这里也加入结果的循环显示，确保刷新后内容依然存在
    for i, result in enumerate(st.session_state.translation_results):
        with st.expander(f"文件: **{result['name']}** ({'成功' if result['success'] else '失败'})", expanded=True):
            if result['success']:
                st.text_area(
                    "翻译预览",
                    value=result['content'],
                    # 这里的 key 不需要 live_ 前缀，也不需要外层循环的 i，因为这个代码块的执行是独立的
                    key=f"final_textarea_{st.session_state.session_id}_{i}",
                    height=300
                )
                st.download_button(
                    label="📥 下载此翻译文件",
                    data=result['content'].encode('utf-8'),
                    file_name=f"{os.path.splitext(result['name'])[0]}_translated.srt",
                    mime="text/plain",
                    key=f"final_download_single_{st.session_state.session_id}_{i}"
                )
            else:
                st.error(f"❌ 翻译失败: {result['error']}")

    st.markdown("---")
    st.subheader("📊 翻译总结与批量下载")
    successful_results = [r for r in st.session_state.translation_results if r['success']]
    failed_results = [r for r in st.session_state.translation_results if not r['success']]
    col1, col2 = st.columns(2)
    col1.metric("成功文件数", len(successful_results))
    col2.metric("失败文件数", len(failed_results))
    if successful_results:
        try:
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED, False) as zf:
                for res in successful_results:
                    zf.writestr(f"{os.path.splitext(res['name'])[0]}_translated.srt", res['content'].encode('utf-8'))
            zip_buffer.seek(0)
            st.download_button(
                label=f"📥 下载全部成功结果 ({len(successful_results)} 个文件)",
                data=zip_buffer,
                file_name=f"translated_srt_files_{st.session_state.session_id}.zip",
                mime="application/zip",
                key=f"download_all_{st.session_state.session_id}"
            )
        except Exception as e:
            st.error(f"创建 ZIP 文件时出错: {e}")
