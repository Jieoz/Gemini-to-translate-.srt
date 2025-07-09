from fastapi import FastAPI, HTTPException, File, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from dotenv import load_dotenv
import os
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
from typing import List, AsyncGenerator, Dict
import re
import asyncio

load_dotenv()

# --- FastAPI App Initialization ---
app = FastAPI()

# --- Core Optimization Parameter ---
GROUP_BATCH_SIZE = 20

# --- Gemini API Configuration ---
try:
    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
    model = genai.GenerativeModel('gemini-2.0-flash')
except Exception as e:
    print(f"Error configuring Gemini API: {e}")
    model = None

# Safety settings
SAFETY_SETTINGS = {
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
}

# --- Final Prompt for Batching Groups (V21 - Context-Aware Single Line Output) ---
# This version translates a whole sentence, then allocates the translation back to single-line entries.
MULTI_GROUP_BATCH_PROMPT_V21 = """
You are a world-class subtitle translation expert. Your task is to translate sentence groups into fluent, single-line Chinese subtitles, maintaining the original entry structure.

**CRITICAL INSTRUCTIONS - FOLLOW WITH 100% PRECISION:**
1.  **PROCESS BY GROUP:** The input contains sentence groups marked by `[GROUP START]` and `[GROUP END]`. Treat each group as one complete thought.
2.  **COMBINE & TRANSLATE:** For each group, mentally combine the text from all `[index]` lines to understand the full sentence. Translate this entire sentence into a single, high-quality, natural-sounding Chinese sentence.
3.  **ALLOCATE & OUTPUT:** Now, intelligently allocate parts of your complete translation back to the original `[index]` numbers. Each `[index]` in your output must correspond to an `[index]` in the input group.
    * **SINGLE LINE RULE:** The translated text for each `[index]` MUST be a single, continuous line without any line breaks (`\n`).
    * **LOGICAL ALLOCATION:** The text you allocate to each index should logically correspond to the original text for that index.
4.  **PRESERVE ALL INDEXES:** Your output must contain every single `[index]` from the input batch, each on a new line.

**EXAMPLE:**
*Input:*
[GROUP START]
[33] some of these carriages were built in the 1920s and offer those lucky
[34] enough to get a ticket a level of comfort
[35] almost unrivalled anywhere in the world.
[GROUP END]

*Your Correct, Single-Line Output:*
[33] 其中一些车厢建于20世纪20年代，为那些幸运的乘客
[34] 提供了一种近乎无与伦比的舒适体验
[35] 这在世界上的任何地方都难得一见。

Now, process the following batch of groups, applying these rules meticulously:
{subtitle_batch_text}
"""

def strip_tags(text: str) -> str:
    """Removes SRT/ASS/HTML style tags from a string."""
    return re.sub(r'\{.*?\}|<.*?>', '', text).strip()

def create_template_and_clean_text(original_line: str) -> Dict[str, str]:
    """
    Creates a format-safe template and extracts clean text.
    This version correctly escapes curly braces in formatting tags to prevent KeyErrors.
    """
    clean_text = strip_tags(original_line)
    template = original_line
    
    if clean_text:
        # Use a unique placeholder that won't be in the text
        placeholder = "___TRANSLATION_PLACEHOLDER___"
        
        # Replace the first occurrence of clean_text with the unique placeholder
        try:
            template = re.sub(re.escape(clean_text), placeholder, template, 1)
        except re.error:
            # Fallback for rare regex errors
            template = template.replace(clean_text, placeholder, 1)

        # Now, escape all curly braces in the entire template
        template = template.replace('{', '{{').replace('}', '}}')
        
        # Finally, replace the unique placeholder with the actual, unescaped format placeholder
        template = template.replace(placeholder, '{}')
    else:
        # If there is no text, just escape any braces in the tags to be safe
        template = template.replace('{', '{{').replace('}', '}}')

    return {"clean": clean_text, "template": template}


def parse_srt(srt_content: str) -> List[Dict]:
    """
    Parses SRT content, handling multi-line entries and format tags.
    This version correctly handles tags and prepares data for context-aware translation.
    """
    lines = srt_content.strip().split("\n")
    subtitles = []
    i = 0
    while i < len(lines):
        try:
            if lines[i].strip().isdigit():
                index = int(lines[i].strip())
                i += 1
                time_str = lines[i]
                if "-->" not in time_str: continue
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
        except (ValueError, IndexError):
            i += 1
            continue
    return subtitles

def group_subtitles_by_sentence(subtitles: List[Dict]) -> List[List[Dict]]:
    """Groups subtitles based on the combined clean text of their lines."""
    if not subtitles:
        return []
    groups = []
    current_group = []
    sentence_enders = ('.', '?', '!', '."')
    for sub in subtitles:
        full_clean_text = " ".join([line['clean'] for line in sub['lines']]).strip()
        current_group.append(sub)
        if full_clean_text.endswith(sentence_enders) or (full_clean_text.isupper() and full_clean_text):
            groups.append(current_group)
            current_group = []
    if current_group:
        groups.append(current_group)
    return groups

async def _api_call_with_retry(prompt: str) -> str:
    """Helper function for API calls with exponential backoff."""
    if not model: return "API_CONFIGURATION_ERROR"
    retries = 3
    delay = 5
    for attempt in range(retries):
        try:
            response = await model.generate_content_async(
                prompt,
                safety_settings=SAFETY_SETTINGS,
                generation_config=genai.types.GenerationConfig(temperature=0.7)
            )
            return response.text.strip()
        except Exception as e:
            if "429" in str(e) and attempt < retries - 1:
                print(f"Rate limit hit, retrying in {delay}s...")
                await asyncio.sleep(delay)
                delay *= 2
            else:
                print(f"API call failed: {e}")
                return "API_CALL_FAILED"
    return "API_CALL_FAILED"

async def translate_batch_of_groups_and_parse(batch_of_groups: List[List[Dict]]) -> Dict[int, str]:
    """Constructs a prompt for groups, calls API, and parses the response."""
    batch_input_text = ""
    original_text_map = {}
    for group in batch_of_groups:
        batch_input_text += "[GROUP START]\n"
        for sub in group:
            # Join the clean text from all lines of the subtitle entry
            clean_text = " ".join([line['clean'] for line in sub['lines']])
            batch_input_text += f"[{sub['index']}] {clean_text}\n"
            original_text_map[sub['index']] = clean_text
        batch_input_text += "[GROUP END]\n"

    prompt = MULTI_GROUP_BATCH_PROMPT_V21.format(subtitle_batch_text=batch_input_text)
    response_text = await _api_call_with_retry(prompt)

    if response_text in ("API_CALL_FAILED", "API_CONFIGURATION_ERROR"):
        return original_text_map

    translation_map = {}
    pattern = re.compile(r'\[(\d+)\]\s*(.*)')
    for line in response_text.split('\n'):
        match = pattern.match(line.strip())
        if match:
            index = int(match.group(1))
            translation = match.group(2).strip()
            if translation:
                translation_map[index] = translation

    # Fallback for any missed indexes
    for group in batch_of_groups:
        for sub in group:
            if sub['index'] not in translation_map:
                print(f"Warning: Index {sub['index']} not in response. Using original text.")
                translation_map[sub['index']] = original_text_map.get(sub['index'], "")

    return translation_map

async def translate_srt_stream(srt_content: str, display_mode: str = "only_translated") -> AsyncGenerator[str, None]:
    """Main orchestrator: processes groups for context-aware, single-line output."""
    original_subtitles = parse_srt(srt_content)
    subtitle_groups = group_subtitles_by_sentence(original_subtitles)
    
    total_groups = len(subtitle_groups)
    for i in range(0, total_groups, GROUP_BATCH_SIZE):
        batch_of_groups = subtitle_groups[i:i + GROUP_BATCH_SIZE]
        if not batch_of_groups: continue

        start_index = batch_of_groups[0][0]['index']
        end_index = batch_of_groups[-1][-1]['index']
        status_message = f"[STATUS] 正在翻译批次 (字幕 {start_index} 到 {end_index})..."
        yield status_message

        translation_map = await translate_batch_of_groups_and_parse(batch_of_groups)

        for group in batch_of_groups:
            for sub in group:
                translated_text = translation_map.get(sub['index'], "").replace('\n', ' ').strip()
                
                # Reconstruct original text with tags from templates
                original_text_lines = [line['template'].format(line['clean']) for line in sub['lines']]
                original_text = "\n".join(original_text_lines)

                # Reconstruct translated text with tags, but as a single line
                # We apply the full translation to the first line's template and leave others empty
                # A more sophisticated approach might be needed if tags are complex
                first_line_template = sub['lines'][0]['template'] if sub['lines'] else '{}'
                final_translated_text_with_tags = first_line_template.format(translated_text)

                output_chunk = f"{sub['index']}\n{sub['time']}\n"
                if display_mode == "only_translated":
                    output_chunk += f"{final_translated_text_with_tags}\n\n"
                elif display_mode == "original_above_translated":
                    output_chunk += f"{original_text}\n{final_translated_text_with_tags}\n\n"
                elif display_mode == "translated_above_original":
                    output_chunk += f"{final_translated_text_with_tags}\n{original_text}\n\n"
                
                yield output_chunk
    
    yield "[STATUS] 全部翻译完成！"

# --- FastAPI Endpoints ---
@app.post("/translate", response_class=JSONResponse)
async def translate_endpoint(file: UploadFile = File(...), display_mode: str = "only_translated"):
    try:
        contents = await file.read()
        srt_content = contents.decode("utf-8-sig")
        full_translation = ""
        async for chunk in translate_srt_stream(srt_content, display_mode):
            if not chunk.startswith("[STATUS]"):
                full_translation += chunk
        return JSONResponse(content={"translated_srt": full_translation})
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An error occurred: {str(e)}")

@app.post("/translate-stream")
async def translate_stream_endpoint(file: UploadFile = File(...), display_mode: str = "only_translated"):
    try:
        contents = await file.read()
        srt_content = contents.decode("utf-8-sig")
        return StreamingResponse(translate_srt_stream(srt_content, display_mode), media_type="text/plain; charset=utf-8")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An error occurred: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    if not os.getenv("GEMINI_API_KEY"):
        print("FATAL ERROR: GEMINI_API_KEY environment variable not found.")
    else:
        uvicorn.run(app, host="0.0.0.0", port=8000)
