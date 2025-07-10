from fastapi import FastAPI, HTTPException, File, UploadFile, Query, BackgroundTasks
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
import json
from datetime import datetime
import hashlib
import aiofiles
from pathlib import Path
import time

# 加载环境变量
load_dotenv()

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# FastAPI应用初始化
app = FastAPI(
    title="SRT翻译API",
    description="支持多语言字幕翻译的API服务",
    version="2.0.0"
)

# 添加CORS中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 核心配置参数
GROUP_BATCH_SIZE = 20
MAX_RETRIES = 3
RATE_LIMIT_DELAY = 5

# 支持的语言映射
SUPPORTED_LANGUAGES = {
    "Chinese": "中文",
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
    "快速": {"temperature": 0.3, "max_tokens": 1000},
    "标准": {"temperature": 0.7, "max_tokens": 2000},
    "高质量": {"temperature": 0.9, "max_tokens": 3000}
}

# Gemini API配置
try:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY environment variable not found")
    
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-2.0-flash')
    logger.info("Gemini API配置成功")
except Exception as e:
    logger.error(f"Gemini API配置失败: {e}")
    model = None

# 安全设置
SAFETY_SETTINGS = {
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
}

# 请求模型
class TranslationRequest(BaseModel):
    display_mode: str = "only_translated"
    target_language: str = "Chinese"
    quality_mode: str = "标准"
    font_size: Optional[int] = None
    preserve_formatting: bool = True
    split_long_lines: bool = True
    max_line_length: int = 40

class APIStatus(BaseModel):
    status: str
    message: str
    timestamp: str
    version: str

# 翻译提示词模板
def get_translation_prompt(target_language: str, quality_mode: str) -> str:
    """根据目标语言和质量模式生成翻译提示词"""
    
    quality_instructions = {
        "快速": "注重翻译速度，保持基本准确性。",
        "标准": "在速度和质量之间取得平衡，确保翻译自然流畅。",
        "高质量": "优先考虑翻译质量，深入理解上下文，产生最佳的翻译效果。"
    }
    
    return f"""
你是一位专业的字幕翻译专家。你的任务是将字幕组翻译成流畅、自然的{SUPPORTED_LANGUAGES.get(target_language, '中文')}字幕。

**核心要求：**
1. **按组处理：** 输入包含由`[GROUP START]`和`[GROUP END]`标记的句子组，每组代表一个完整的语义单元
2. **整体翻译：** 将每组的所有`[index]`行文本理解为一个完整句子，然后翻译成自然的{SUPPORTED_LANGUAGES.get(target_language, '中文')}
3. **智能分配：** 将完整的翻译内容合理分配回对应的`[index]`行，保持逻辑连贯性
4. **单行输出：** 每个`[index]`对应的翻译内容必须是单行，不能包含换行符

**质量要求：** {quality_instructions.get(quality_mode, quality_instructions['标准'])}

**格式要求：**
- 保持所有原始的`[index]`编号
- 每个翻译行不超过40个字符
- 保持字幕的时间同步性
- 避免过度直译，注重语言的自然性

**示例：**
*输入：*
[GROUP START]
[33] some of these carriages were built in the 1920s and offer those lucky
[34] enough to get a ticket a level of comfort
[35] almost unrivalled anywhere in the world.
[GROUP END]

*正确输出：*
[33] 其中一些车厢建于20世纪20年代，为那些幸运的乘客
[34] 提供了一种近乎无与伦比的舒适体验
[35] 这在世界上的任何地方都难得一见。

现在请处理以下字幕组：
{{subtitle_batch_text}}
"""

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
                
                if i >= len(lines):
                    break
                    
                time_str = lines[i]
                if "-->" not in time_str:
                    continue
                i += 1
                
                text_lines_raw = []
                while i < len(lines) and lines[i].strip() != "":
                    text_lines_raw.append(lines[i])
                    i += 1
                
                processed_lines = []
                for raw_line in text_lines_raw:
                    if raw_line.strip():
                        processed_lines.append(create_template_and_clean_text(raw_line))

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
            logger.warning(f"解析SRT时出错: {e}")
            i += 1
            continue
    
    return subtitles

def group_subtitles_by_sentence(subtitles: List[Dict]) -> List[List[Dict]]:
    """根据句子结构分组字幕"""
    if not subtitles:
        return []
    
    groups = []
    current_group = []
    sentence_enders = ('.', '?', '!', '."', '."', '？', '！', '。')
    
    for sub in subtitles:
        full_clean_text = " ".join([line['clean'] for line in sub['lines']]).strip()
        current_group.append(sub)
        
        if (full_clean_text.endswith(sentence_enders) or 
            (full_clean_text.isupper() and full_clean_text) or 
            len(current_group) >= 5):  # 防止组过长
            groups.append(current_group)
            current_group = []
    
    if current_group:
        groups.append(current_group)
    
    return groups

def get_file_stats(srt_content: str) -> Dict[str, Any]:
    """获取文件统计信息"""
    lines = srt_content.strip().split('\n')
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
        'estimated_time': max(1, subtitle_count // 10)
    }

def split_long_line(text: str, max_length: int = 40) -> List[str]:
    """智能分割长行"""
    if len(text) <= max_length:
        return [text]
    
    # 优先在标点符号处分割
    punctuation = '，。！？；：、'
    words = text.split()
    lines = []
    current_line = ""
    
    for word in words:
        if len(current_line + word) <= max_length:
            current_line += word + " "
        else:
            if current_line:
                lines.append(current_line.strip())
            current_line = word + " "
    
    if current_line:
        lines.append(current_line.strip())
    
    return lines

async def api_call_with_retry(prompt: str, quality_mode: str = "标准") -> str:
    """带重试的API调用"""
    if not model:
        return "API_CONFIGURATION_ERROR"
    
    config = QUALITY_MODES.get(quality_mode, QUALITY_MODES["标准"])
    
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
            
            if response.text:
                return response.text.strip()
            else:
                return "EMPTY_RESPONSE"
                
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
    target_language: str = "Chinese",
    quality_mode: str = "标准"
) -> Dict[int, str]:
    """翻译一批字幕组并解析结果"""
    
    # 构建批次输入文本
    batch_input_text = ""
    original_text_map = {}
    
    for group in batch_of_groups:
        batch_input_text += "[GROUP START]\n"
        for sub in group:
            clean_text = " ".join([line['clean'] for line in sub['lines']])
            batch_input_text += f"[{sub['index']}] {clean_text}\n"
            original_text_map[sub['index']] = clean_text
        batch_input_text += "[GROUP END]\n"

    # 生成提示词并调用API
    prompt = get_translation_prompt(target_language, quality_mode).format(
        subtitle_batch_text=batch_input_text
    )
    
    response_text = await api_call_with_retry(prompt, quality_mode)

    # 处理API调用失败的情况
    if response_text in ("API_CALL_FAILED", "API_CONFIGURATION_ERROR", "SAFETY_BLOCK", "EMPTY_RESPONSE"):
        logger.error(f"翻译失败: {response_text}")
        return original_text_map

    # 解析翻译结果
    translation_map = {}
    pattern = re.compile(r'\[(\d+)\]\s*(.*)')
    
    for line in response_text.split('\n'):
        line = line.strip()
        if not line:
            continue
            
        match = pattern.match(line)
        if match:
            index = int(match.group(1))
            translation = match.group(2).strip()
            if translation:
                translation_map[index] = translation

    # 为缺失的索引提供回退
    for group in batch_of_groups:
        for sub in group:
            if sub['index'] not in translation_map:
                logger.warning(f"警告: 索引 {sub['index']} 未在响应中找到，使用原文")
                translation_map[sub['index']] = original_text_map.get(sub['index'], "")

    return translation_map

async def translate_srt_stream(
    srt_content: str, 
    display_mode: str = "only_translated",
    target_language: str = "Chinese",
    quality_mode: str = "标准",
    font_size: Optional[int] = None,
    split_long_lines: bool = True,
    max_line_length: int = 40
) -> AsyncGenerator[str, None]:
    """主要翻译流处理函数"""
    
    try:
        # 解析和分组字幕
        original_subtitles = parse_srt(srt_content)
        if not original_subtitles:
            yield "[STATUS] 错误: 无法解析SRT文件"
            return
            
        subtitle_groups = group_subtitles_by_sentence(original_subtitles)
        total_groups = len(subtitle_groups)
        
        yield f"[STATUS] 开始翻译，共 {total_groups} 个字幕组"
        
        # 分批处理字幕组
        for i in range(0, total_groups, GROUP_BATCH_SIZE):
            batch_of_groups = subtitle_groups[i:i + GROUP_BATCH_SIZE]
            if not batch_of_groups:
                continue

            start_index = batch_of_groups[0][0]['index']
            end_index = batch_of_groups[-1][-1]['index']
            
            yield f"[STATUS] 正在翻译批次 {i//GROUP_BATCH_SIZE + 1}/{(total_groups + GROUP_BATCH_SIZE - 1)//GROUP_BATCH_SIZE} (字幕 {start_index}-{end_index})"

            # 翻译当前批次
            translation_map = await translate_batch_of_groups_and_parse(
                batch_of_groups, target_language, quality_mode
            )

            # 生成输出
            for group in batch_of_groups:
                for sub in group:
                    translated_text = translation_map.get(sub['index'], "").replace('\n', ' ').strip()
                    
                    # 分割长行
                    if split_long_lines and len(translated_text) > max_line_length:
                        translated_lines = split_long_line(translated_text, max_line_length)
                        translated_text = '\n'.join(translated_lines)
                    
                    # 重建原文
                    original_text_lines = [line['template'].format(line['clean']) for line in sub['lines']]
                    
                    # 应用字体大小
                    if font_size and display_mode != "only_translated":
                        original_text_lines = [f'<font size="{font_size}">{line}</font>' for line in original_text_lines]

                    original_text = "\n".join(original_text_lines)

                    # 应用格式到翻译文本
                    first_line_template = sub['lines'][0]['template'] if sub['lines'] else '{}'
                    final_translated_text_with_tags = first_line_template.format(translated_text) if translated_text else ""

                    # 构建输出
                    output_chunk = f"{sub['index']}\n{sub['time']}\n"
                    
                    if display_mode == "only_translated":
                        output_chunk += f"{final_translated_text_with_tags}\n\n"
                    elif display_mode == "original_above_translated":
                        output_chunk += f"{original_text}\n{final_translated_text_with_tags}\n\n"
                    elif display_mode == "translated_above_original":
                        output_chunk += f"{final_translated_text_with_tags}\n{original_text}\n\n"
                    
                    yield output_chunk
        
        yield "[STATUS] 翻译完成！"
        
    except Exception as e:
        logger.error(f"翻译过程中出错: {e}")
        yield f"[STATUS] 翻译失败: {str(e)}"

# API端点
@app.get("/", response_model=APIStatus)
async def root():
    """根端点 - 返回API状态"""
    return APIStatus(
        status="active",
        message="SRT翻译API正在运行",
        timestamp=datetime.now().isoformat(),
        version="2.0.0"
    )

@app.get("/health")
async def health_check():
    """健康检查端点"""
    api_status = "正常" if model else "API未配置"
    return {
        "status": "healthy",
        "api_status": api_status,
        "timestamp": datetime.now().isoformat(),
        "supported_languages": list(SUPPORTED_LANGUAGES.keys()),
        "quality_modes": list(QUALITY_MODES.keys())
    }

@app.get("/languages")
async def get_supported_languages():
    """获取支持的语言列表"""
    return {
        "languages": SUPPORTED_LANGUAGES,
        "default": "Chinese"
    }

@app.get("/stats")
async def get_file_stats_endpoint(file: UploadFile = File(...)):
    """获取文件统计信息"""
    try:
        contents = await file.read()
        srt_content = contents.decode("utf-8-sig")
        stats = get_file_stats(srt_content)
        return JSONResponse(content=stats)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"文件分析失败: {str(e)}")

@app.post("/translate", response_class=JSONResponse)
async def translate_endpoint(
    file: UploadFile = File(...),
    display_mode: str = Query("only_translated", description="显示模式"),
    target_language: str = Query("Chinese", description="目标语言"),
    quality_mode: str = Query("标准", description="质量模式"),
    font_size: Optional[int] = Query(None, description="字体大小"),
    split_long_lines: bool = Query(True, description="是否分割长行"),
    max_line_length: int = Query(40, description="最大行长度")
):
    """批量翻译端点"""
    try:
        contents = await file.read()
        srt_content = contents.decode("utf-8-sig")
        
        # 验证参数
        if target_language not in SUPPORTED_LANGUAGES:
            raise HTTPException(status_code=400, detail=f"不支持的语言: {target_language}")
        
        if quality_mode not in QUALITY_MODES:
            raise HTTPException(status_code=400, detail=f"不支持的质量模式: {quality_mode}")
        
        full_translation = ""
        async for chunk in translate_srt_stream(
            srt_content, display_mode, target_language, quality_mode, 
            font_size, split_long_lines, max_line_length
        ):
            if not chunk.startswith("[STATUS]"):
                full_translation += chunk
        
        return JSONResponse(content={
            "translated_srt": full_translation,
            "source_language": "auto",
            "target_language": target_language,
            "quality_mode": quality_mode,
            "timestamp": datetime.now().isoformat()
        })
        
    except Exception as e:
        logger.error(f"翻译失败: {e}")
        raise HTTPException(status_code=500, detail=f"翻译失败: {str(e)}")

@app.post("/translate-stream")
async def translate_stream_endpoint(
    file: UploadFile = File(...),
    display_mode: str = Query("only_translated", description="显示模式"),
    target_language: str = Query("Chinese", description="目标语言"),
    quality_mode: str = Query("标准", description="质量模式"),
    font_size: Optional[int] = Query(None, description="字体大小"),
    split_long_lines: bool = Query(True, description="是否分割长行"),
    max_line_length: int = Query(40, description="最大行长度")
):
    """流式翻译端点"""
    try:
        contents = await file.read()
        srt_content = contents.decode("utf-8-sig")
        
        # 验证参数
        if target_language not in SUPPORTED_LANGUAGES:
            raise HTTPException(status_code=400, detail=f"不支持的语言: {target_language}")
        
        if quality_mode not in QUALITY_MODES:
            raise HTTPException(status_code=400, detail=f"不支持的质量模式: {quality_mode}")
        
        return StreamingResponse(
            translate_srt_stream(
                srt_content, display_mode, target_language, quality_mode,
                font_size, split_long_lines, max_line_length
            ),
            media_type="text/plain; charset=utf-8"
        )
        
    except Exception as e:
        logger.error(f"流式翻译失败: {e}")
        raise HTTPException(status_code=500, detail=f"流式翻译失败: {str(e)}")

@app.post("/validate")
async def validate_srt_endpoint(file: UploadFile = File(...)):
    """验证SRT文件格式"""
    try:
        contents = await file.read()
        srt_content = contents.decode("utf-8-sig")
        
        subtitles = parse_srt(srt_content)
        stats = get_file_stats(srt_content)
        
        return JSONResponse(content={
            "valid": len(subtitles) > 0,
            "subtitle_count": len(subtitles),
            "stats": stats,
            "message": "SRT文件格式有效" if len(subtitles) > 0 else "SRT文件格式无效"
        })
        
    except Exception as e:
        return JSONResponse(content={
            "valid": False,
            "error": str(e),
            "message": "文件验证失败"
        })

# 错误处理器
@app.exception_handler(404)
async def not_found_handler(request, exc):
    return JSONResponse(
        status_code=404,
        content={"message": "API端点不存在", "timestamp": datetime.now().isoformat()}
    )

@app.exception_handler(500)
async def internal_error_handler(request, exc):
    logger.error(f"内部服务器错误: {exc}")
    return JSONResponse(
        status_code=500,
        content={"message": "内部服务器错误", "timestamp": datetime.now().isoformat()}
    )

if __name__ == "__main__":
    import uvicorn
    
    # 检查环境变量
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
