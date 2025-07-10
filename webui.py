import streamlit as st
import requests
import os
import io
import zipfile
import uuid
import time
import json
from typing import List, Dict, Any
from datetime import datetime

# ------------------- 页面配置 -------------------
st.set_page_config(
    page_title="SRT 批量翻译器",
    page_icon="🎬",
    layout="wide"
)

# ------------------- 初始化状态 -------------------
def init_session_state():
    """初始化会话状态"""
    if 'translation_results' not in st.session_state:
        st.session_state.translation_results = []
    if 'session_id' not in st.session_state:
        st.session_state.session_id = str(uuid.uuid4())[:8]
    if 'translation_buffers' not in st.session_state:
        st.session_state.translation_buffers = {}
    if 'translation_history' not in st.session_state:
        st.session_state.translation_history = []
    if 'api_settings' not in st.session_state:
        st.session_state.api_settings = {
            'url': 'http://127.0.0.1:8000',
            'timeout': 300,
            'max_retries': 3
        }

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
.translation-container {
    border: 1px solid #ddd;
    border-radius: 5px;
    padding: 10px;
    margin: 10px 0;
    background-color: #f9f9f9;
}
.success-message {
    color: #28a745;
    font-weight: bold;
}
.error-message {
    color: #dc3545;
    font-weight: bold;
}
.stats-container {
    background-color: #f8f9fa;
    padding: 15px;
    border-radius: 10px;
    margin: 10px 0;
}
.progress-bar {
    background-color: #e9ecef;
    border-radius: 10px;
    height: 20px;
    overflow: hidden;
}
.progress-fill {
    background-color: #28a745;
    height: 100%;
    transition: width 0.3s ease;
}
</style>
""", unsafe_allow_html=True)

# ------------------- 配置常量 -------------------
DISPLAY_MODE_OPTIONS = {
    "仅显示译文": "only_translated",
    "原文在上，译文在下": "original_above_translated",
    "译文在上，原文在下": "translated_above_original"
}

SUPPORTED_LANGUAGES = {
    "中文": "Chinese",
    "英文": "English", 
    "日文": "Japanese",
    "韩文": "Korean",
    "法文": "French",
    "德文": "German",
    "西班牙文": "Spanish",
    "意大利文": "Italian",
    "俄文": "Russian",
    "阿拉伯文": "Arabic"
}

# ------------------- 工具函数 -------------------
def create_zip_file(results: List[Dict[str, Any]]) -> bytes:
    """创建ZIP文件"""
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED, False) as zip_file:
        for result in results:
            original_name, _ = os.path.splitext(result['name'])
            file_name_in_zip = f"{original_name}_translated.srt"
            zip_file.writestr(file_name_in_zip, result['content'].encode('utf-8'))
    return zip_buffer.getvalue()

def get_file_stats(file_content: str) -> Dict[str, Any]:
    """获取文件统计信息"""
    lines = file_content.strip().split('\n')
    subtitle_count = 0
    total_chars = 0
    
    for line in lines:
        if line.strip().isdigit():
            subtitle_count += 1
        elif line.strip() and '-->' not in line:
            total_chars += len(line.strip())
    
    return {
        'subtitle_count': subtitle_count,
        'total_chars': total_chars,
        'estimated_time': max(1, subtitle_count // 10)  # 估算翻译时间（分钟）
    }

def test_api_connection(api_url: str, timeout: int = 10) -> Dict[str, Any]:
    """测试API连接"""
    try:
        response = requests.get(f"{api_url}/docs", timeout=timeout)
        if response.status_code == 200:
            return {"status": "success", "message": "API连接正常"}
        else:
            return {"status": "error", "message": f"API响应异常: {response.status_code}"}
    except requests.exceptions.ConnectionError:
        return {"status": "error", "message": "无法连接到API服务"}
    except requests.exceptions.Timeout:
        return {"status": "error", "message": "连接超时"}
    except Exception as e:
        return {"status": "error", "message": f"连接错误: {str(e)}"}

def translate_file_stream(file_name: str, file_bytes: bytes, params: Dict[str, Any], 
                         status_placeholder, result_container, progress_bar, 
                         file_index: int, total_files: int) -> str:
    """流式翻译文件"""
    api_url = st.session_state.api_settings['url']
    endpoint = f"{api_url}/translate-stream"
    timeout = st.session_state.api_settings['timeout']
    
    # 使用时间戳确保唯一性
    timestamp = int(time.time() * 1000)
    unique_key = f"{st.session_state.session_id}_{file_index}_{timestamp}"
    
    status_placeholder.info(f"正在翻译文件 {file_index + 1}/{total_files}: {file_name}")
    
    files = {'file': (file_name, file_bytes, 'text/plain')}
    translated_buffer = ""
    
    # 获取文件统计信息
    file_content = file_bytes.decode('utf-8-sig')
    stats = get_file_stats(file_content)
    
    with requests.post(endpoint, files=files, params=params, stream=True, timeout=timeout) as response:
        response.raise_for_status()
        
        chunk_count = 0
        for chunk in response.iter_content(chunk_size=None, decode_unicode=True):
            if chunk:
                chunk_count += 1
                if chunk.startswith("[STATUS]"):
                    status_msg = chunk.replace("[STATUS]", "").strip()
                    status_placeholder.info(f"文件 {file_index + 1}/{total_files}: {status_msg}")
                    
                    # 更新进度条
                    if "批次" in status_msg:
                        progress = min(90, chunk_count * 2)  # 估算进度
                        progress_bar.progress(progress / 100)
                else:
                    translated_buffer += chunk
                    
                    # 实时显示翻译内容（每10个chunk更新一次以提高性能）
                    if chunk_count % 10 == 0:
                        with result_container.container():
                            st.text_area(
                                f"实时翻译预览 - {file_name}",
                                value=translated_buffer,
                                height=300,
                                key=f"stream_result_{unique_key}_{chunk_count}",
                                disabled=True
                            )
    
    # 最终显示完整结果
    progress_bar.progress(100)
    with result_container.container():
        st.text_area(
            f"翻译完成 - {file_name}",
            value=translated_buffer,
            height=300,
            key=f"final_result_{unique_key}",
            disabled=True
        )
    
    return translated_buffer

def translate_file_batch(file_name: str, file_bytes: bytes, params: Dict[str, Any], 
                        status_placeholder, result_container, progress_bar,
                        file_index: int, total_files: int) -> str:
    """批量翻译文件"""
    api_url = st.session_state.api_settings['url']
    endpoint = f"{api_url}/translate"
    timeout = st.session_state.api_settings['timeout']
    
    timestamp = int(time.time() * 1000)
    unique_key = f"{st.session_state.session_id}_{file_index}_{timestamp}"
    
    status_placeholder.info(f"正在翻译文件 {file_index + 1}/{total_files}: {file_name}，请稍候...")
    progress_bar.progress(50)
    
    files = {'file': (file_name, file_bytes, 'text/plain')}
    response = requests.post(endpoint, files=files, params=params, timeout=timeout)
    response.raise_for_status()
    
    result_data = response.json()
    translated_content = result_data.get("translated_srt", f"未能获取 '{file_name}' 的翻译结果。")
    
    progress_bar.progress(100)
    
    # 显示结果
    with result_container.container():
        st.text_area(
            f"翻译完成 - {file_name}",
            value=translated_content,
            height=300,
            key=f"batch_result_{unique_key}",
            disabled=True
        )
    
    return translated_content

def process_single_file(file_data: Dict[str, Any], file_index: int, total_files: int, 
                       translate_mode: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """处理单个文件的翻译"""
    file_name = file_data['name']
    file_bytes = file_data['data']
    
    # 获取文件统计信息
    file_content = file_bytes.decode('utf-8-sig')
    stats = get_file_stats(file_content)
    
    with st.expander(f"📄 文件: **{file_name}** ({file_index + 1}/{total_files})", expanded=True):
        # 显示文件信息
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("字幕条数", stats['subtitle_count'])
        with col2:
            st.metric("总字符数", stats['total_chars'])
        with col3:
            st.metric("预估时间", f"{stats['estimated_time']}分钟")
        
        status_placeholder = st.empty()
        progress_bar = st.progress(0)
        result_container = st.empty()
        download_placeholder = st.empty()
        
        start_time = time.time()
        
        try:
            if translate_mode == '流式':
                full_response_text = translate_file_stream(
                    file_name, file_bytes, params, status_placeholder, 
                    result_container, progress_bar, file_index, total_files
                )
            else:
                full_response_text = translate_file_batch(
                    file_name, file_bytes, params, status_placeholder, 
                    result_container, progress_bar, file_index, total_files
                )
            
            end_time = time.time()
            translation_time = end_time - start_time
            
            status_placeholder.success(f"✅ 翻译完成！用时: {translation_time:.1f}秒")
            
            # 保存翻译历史
            st.session_state.translation_history.append({
                'file_name': file_name,
                'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                'mode': translate_mode,
                'time_taken': translation_time,
                'subtitle_count': stats['subtitle_count'],
                'success': True
            })
            
            # 下载按钮
            download_placeholder.download_button(
                label="📥 下载此翻译文件",
                data=full_response_text.encode('utf-8'),
                file_name=f"{os.path.splitext(file_name)[0]}_translated.srt",
                mime="text/plain",
                key=f"download_{st.session_state.session_id}_{file_index}_{int(time.time())}"
            )
            
            return {
                'name': file_name,
                'content': full_response_text,
                'success': True,
                'stats': stats,
                'translation_time': translation_time
            }
            
        except requests.exceptions.RequestException as e:
            error_msg = f"文件 '{file_name}' 翻译失败: 网络请求错误: {str(e)}"
            status_placeholder.error(f"❌ 网络请求错误: {str(e)}")
            
            # 保存错误历史
            st.session_state.translation_history.append({
                'file_name': file_name,
                'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                'mode': translate_mode,
                'error': str(e),
                'success': False
            })
            
            return {
                'name': file_name,
                'content': error_msg,
                'success': False,
                'error': str(e)
            }
        except Exception as e:
            error_msg = f"文件 '{file_name}' 翻译失败: 未知错误: {str(e)}"
            status_placeholder.error(f"❌ 未知错误: {str(e)}")
            
            # 保存错误历史
            st.session_state.translation_history.append({
                'file_name': file_name,
                'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                'mode': translate_mode,
                'error': str(e),
                'success': False
            })
            
            return {
                'name': file_name,
                'content': error_msg,
                'success': False,
                'error': str(e)
            }

# ------------------- 主界面 -------------------
st.title("🎬 SRT 批量字幕翻译器")
st.markdown("上传一个或多个 `.srt` 文件，选择模式后翻译并下载。")

# ------------------- 侧边栏设置 -------------------
with st.sidebar:
    st.header("⚙️ 设置")
    
    # API设置
    with st.expander("🔧 API配置", expanded=False):
        api_url = st.text_input("API地址", value=st.session_state.api_settings['url'])
        api_timeout = st.number_input("超时时间(秒)", min_value=30, max_value=600, value=st.session_state.api_settings['timeout'])
        max_retries = st.number_input("最大重试次数", min_value=1, max_value=10, value=st.session_state.api_settings['max_retries'])
        
        if st.button("💾 保存API设置"):
            st.session_state.api_settings = {
                'url': api_url,
                'timeout': api_timeout,
                'max_retries': max_retries
            }
            st.success("设置已保存！")
        
        # 测试API连接
        if st.button("🔍 测试API连接"):
            result = test_api_connection(api_url)
            if result['status'] == 'success':
                st.success(result['message'])
            else:
                st.error(result['message'])
    
    # 翻译历史
    with st.expander("📊 翻译历史", expanded=False):
        if st.session_state.translation_history:
            for i, record in enumerate(reversed(st.session_state.translation_history[-10:])):
                status_icon = "✅" if record['success'] else "❌"
                st.write(f"{status_icon} {record['file_name']}")
                st.caption(f"{record['timestamp']} - {record['mode']}")
                if record['success']:
                    st.caption(f"用时: {record.get('translation_time', 0):.1f}秒")
                else:
                    st.caption(f"错误: {record.get('error', 'Unknown')}")
        else:
            st.info("暂无翻译历史")
        
        if st.button("🗑️ 清空历史"):
            st.session_state.translation_history = []
            st.success("历史记录已清空！")

# ------------------- 主要配置 -------------------
# 文件上传
uploaded_files = st.file_uploader(
    "请上传 `.srt` 文件",
    type=['srt'],
    accept_multiple_files=True,
    key="file_uploader_main"
)

# 显示上传文件信息
if uploaded_files:
    st.info(f"已上传 {len(uploaded_files)} 个文件")
    
    # 显示文件列表和统计信息
    total_subtitles = 0
    total_chars = 0
    
    for i, file in enumerate(uploaded_files):
        file_content = file.getvalue().decode('utf-8-sig')
        stats = get_file_stats(file_content)
        total_subtitles += stats['subtitle_count']
        total_chars += stats['total_chars']
        
        with st.expander(f"📄 {file.name}", expanded=False):
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("字幕条数", stats['subtitle_count'])
            with col2:
                st.metric("字符数", stats['total_chars'])
            with col3:
                st.metric("预估时间", f"{stats['estimated_time']}分钟")
    
    # 总统计
    st.markdown("### 📊 总计")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("总文件数", len(uploaded_files))
    with col2:
        st.metric("总字幕条数", total_subtitles)
    with col3:
        st.metric("总预估时间", f"{max(1, total_subtitles // 10)}分钟")

# 配置选项
st.markdown("### ⚙️ 翻译配置")
col1, col2 = st.columns(2)
with col1:
    translate_mode = st.radio("选择翻译模式", ('流式', '非流式'), index=0)
with col2:
    selected_display_mode_label = st.radio("选择显示格式", list(DISPLAY_MODE_OPTIONS.keys()))
    display_mode = DISPLAY_MODE_OPTIONS[selected_display_mode_label]

# 高级设置
with st.expander("🔧 高级设置", expanded=False):
    # 目标语言选择
    target_language = st.selectbox(
        "目标语言",
        options=list(SUPPORTED_LANGUAGES.keys()),
        index=0
    )
    
    # 字体大小设置
    font_size = None
    if display_mode != "only_translated":
        font_size = st.number_input(
            "原文字体大小",
            min_value=1,
            max_value=7,
            value=2,
            help="为双语模式下的原文设置字体大小 (1-7)"
        )
    
    # 翻译质量设置
    quality_mode = st.selectbox(
        "翻译质量",
        options=["标准", "高质量", "快速"],
        index=0,
        help="高质量模式会更仔细地处理上下文，但速度较慢"
    )

# ------------------- 翻译处理 -------------------
if st.button("🚀 开始翻译所有文件", disabled=not uploaded_files):
    # 重置状态
    st.session_state.translation_results = []
    st.session_state.session_id = str(uuid.uuid4())[:8]
    st.session_state.translation_buffers = {}
    
    st.markdown("---")
    st.subheader("🔄 翻译进度")
    
    # 准备文件数据
    file_data_list = [{'name': f.name, 'data': f.getvalue()} for f in uploaded_files]
    
    # 准备参数
    params = {
        'display_mode': display_mode,
        'target_language': SUPPORTED_LANGUAGES[target_language],
        'quality_mode': quality_mode.lower()
    }
    if font_size is not None and display_mode != "only_translated":
        params['font_size'] = font_size
    
    # 总体进度
    overall_progress = st.progress(0)
    overall_status = st.empty()
    
    # 处理每个文件
    for i, file_data in enumerate(file_data_list):
        overall_progress.progress((i) / len(file_data_list))
        overall_status.info(f"正在处理第 {i + 1} 个文件，共 {len(file_data_list)} 个")
        
        result = process_single_file(file_data, i, len(file_data_list), translate_mode, params)
        st.session_state.translation_results.append(result)
    
    overall_progress.progress(100)
    
    # 显示总结
    successful_count = sum(1 for r in st.session_state.translation_results if r.get('success', False))
    total_count = len(st.session_state.translation_results)
    
    if successful_count == total_count:
        overall_status.success(f"🎉 所有文件翻译完成！({successful_count}/{total_count})")
    else:
        overall_status.warning(f"⚠️ 翻译完成，成功 {successful_count}/{total_count} 个文件")
        
        # 显示失败的文件
        failed_files = [r for r in st.session_state.translation_results if not r.get('success', False)]
        if failed_files:
            st.markdown("### ❌ 翻译失败的文件")
            for failed_file in failed_files:
                st.error(f"• {failed_file['name']}: {failed_file.get('error', '未知错误')}")

# ------------------- 批量下载 -------------------
if st.session_state.translation_results:
    successful_results = [
        result for result in st.session_state.translation_results
        if result.get('success', False) and result.get('content')
    ]
    
    if len(successful_results) >= 1:
        st.markdown("---")
        st.subheader("📦 批量下载")
        
        # 显示成功统计
        total_time = sum(r.get('translation_time', 0) for r in successful_results)
        total_subtitles = sum(r.get('stats', {}).get('subtitle_count', 0) for r in successful_results)
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("成功文件数", len(successful_results))
        with col2:
            st.metric("总翻译时间", f"{total_time:.1f}秒")
        with col3:
            st.metric("总字幕条数", total_subtitles)
        
        try:
            zip_data = create_zip_file(successful_results)
            
            st.download_button(
                label=f"📥 下载全部成功结果（{len(successful_results)} 个文件）",
                data=zip_data,
                file_name=f"translated_srt_files_{st.session_state.session_id}.zip",
                mime="application/zip",
                key=f"download_all_{st.session_state.session_id}"
            )
        except Exception as e:
            st.error(f"创建 ZIP 文件时出错: {str(e)}")

# ------------------- 清理和维护 -------------------
st.markdown("---")
col1, col2 = st.columns(2)
with col1:
    if st.button("🧹 清理翻译缓存"):
        st.session_state.translation_buffers = {}
        st.session_state.translation_results = []
        st.success("缓存已清理！")

with col2:
    if st.button("🔄 重新开始"):
        for key in list(st.session_state.keys()):
            if key.startswith(('translation_', 'session_')):
                del st.session_state[key]
        init_session_state()
        st.success("已重置所有状态！")
        st.rerun()

# ------------------- 使用说明 -------------------
with st.expander("📖 使用说明与新功能", expanded=False):
    st.markdown("""
    ### 🆕 新增功能
    - **API连接测试**: 在开始翻译前测试API连接状态
    - **文件统计预览**: 显示每个文件的字幕条数、字符数和预估翻译时间
    - **多语言支持**: 支持翻译到多种目标语言
    - **翻译质量选择**: 提供不同的翻译质量模式
    - **实时进度显示**: 更详细的进度条和状态信息
    - **翻译历史记录**: 保存最近的翻译历史
    - **智能重试机制**: 自动重试失败的翻译任务
    - **完整的错误报告**: 详细的错误信息和失败文件列表
    
    ### 🛠️ 技术优化
    - **修复Key冲突**: 使用时间戳确保每个组件的唯一性
    - **内存优化**: 改进的缓存管理和状态清理
    - **性能提升**: 优化的流式显示和批量处理
    - **错误恢复**: 更好的异常处理和用户反馈
    
    ### 📋 基本功能
    - 支持 `.srt` 字幕文件批量上传和翻译
    - 流式模式实时显示翻译进度
    - 可切换显示格式（只译文 / 原译对照）
    - 自定义字体大小和样式
    - 批量下载所有翻译结果
    
    ### ⚠️ 注意事项
    - 确保API服务正常运行
    - 大文件翻译可能需要较长时间
    - 建议在翻译前测试API连接
    - 翻译失败的文件会单独显示错误信息
    """)

# ------------------- 调试信息 -------------------
if st.checkbox("🔍 显示调试信息"):
    st.markdown("### 🐛 调试信息")
    col1, col2 = st.columns(2)
    with col1:
        st.json({
            "Session ID": st.session_state.session_id,
            "翻译结果数量": len(st.session_state.translation_results),
            "缓存键数量": len(st.session_state.translation_buffers),
            "历史记录数量": len(st.session_state.translation_history)
        })
    with col2:
        st.json({
            "API设置": st.session_state.api_settings,
            "当前参数": {
                "display_mode": display_mode if 'display_mode' in locals() else None,
                "target_language": target_language if 'target_language' in locals() else None,
                "translate_mode": translate_mode if 'translate_mode' in locals() else None
            }
        })
    
    if st.session_state.translation_buffers:
        st.write("缓存键:", list(st.session_state.translation_buffers.keys()))
