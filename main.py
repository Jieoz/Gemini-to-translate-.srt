from fastapi import FastAPI, HTTPException, File, UploadFile, Query
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
import os
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
from typing import List, AsyncGenerator, Dict, Optional, Any
import re
import asyncio
import logging
from datetime import datetime

# 加载环境变量
load_dotenv()

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# FastAPI应用初始化
app = FastAPI(
    title="SRT翻译API",
    description="支持多语言字幕翻译和高级优化的API服务",
    version="5.0.4" # 格式修复最终版
)

# 添加CORS中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- 核心配置参数 ---
MAX_CHARS_PER_BATCH = 8000
MAX_RETRIES = 3
RATE_LIMIT_DELAY = 5

# 支持的语言映射
SUPPORTED_LANGUAGES = {
    "Simplified Chinese": "简体中文",
    "English": "英文",
    "Japanese": "日文",
    "Korean": "韩文",
    "French": "法文",
    "German": "德文",
    "Spanish": "西班牙文",
    "Italian": "意大利文",
    "Russian": "俄文",
    "Arabic": "阿拉伯文"
}

# 质量模式配置
QUALITY_MODES = {
    "快速": {"temperature": 0.3, "max_tokens": 2048},
    "标准": {"temperature": 0.7, "max_tokens": 4096},
    "高质量": {"temperature": 0.9, "max_tokens": 8192}
}

# 支持的模型列表
SUPPORTED_MODELS = ["gemini-2.0-flash", "gemini-1.5-pro", "gemini-1.5-flash"]

# Gemini API配置
try:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY environment variable not found")
    genai.configure(api_key=api_key)
    logger.info("Gemini API Key配置成功")
except Exception as e:
    logger.error(f"Gemini API Key配置失败: {e}")

# 安全设置
SAFETY_SETTINGS = {
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
}

# --- Pydantic Models for API ---
class APIStatus(BaseModel):
    status: str
    message: str
    timestamp: str
    version: str

# --- 翻译提示词模板 ---
def get_translation_prompt(target_language: str, quality_mode: str) -> str:
    """根据目标语言和质量模式生成翻译提示词（英文指令，明确中文目标）"""

    lang_name = SUPPORTED_LANGUAGES.get(target_language, "简体中文")

    quality_instructions = {
        "快速": "prioritizing speed while maintaining basic accuracy.",
        "标准": "balancing speed and quality for a natural, fluent translation.",
        "高质量": "prioritizing quality, deeply understanding context to produce the best possible translation."
    }

    return f"""
You are a professional subtitle translation expert. Your task is to translate groups of subtitles into fluent, natural {lang_name}.

**Core Requirements:**
1. **Process by Group:** The input contains sentence groups marked by `[GROUP START]` and `[GROUP END]`. Each group represents a complete semantic unit.
2. **Translate Holistically:** Understand the full sentence by combining all `[index]` lines within a group, then translate it into natural {lang_name}.
3. **Allocate Intelligently:** Distribute the complete translation back to the corresponding `[index]` lines, maintaining logical coherence.
4. **Single-Line Output:** The translated text for each `[index]` must be a single line without any line breaks.

**Quality Requirement:** Your translation should be {quality_instructions.get(quality_mode, quality_instructions['标准'])}

**Formatting Rules:**
- Preserve all original `[index]` numbers.
- Avoid literal translations; focus on natural language.

**Example:**
*Input:*
[GROUP START]
[33] some of these carriages were built in the 1920s and offer those lucky
[34] enough to get a ticket a level of comfort
[35] almost unrivalled anywhere in the world.
[GROUP END]

*Correct Output (if target is 简体中文):*
[33] 其中一些车厢建于20世纪20年代，为那些幸运的乘客
[34] 提供了一种近乎无与伦比的舒适体验
[35] 这在世界上的任何地方都难得一见。

Now, please process the following subtitle groups:
{{subtitle_batch_text}}
"""

# --- 核心处理函数 ---

def strip_tags(text: str) -> str:
    """移除SRT/ASS/HTML样式标签"""
    return re.sub(r'\{.*?\}|<.*?>', '', text).strip()

def create_template_and_clean_text(original_line: str) -> Dict[str, str]:
    """创建格式模板并提取纯文本"""
    clean_text = strip_tags(original_line)
    template = original_line

    if clean_text:
        placeholder = "___TRANSLATION_PLACEHOLDER___"
        try:
            template = re.sub(re.escape(clean_text), placeholder, template, 1)
        except re.error:
            template = template.replace(clean_text, placeholder, 1)

        template = template.replace('{', '{{').replace('}', '}}')
        template = template.replace(placeholder, '{}')
    else:
        template = template.replace('{', '{{').replace('}', '}}')

    return {"clean": clean_text, "template": template}

def parse_srt(srt_content: str) -> List[Dict]:
    """解析SRT文件内容"""
    lines = srt_content.strip().split("\n")
    subtitles = []
    i = 0

    while i < len(lines):
        try:
            if lines[i].strip().isdigit():
                index = int(lines[i].strip())
                i += 1

                if i >= len(lines): break

                time_str = lines[i]
                if "-->" not in time_str: continue
                i += 1

                text_lines_raw = []
                while i < len(lines) and lines[i].strip() != "":
                    text_lines_raw.append(lines[i])
                    i += 1

                processed_lines = [create_template_and_clean_text(raw_line) for raw_line in text_lines_raw if raw_line.strip()]

                if processed_lines:
                    subtitles.append({
                        "index": index,
                        "time": time_str,
                        "lines": processed_lines
                    })
                i += 1
            else:
                i += 1
        except (ValueError, IndexError) as e:
            logger.warning(f"解析SRT时出错: {e} at line {i}")
            i += 1
            continue

    return subtitles

def group_subtitles_by_sentence(subtitles: List[Dict]) -> List[List[Dict]]:
    """根据句子结构分组字幕"""
    if not subtitles: return []

    groups = []
    current_group = []
    sentence_enders = ('.', '?', '!', '."', '."', '？', '！', '。')

    for sub in subtitles:
        full_clean_text = " ".join([line['clean'] for line in sub['lines']]).strip()
        current_group.append(sub)

        if (full_clean_text.endswith(sentence_enders) or
            (full_clean_text.isupper() and full_clean_text) or
            len(current_group) >= 5):
            groups.append(current_group)
            current_group = []

    if current_group:
        groups.append(current_group)

    return groups

async def api_call_with_retry(prompt: str, quality_mode: str, model_name: str) -> str:
    """带重试的API调用，并动态选择模型"""
    if not os.getenv("GEMINI_API_KEY"):
        return "API_KEY_MISSING"

    config = QUALITY_MODES.get(quality_mode, QUALITY_MODES["标准"])

    try:
        model = genai.GenerativeModel(model_name)
    except Exception as e:
        logger.error(f"无法创建模型 '{model_name}': {e}")
        return f"INVALID_MODEL_NAME: {model_name}"

    for attempt in range(MAX_RETRIES):
        try:
            response = await model.generate_content_async(
                prompt,
                safety_settings=SAFETY_SETTINGS,
                generation_config=genai.types.GenerationConfig(
                    temperature=config["temperature"],
                    max_output_tokens=config["max_tokens"]
                )
            )

            return response.text.strip() if response.text else "EMPTY_RESPONSE"

        except Exception as e:
            error_msg = str(e)
            if "429" in error_msg and attempt < MAX_RETRIES - 1:
                delay = RATE_LIMIT_DELAY * (2 ** attempt)
                logger.warning(f"API限流，{delay}秒后重试...")
                await asyncio.sleep(delay)
            elif "SAFETY" in error_msg:
                logger.error(f"内容安全检查失败: {error_msg}")
                return "SAFETY_BLOCK"
            else:
                logger.error(f"API调用失败 (attempt {attempt + 1}): {error_msg}")
                if attempt == MAX_RETRIES - 1:
                    return "API_CALL_FAILED"
                await asyncio.sleep(2)

    return "API_CALL_FAILED"

async def translate_batch_of_groups_and_parse(
    batch_of_groups: List[List[Dict]],
    target_language: str,
    quality_mode: str,
    model_name: str
) -> Dict[int, str]:
    """翻译单个字幕组批次并解析结果"""

    batch_input_text = ""
    original_text_map = {}

    for group in batch_of_groups:
        batch_input_text += "[GROUP START]\n"
        for sub in group:
            clean_text = " ".join([line['clean'] for line in sub['lines']])
            batch_input_text += f"[{sub['index']}] {clean_text}\n"
            original_text_map[sub['index']] = clean_text
        batch_input_text += "[GROUP END]\n"

    prompt = get_translation_prompt(target_language, quality_mode).format(
        subtitle_batch_text=batch_input_text
    )

    response_text = await api_call_with_retry(prompt, quality_mode, model_name)

    if response_text in ("API_CALL_FAILED", "API_CONFIGURATION_ERROR", "SAFETY_BLOCK", "EMPTY_RESPONSE", "INVALID_MODEL_NAME"):
        logger.error(f"翻译批次失败: {response_text}")
        return {sub['index']: original_text_map.get(sub['index'], "") for group in batch_of_groups for sub in group}

    translation_map = {}
    pattern = re.compile(r'\[(\d+)\]\s*(.*)')

    for line in response_text.split('\n'):
        match = pattern.match(line.strip())
        if match:
            index = int(match.group(1))
            translation = match.group(2).strip()
            if translation:
                translation_map[index] = translation

    for group in batch_of_groups:
        for sub in group:
            if sub['index'] not in translation_map:
                logger.warning(f"警告: 索引 {sub['index']} 未在响应中找到，使用原文")
                translation_map[sub['index']] = original_text_map.get(sub['index'], "")

    return translation_map

async def translate_srt_stream(
    srt_content: str,
    display_mode: str,
    target_language: str,
    quality_mode: str,
    font_size: Optional[int],
    split_long_lines: bool,
    max_line_length: int,
    model_name: str
) -> AsyncGenerator[str, None]:
    """主要翻译流处理函数，包含动态批处理和并发API调用"""

    try:
        original_subtitles = parse_srt(srt_content)
        if not original_subtitles:
            yield "[STATUS] 错误: 无法解析SRT文件"
            return

        subtitle_groups = group_subtitles_by_sentence(original_subtitles)

        all_batches = []
        current_batch = []
        current_chars = 0
        for group in subtitle_groups:
            group_chars = sum(len(line['clean']) for sub in group for line in sub['lines'])
            if current_batch and (current_chars + group_chars > MAX_CHARS_PER_BATCH):
                all_batches.append(current_batch)
                current_batch = []
                current_chars = 0
            current_batch.append(group)
            current_chars += group_chars
        if current_batch:
            all_batches.append(current_batch)

        yield f"[STATUS] 文件已拆分为 {len(all_batches)} 个批次进行处理..."

        tasks = [translate_batch_of_groups_and_parse(batch, target_language, quality_mode, model_name) for batch in all_batches]
        yield "[STATUS] 正在并行发送所有翻译请求..."

        results_list = await asyncio.gather(*tasks)

        yield "[STATUS] 所有翻译结果已返回，正在重组..."

        final_translation_map = {}
        for result_map in results_list:
            final_translation_map.update(result_map)

        for sub in original_subtitles:
            # 获取该条字幕的完整译文，并移除所有换行符
            translated_text = final_translation_map.get(sub['index'], "").replace('\n', ' ').strip()

            # (可选)如果需要，对过长的译文进行分行
            if split_long_lines and len(translated_text) > max_line_length:
                translated_text = '\n'.join([translated_text[i:i+max_line_length] for i in range(0, len(translated_text), max_line_length)])

            # --- 核心修改点 ---

            # 1. 重构带格式的译文
            # 将所有行的纯文本合并，然后用第一行的格式模板来包裹。
            # 这假设一个字幕条目内的所有行共享相同的基础样式（如颜色）。
            first_line_template = sub['lines'][0]['template'] if sub['lines'] else '{}'
            # 确保即使没有译文，也不会出现格式化错误
            final_translated_text_with_tags = first_line_template.format(translated_text) if translated_text else ""

            # 2. 重构带格式的原文（用于双语模式）
            original_text_for_display = ""
            if display_mode != "only_translated":
                # 将每一行的原始纯文本拼接起来
                original_full_clean_text = " ".join([line['clean'] for line in sub['lines']])

                # 使用第一行的格式模板来包裹完整的原文纯文本
                original_text_single_line_with_tags = first_line_template.format(original_full_clean_text)

                # 应用额外的字体大小标签
                if font_size:
                    original_text_for_display = f'<font size="{font_size}">{original_text_single_line_with_tags}</font>'
                else:
                    original_text_for_display = original_text_single_line_with_tags

            # --- 修改结束 ---

            # 3. 构建最终输出块
            output_chunk = f"{sub['index']}\n{sub['time']}\n"
            if display_mode == "only_translated":
                output_chunk += f"{final_translated_text_with_tags}\n\n"
            elif display_mode == "original_above_translated":
                output_chunk += f"{original_text_for_display}\n{final_translated_text_with_tags}\n\n"
            elif display_mode == "translated_above_original":
                output_chunk += f"{final_translated_text_with_tags}\n{original_text_for_display}\n\n"

            yield output_chunk

        yield "[STATUS] 翻译完成！"

    except Exception as e:
        logger.error(f"翻译过程中出错: {e}", exc_info=True)
        yield f"[STATUS] 翻译失败: {str(e)}"

# --- API 端点 ---

@app.get("/", response_model=APIStatus, summary="API状态检查")
async def root():
    """返回API的当前状态和版本信息。"""
    return APIStatus(
        status="active",
        message="SRT Translation API is running.",
        timestamp=datetime.now().isoformat(),
        version="5.0.4"
    )

@app.get("/config", summary="获取API配置")
async def get_config():
    """返回支持的语言、质量模式和模型等配置信息。"""
    return {
        "supported_languages": SUPPORTED_LANGUAGES,
        "quality_modes": list(QUALITY_MODES.keys()),
        "default_target_language": "Simplified Chinese",
        "supported_models": SUPPORTED_MODELS
    }

@app.post("/translate-stream", summary="流式翻译SRT文件")
async def translate_stream_endpoint(
    file: UploadFile = File(..., description="要翻译的SRT文件"),
    display_mode: str = Query("only_translated", description="显示模式"),
    target_language: str = Query("Simplified Chinese", description="目标语言"),
    quality_mode: str = Query("标准", description="质量模式"),
    font_size: Optional[int] = Query(None, description="原文的字体大小 (1-7)"),
    split_long_lines: bool = Query(True, description="是否自动分割过长的译文行"),
    max_line_length: int = Query(40, description="每行译文的最大字符数"),
    model_name: str = Query("gemini-1.5-flash", description="要使用的Gemini模型")
):
    """接收SRT文件并以流式响应返回翻译结果。"""
    try:
        contents = await file.read()
        srt_content = contents.decode("utf-8-sig")

        if target_language not in SUPPORTED_LANGUAGES:
            raise HTTPException(status_code=400, detail=f"不支持的语言: {target_language}")

        if quality_mode not in QUALITY_MODES:
            raise HTTPException(status_code=400, detail=f"不支持的质量模式: {quality_mode}")

        if model_name not in SUPPORTED_MODELS:
            raise HTTPException(status_code=400, detail=f"不支持的模型: {model_name}")

        return StreamingResponse(
            translate_srt_stream(
                srt_content, display_mode, target_language, quality_mode,
                font_size, split_long_lines, max_line_length, model_name
            ),
            media_type="text/plain; charset=utf-8"
        )

    except Exception as e:
        logger.error(f"流式翻译失败: {e}", exc_info=True)
        async def error_stream():
            yield f"[STATUS] 翻译失败: {str(e)}"
        return StreamingResponse(error_stream(), media_type="text/plain; charset=utf-8", status_code=500)


if __name__ == "__main__":
    import uvicorn

    if not os.getenv("GEMINI_API_KEY"):
        logger.error("致命错误: 未找到GEMINI_API_KEY环境变量")
        exit(1)

    logger.info("启动SRT翻译API服务...")
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info",
        access_log=True
    )
