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
    page_title="SRT 深度翻译器 Pro",
    page_icon="🔮",
    layout="wide"
)

# ------------------- 初始化/获取后端配置 -------------------
@st.cache_data(ttl=3600)
def get_api_config(api_url: str) -> Optional[Dict[str, Any]]:
    """从后端获取API配置信息"""
    try:
        response = requests.get(f"{api_url}/config", timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        st.error(f"无法从API获取配置: {e}")
        return None

def init_session_state():
    """初始化会话状态"""
    if 'session_id' not in st.session_state:
        st.session_state.session_id = str(uuid.uuid4())[:8]
    if 'translation_results' not in st.session_state:
        st.session_state.translation_results = []
    if 'api_settings' not in st.session_state:
        st.session_state.api_settings = {'url': 'http://127.0.0.1:8000', 'timeout': 300}
    if 'api_config' not in st.session_state:
        st.session_state.api_config = get_api_config(st.session_state.api_settings['url'])
    # 初始化文件内容缓存
    if 'file_cache' not in st.session_state:
        st.session_state.file_cache = {}

# ------------------- 核心功能函数 (新增) -------------------

def calculate_cost_estimate(
    files_content: List[str], 
    model_name: str, 
    enable_sentence_break: bool
) -> str:
    """
    根据文件内容、所选模型和是否启用智能断句来估算费用。
    """
    # --- 基础定价 (美元 / 每100万 aTokens) ---
    # 假设Pro模型价格是Flash的10倍，这是一个常见的定价策略
    pricing = {
        "gemini-1.5-flash": {"input": 0.10, "output": 0.40},
        "gemini-1.5-pro": {"input": 1.00, "output": 4.00} 
    }
    model_price = pricing.get(model_name, pricing["gemini-1.5-flash"])

    # --- 估算参数 ---
    # Token换算率 (基于经验的保守估计)
    # 英文原文: 约4个字符计为1个Token
    # 中文译文: 约1.5个字符计为1个Token
    # 假设原文是英文，译文是中文
    CHARS_PER_INPUT_TOKEN = 4
    CHARS_PER_OUTPUT_TOKEN = 1.5
    # Prompt指令开销：估算指令文本会额外增加20%的输入Token
    PROMPT_OVERHEAD = 0.20
    # 智能断句任务开销：假设10%的字幕需要处理，且其API调用成本是普通翻译的2倍（因Prompt更复杂）
    BREAK_TASK_RATIO = 0.10
    BREAK_TASK_COST_MULTIPLIER = 2.0

    total_chars = sum(len(content) for content in files_content)
    if total_chars == 0:
        return "$0.00"

    # --- 计算主翻译任务费用 ---
    # 估算原文为英文，译文为中文时的字符数（中文通常更短）
    input_chars_main = total_chars
    output_chars_main = total_chars * 0.7 

    input_tokens_main = (input_chars_main / CHARS_PER_INPUT_TOKEN) * (1 + PROMPT_OVERHEAD)
    output_tokens_main = output_chars_main / CHARS_PER_OUTPUT_TOKEN
    
    cost_main = ((input_tokens_main / 1_000_000) * model_price["input"]) + \
                ((output_tokens_main / 1_000_000) * model_price["output"])

    # --- 计算智能断句任务费用 (如果启用) ---
    cost_break = 0
    if enable_sentence_break:
        input_chars_break = input_chars_main * BREAK_TASK_RATIO
        output_chars_break = output_chars_main * BREAK_TASK_RATIO

        input_tokens_break = (input_chars_break / CHARS_PER_INPUT_TOKEN) * (1 + PROMPT_OVERHEAD)
        output_tokens_break = output_chars_break / CHARS_PER_OUTPUT_TOKEN

        cost_break = (((input_tokens_break / 1_000_000) * model_price["input"]) + \
                     ((output_tokens_break / 1_000_000) * model_price["output"])) * BREAK_TASK_COST_MULTIPLIER

    total_cost = cost_main + cost_break

    # 返回一个格式化的价格范围，使其看起来更像估算值
    cost_low = total_cost * 0.8
    cost_high = total_cost * 1.2
    
    if cost_high < 0.01:
         return "< $0.01 (费用极低)"
    else:
        return f"~ ${cost_low:.2f} - ${cost_high:.2f} USD"

# ------------------- 初始化 -------------------
init_session_state()

# ------------------- 样式 -------------------
st.markdown("""
<style>
/* --- 全局页面背景 --- */
.stApp {
    background-color: #ffffff;
}

/* --- 为所有输入框、选择框设置统一样式，使其在灰色背景下清晰可见 --- */
div[data-testid="stTextInput"], 
div[data-testid="stNumberInput"], 
div[data-testid="stSelectbox"] {
    background-color: #f0f2f6; /* 设置背景为白色 */
    border: 1px solid #cccccc;  /* 添加一个浅灰色边框 */
    border-radius: 5px;         /* 添加圆角，使其更美观 */
    padding: 0px 5px;           /* 可选：微调内部边距 */
}

/* --- 修复Streamlit部分版本中下拉框箭头颜色问题 --- */
div[data-testid="stSelectbox"] div[data-baseweb="select"] > div {
    background-color: transparent;
}

/* --- 主要文本预览区域的样式 --- */
div[data-testid="stTextArea"] > div > div > textarea {
    height: 300px !important;
    font-family: 'Courier New', monospace !important;
    font-size: 12px !important;
    line-height: 1.4 !important;
    background-color: #f9f9f9; /* 也可以为预览区设置一个略微不同的背景色 */
    border: 1px solid #dddddd;
}
</style>
""", unsafe_allow_html=True)

# ------------------- 主界面 -------------------
st.title("🔮 SRT 深度翻译器 Pro")
st.markdown("上传一个或多个 `.srt` 文件，本工具将调用大语言模型进行上下文感知的高质量翻译，并提供丰富的专业选项。")

# ------------------- 侧边栏设置 -------------------
with st.sidebar:
    st.header("⚙️ API设置")
    api_url = st.text_input("API地址", value=st.session_state.api_settings['url'], help="您的后端翻译服务的URL地址。")
    api_timeout = st.number_input("请求超时(秒)", min_value=30, max_value=600, value=st.session_state.api_settings['timeout'], help="单个文件翻译任务的最大等待时间。")
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
    on_change=lambda: st.session_state.update(translation_results=[], file_cache={}),
    key="file_uploader_main"
)

# 缓存文件内容以避免重复读取
if uploaded_files:
    for f in uploaded_files:
        if f.file_id not in st.session_state.file_cache:
            st.session_state.file_cache[f.file_id] = f.getvalue().decode('utf-8-sig', errors='ignore')

# 仅当有文件上传时才显示后续内容
if uploaded_files:
    st.markdown("---")
    st.subheader("📄 文件概览")
    total_chars = sum(len(content) for content in st.session_state.file_cache.values())
    total_lines = sum(content.count('\n') for content in st.session_state.file_cache.values())
    
    col1, col2, col3 = st.columns(3)
    col1.metric("总文件数", len(uploaded_files))
    col2.metric("总字符数", f"{total_chars:,}")
    col3.metric("总行数", f"{total_lines:,}")


if not st.session_state.api_config:
    st.error("API配置加载失败，请检查侧边栏中的API地址并刷新配置。")
else:
    # --- 配置解析 ---
    api_config = st.session_state.api_config
    lang_map = api_config.get("supported_languages", {"Simplified Chinese": "简体中文"})
    quality_modes = api_config.get("quality_modes", ["标准", "高质量", "快速"])
    default_lang = api_config.get("default_target_language", "Simplified Chinese")
    supported_models = api_config.get("supported_models", ["gemini-1.5-flash", "gemini-1.5-pro"])
    sb_features = api_config.get("sentence_break_features", {})
    lang_display_map = {v: k for k, v in lang_map.items()}

    st.markdown("### ⚙️ 翻译核心配置")
    col1, col2 = st.columns(2)
    with col1:
        target_language_display = st.selectbox(
            "目标语言", 
            options=list(lang_display_map.keys()), 
            index=list(lang_display_map.values()).index(default_lang) if default_lang in lang_display_map.values() else 0,
            help="选择您希望将字幕翻译成的目标语言。"
        )
        target_language = lang_display_map[target_language_display]
    with col2:
        quality_mode = st.selectbox(
            "翻译质量", 
            options=quality_modes, 
            index=1,
            help="此选项控制AI的'温度(temperature)'参数，决定了翻译的创造性水平。\n- **快速**: 温度较低，速度快，结果更保守、直接。\n- **标准**: 默认选项，在准确性和流畅性之间取得良好平衡。\n- **高质量**: 温度较高，AI会更具创造性，译文可能更自然流畅，但也可能出现意想不到的表达。"
        )
    
    display_mode_options = {"仅显示译文": "only_translated", "原文在上，译文在下": "original_above_translated", "译文在上，原文在下": "translated_above_original"}
    selected_display_mode_label = st.radio(
        "选择显示格式", 
        list(display_mode_options.keys()),
        help="选择最终生成的SRT文件内容的格式。\n- **仅显示译文**: 最常见的选择，用于直接观看。\n- **双语格式**: 非常适合语言学习者或需要校对翻译质量的专业人士。"
    )
    display_mode = display_mode_options[selected_display_mode_label]
    font_size = None
    if display_mode != "only_translated":
        font_size = st.number_input(
            "**设置原文的字体大小 (可选)**", 
            min_value=1, max_value=7, value=2,
            help="在双语模式下，可以为原文设置不同的字体大小以便区分。此功能依赖于播放器的HTML标签支持。"
        )

    with st.expander("更多高级选项与成本控制"):
        model_name = st.selectbox(
            "选择AI模型", 
            options=supported_models, 
            index=0,
            help="这是影响翻译质量和成本的最关键因素。\n- **Gemini 1.5 Flash**: 速度快，价格经济，性价比极高，适合绝大多数日常视频和常规内容的翻译。\n- **Gemini 1.5 Pro**: 功能更强大的旗舰模型，具备更强的逻辑推理和细微语境理解能力。适合翻译专业、复杂或包含大量术语的内容，当然成本也更高。"
        )
        
        st.markdown("---") 

        col_adv1, col_adv2 = st.columns(2)
        with col_adv1:
            st.write("##### 强制换行")
            split_long_lines = st.checkbox("自动分割过长的译文行", value=True, help="这是一个“硬分割”功能。当单行译文超过下方设定的字符数时，会强制换行。有助于提升在移动设备上的可读性，但可能在不恰当的位置分割句子。")
            max_line_length = st.number_input("每行译文最大字符数", min_value=20, max_value=100, value=40, disabled=not split_long_lines)

        with col_adv2:
            st.write("##### 智能长句断句 (AI驱动)")
            enable_sentence_break = st.checkbox(
                "启用智能长句断句", 
                value=False, 
                help="【推荐用于提升观感，但会增加成本】此功能会发起一次额外的、独立的AI调用。AI会分析那些持续时间过长的字幕，并根据语义和自然的语音停顿，将其智能地拆分成多个更短、更易于阅读的字幕条目。这能极大地优化观看体验，尤其是在处理旁白或快速对话时。"
            )
        
        if enable_sentence_break:
            col_sb1, col_sb2 = st.columns(2)
            with col_sb1:
                min_duration = st.number_input(
                    "断句最小时长 (秒)", 
                    min_value=3.0, max_value=20.0, 
                    value=sb_features.get("min_duration_seconds", 6.0), 
                    step=0.5,
                    help="只有当一条字幕的显示时间超过此值时，它才会被考虑进行智能断句。这可以防止系统处理那些本身就很短的字幕。"
                )
            with col_sb2:
                min_chars = st.number_input(
                    "断句最小字符数", 
                    min_value=20, max_value=200, 
                    value=sb_features.get("max_chars_for_break", 60), 
                    step=5,
                    help="只有当一条字幕的**原文**字符数超过此值时，它才会被考虑进行智能断句。这有助于精确锁定那些真正冗长的句子。"
                )

    # --- 新增：成本实时预估 ---
    if uploaded_files:
        st.markdown("---")
        with st.container():
            all_files_content = list(st.session_state.file_cache.values())
            estimated_cost_str = calculate_cost_estimate(all_files_content, model_name, enable_sentence_break)
            st.info(f"💰 **预估费用:** {estimated_cost_str}", icon="💡")
            st.caption("这是一个基于您上传文件的总字符数、所选模型和设置的粗略估算。实际费用可能因文本复杂度、对话密度和最终的Token用量而略有浮动。")

    # ------------------- 翻译按钮和处理逻辑 -------------------
    if st.button("🚀 开始翻译所有文件", disabled=not uploaded_files, type="primary"):
        # ... (后续的翻译逻辑代码保持不变) ...
        st.session_state.translation_results = []
        st.session_state.session_id = str(uuid.uuid4())[:8]
        file_data_list = [{'name': f.name, 'data': st.session_state.file_cache[f.file_id].encode('utf-8')} for f in uploaded_files]
        
        params = {
            'display_mode': display_mode, 
            'target_language': target_language, 
            'quality_mode': quality_mode,
            'split_long_lines': split_long_lines, 
            'max_line_length': max_line_length, 
            'model_name': model_name,
            'enable_sentence_break': enable_sentence_break,
        }
        if enable_sentence_break:
             params.update({
                'min_duration_seconds': min_duration,
                'max_chars_for_break': min_chars
             })

        if font_size is not None and display_mode != "only_translated":
            params['font_size'] = font_size

        progress_bar = st.progress(0, "准备开始...")
        status_text = st.empty()
        results_placeholder = st.empty()

        start_time = time.time()
        for i, file_data in enumerate(file_data_list):
            file_name = file_data['name']
            status_text.info(f"正在处理第 {i + 1}/{len(file_data_list)} 个文件: **{file_name}**")
            try:
                endpoint = f"{st.session_state.api_settings['url']}/translate-stream"
                files = {'file': (file_name, file_data['data'], 'text/plain')}
                translated_buffer = ""
                with requests.post(endpoint, files=files, params=params, stream=True, timeout=st.session_state.api_settings['timeout']) as response:
                    response.raise_for_status()
                    for chunk in response.iter_content(chunk_size=None, decode_unicode=True):
                        if chunk.startswith("[STATUS]"):
                            status_text.info(f"文件 **{file_name}**: {chunk.replace('[STATUS]', '').strip()}")
                        elif chunk:
                            translated_buffer += chunk
                
                st.session_state.translation_results.append({'name': file_name, 'content': translated_buffer, 'success': True, 'error': None})
            except Exception as e:
                error_message = f"处理文件时出错: {e}"
                if isinstance(e, requests.exceptions.HTTPError):
                    error_message += f" (服务器返回: {e.response.text})"
                st.session_state.translation_results.append({'name': file_name, 'content': None, 'success': False, 'error': error_message})

            with results_placeholder.container():
                st.markdown("---")
                st.subheader("📝 翻译结果 (实时更新)")
                for j, result in enumerate(st.session_state.translation_results):
                    with st.expander(f"文件: **{result['name']}** ({'✅ 成功' if result['success'] else '❌ 失败'})", expanded=True):
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
            
            progress_bar.progress((i + 1) / len(file_data_list))

        end_time = time.time()
        total_time = end_time - start_time
        status_text.success(f"🎉 所有文件处理完成！总耗时: {total_time:.2f} 秒。")
        time.sleep(2)
        status_text.empty()
        progress_bar.empty()
        results_placeholder.empty()

# ------------------- 最终结果与总结区域 -------------------
if st.session_state.translation_results:
    st.markdown("---")
    st.subheader("📝 最终翻译结果")

    for i, result in enumerate(st.session_state.translation_results):
        with st.expander(f"文件: **{result['name']}** ({'✅ 成功' if result['success'] else '❌ 失败'})", expanded=True):
            if result['success']:
                st.text_area(
                    "翻译预览", value=result['content'],
                    key=f"final_textarea_{st.session_state.session_id}_{i}",
                    height=300
                )
                st.download_button(
                    label="📥 下载此翻译文件", data=result['content'].encode('utf-8'),
                    file_name=f"{os.path.splitext(result['name'])[0]}_translated.srt", mime="text/plain",
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
                key=f"download_all_{st.session_state.session_id}",
                type="primary"
            )
        except Exception as e:
            st.error(f"创建 ZIP 文件时出错: {e}")
