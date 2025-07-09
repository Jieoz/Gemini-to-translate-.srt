from fastapi import FastAPI, HTTPException, File, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from dotenv import load_dotenv
import os
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
from typing import List, AsyncGenerator, Dict
import re
import asyncio
import time

load_dotenv()

# --- 核心优化参数 ---
# 根据您的要求，将批次大小调回16，以实现最佳的API调用经济性。
INITIAL_BATCH_SIZE = 16

# 创建 FastAPI 应用实例
app = FastAPI()

# 配置 Gemini API
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel('gemini-2.0-flash')

# 关闭安全过滤器
SAFETY_SETTINGS = {
        HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE
}


# --- 优化后的批处理 Prompt (V8 - Final) ---
# 移除了合并指令，并用更强的语气禁止合并，强制进行独立翻译。
BATCH_TRANSLATION_PROMPT = """
You are a subtitle translation machine. Your task is to translate a batch of subtitles into Chinese with maximum fidelity.

**CRITICAL RULES - FOLLOW WITH 100% PRECISION:**
1.  **ONE-TO-ONE TRANSLATION:** You MUST translate each `[index]` line from the input INDEPENDENTLY.
2.  **NO MERGING:** Do NOT merge the meaning of multiple input lines into a single translation. Even if two lines are similar, they must be translated separately.
3.  **PRESERVE INDEX:** For each input line `[index] text`, you MUST return a corresponding line `[index] <translation>`. The index number is critical.
4.  **VERIFY COUNT:** The number of `[index]` lines in your output must EXACTLY match the number of `[index]` lines in the input.

**Example of Correct Independent Translation:**
*Input:*
[95] who honed his wine making skills
[96] in Australia and the US
*Your Correct Output:*
[95] 他磨练了他的酿酒技巧
[96] 在澳大利亚和美国

**Example of FORBIDDEN Merging:**
*Input:*
[95] who honed his wine making skills
[96] in Australia and the US
*Your INCORRECT Output:*
[95] 他在澳大利亚和美国磨练了他的酿酒技巧
[96] 他在澳大利亚和美国磨练了他的酿酒技巧

Now, process the following batch, ensuring each line is translated independently:
{subtitle_batch}
"""


def parse_srt(srt_content: str) -> List[Dict]:
    """Parses an SRT file content and returns a list of subtitle dictionaries."""
    lines = srt_content.strip().split("\n")
    subtitles = []
    i = 0
    while i < len(lines):
        try:
            if lines[i].strip().isdigit():
                index = int(lines[i].strip())
                i += 1
                time_str = lines[i]
                i += 1
                text_lines = []
                while i < len(lines) and lines[i].strip() != "":
                    text_lines.append(lines[i])
                    i += 1
                text = "\n".join(text_lines)
                subtitles.append({
                    "index": index,
                    "time": time_str,
                    "text": text
                })
                i += 1
            else:
                i += 1
        except (ValueError, IndexError):
            i += 1
            continue
    return subtitles

async def _api_call_with_retry(prompt: str) -> str:
    """A helper function to make API calls with exponential backoff."""
    retries = 3
    delay = 5
    for attempt in range(retries):
        try:
            response = await model.generate_content_async(prompt, safety_settings=SAFETY_SETTINGS)
            return response.text.strip()
        except Exception as e:
            if "429" in str(e) and attempt < retries - 1:
                print(f"Rate limit hit, retrying in {delay}s... (Attempt {attempt + 2}/{retries})")
                await asyncio.sleep(delay)
                delay *= 2
            else:
                print(f"API call failed after all retries: {e}")
                return "API_CALL_FAILED"
    return "API_CALL_FAILED"


async def translate_batch_and_parse(sub_batch: List[Dict]) -> Dict[int, str]:
    """
    Translates a batch and parses the result into a dictionary of {index: translation}.
    """
    batch_input_text = ""
    for sub in sub_batch:
        cleaned_text = sub['text'].replace('\n', ' ').strip()
        batch_input_text += f"[{sub['index']}] {cleaned_text}\n"
    
    prompt = BATCH_TRANSLATION_PROMPT.format(subtitle_batch=batch_input_text)
    response_text = await _api_call_with_retry(prompt)

    if response_text == "API_CALL_FAILED":
        return {}

    # 解析返回的结果，构建一个 {index: translation} 的字典
    translation_map = {}
    # 正则表达式匹配 [数字] 后面的所有内容
    pattern = re.compile(r'\[(\d+)\]\s*(.*)')
    for line in response_text.split('\n'):
        match = pattern.match(line.strip())
        if match:
            index = int(match.group(1))
            translation = match.group(2).strip()
            translation_map[index] = translation
            
    return translation_map


async def translate_srt_stream(srt_content: str, display_mode: str = "only_translated") -> AsyncGenerator[str, None]:
    """
    使用自适应批处理和流式响应高效地翻译SRT文件。
    """
    subtitles = parse_srt(srt_content)
    
    for i in range(0, len(subtitles), INITIAL_BATCH_SIZE):
        batch_subtitles = subtitles[i:i + INITIAL_BATCH_SIZE]
        
        status_message = f"[STATUS] 正在翻译批次 (字幕 {batch_subtitles[0]['index']} 到 {batch_subtitles[-1]['index']})... 请稍候。"
        yield status_message

        # 获取包含索引的翻译字典
        translation_map = await translate_batch_and_parse(batch_subtitles)

        output_srt_batch = ""
        for sub in batch_subtitles:
            # 从字典中按索引查找翻译，如果找不到，则使用原文作为后备
            translated_text = translation_map.get(sub['index'], sub['text'].replace('\n', ' ').strip())
            
            if display_mode == "only_translated":
                output_srt_batch += f"{sub['index']}\n{sub['time']}\n{translated_text}\n\n"
            elif display_mode == "original_above_translated":
                output_srt_batch += f"{sub['index']}\n{sub['time']}\n{sub['text']}\n{translated_text}\n\n"
            elif display_mode == "translated_above_original":
                output_srt_batch += f"{sub['index']}\n{sub['time']}\n{translated_text}\n{sub['text']}\n\n"
        
        yield output_srt_batch


@app.post("/translate", response_class=JSONResponse)
async def translate_endpoint(file: UploadFile = File(...), display_mode: str = "only_translated"):
    try:
        contents = await file.read()
        srt_content = contents.decode("utf-8")
        
        full_translation = ""
        async for chunk in translate_srt_stream(srt_content, display_mode):
            if not chunk.startswith("[STATUS]"):
                full_translation += chunk
            
        return JSONResponse(content={"translated_srt": full_translation})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/translate-stream")
async def translate_stream_endpoint(file: UploadFile = File(...), display_mode: str = "only_translated"):
    try:
        contents = await file.read()
        srt_content = contents.decode("utf-8")
        return StreamingResponse(translate_srt_stream(srt_content, display_mode), media_type="text/plain; charset=utf-8")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
