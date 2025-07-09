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
# Number of sentence groups to batch into a single API call.
# This is the key parameter for cost optimization.
# A larger number means fewer API calls but a larger prompt for each call.
# 15 is a balanced starting point.
GROUP_BATCH_SIZE = 20

# --- Gemini API Configuration ---
try:
    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
    # Using a powerful model is important for complex instructions like this.
    model = genai.GenerativeModel('gemini-2.0-flash')
except Exception as e:
    print(f"Error configuring Gemini API: {e}")
    model = None

# Safety settings to allow a wider range of content
SAFETY_SETTINGS = {
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
}

# --- New Prompt for Batching Multiple Groups (V10 - Cost Optimized) ---
# This prompt instructs the model to handle multiple, independent sentence groups in one go.
MULTI_GROUP_BATCH_PROMPT = """
You are an expert subtitle translator. Your task is to translate a batch of distinct subtitle groups into fluent, natural Chinese.

**CRITICAL INSTRUCTIONS - FOLLOW WITH 100% PRECISION:**
1.  **INDEPENDENT GROUPS:** The input contains multiple, separate sentence groups. Each group is enclosed by `[GROUP START]` and `[GROUP END]`. You MUST treat each group as a completely independent translation task. DO NOT merge context or meaning between different groups.
2.  **FOR EACH GROUP INDIVIDUALLY:**
    a. **COMBINE:** Mentally combine the text from all `[index]` lines within that single group to understand the full sentence.
    b. **TRANSLATE:** Translate the complete sentence into high-quality, natural-sounding Chinese.
    c. **RE-SPLIT:** Intelligently distribute your single translated sentence back across the original `[index]` lines for that group. The number of output `[index]` lines for a group must EXACTLY match the number of input `[index]` lines for that same group.
3.  **PRESERVE ALL INDEXES:** The `[index]` number is critical. Your output must contain every single `[index]` from the input, each on a new line.
4.  **OUTPUT FORMAT:** Only output the `[index] <translation>` lines. Do not include group markers (`[GROUP START]`, `[GROUP END]`) or any other explanatory text in your response.

**Example:**
*Input:*
[GROUP START]
[95] who honed his wine making skills
[96] in Australia and the US
[GROUP END]
[GROUP START]
[97] It is a beautiful day.
[GROUP END]

*Your Correct Output:*
[95] 他磨练了他的酿酒技巧
[96] 在澳大利亚和美国
[97] 今天天气真好。

Now, process the following batch of groups, ensuring each group is translated independently:
{subtitle_batch_text}
"""


def parse_srt(srt_content: str) -> List[Dict]:
    """Parses SRT file content into a list of subtitle dictionaries."""
    # This function remains robust for parsing standard SRT format.
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
                text_lines = []
                while i < len(lines) and lines[i].strip() != "":
                    text_lines.append(lines[i])
                    i += 1
                text = "\n".join(text_lines)
                subtitles.append({"index": index, "time": time_str, "text": text})
                i += 1
            else:
                i += 1
        except (ValueError, IndexError):
            i += 1
            continue
    return subtitles

def group_subtitles_by_sentence(subtitles: List[Dict]) -> List[List[Dict]]:
    """
    Groups subtitles that likely form a complete sentence. This is key for quality.
    """
    if not subtitles:
        return []
    groups = []
    current_group = []
    sentence_enders = ('.', '?', '!', '."')
    for sub in subtitles:
        cleaned_text = sub['text'].replace('\n', ' ').strip()
        current_group.append(sub)
        if cleaned_text.endswith(sentence_enders) or (cleaned_text.isupper() and cleaned_text):
            groups.append(current_group)
            current_group = []
    if current_group:
        groups.append(current_group)
    return groups


async def _api_call_with_retry(prompt: str) -> str:
    """A helper function to make API calls with exponential backoff."""
    if not model:
        return "API_CONFIGURATION_ERROR"
    retries = 3
    delay = 5
    for attempt in range(retries):
        try:
            response = await model.generate_content_async(
                prompt,
                safety_settings=SAFETY_SETTINGS,
                generation_config=genai.types.GenerationConfig(temperature=0.5)
            )
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

async def translate_batch_of_groups_and_parse(batch_of_groups: List[List[Dict]]) -> Dict[int, str]:
    """
    Constructs a prompt for a batch of groups, makes a single API call,
    and parses the entire response.
    """
    batch_input_text = ""
    original_text_map = {}
    # Combine multiple groups into one large text block for the prompt
    for group in batch_of_groups:
        batch_input_text += "[GROUP START]\n"
        for sub in group:
            cleaned_text = sub['text'].replace('\n', ' ').strip()
            batch_input_text += f"[{sub['index']}] {cleaned_text}\n"
            original_text_map[sub['index']] = cleaned_text
        batch_input_text += "[GROUP END]\n"

    prompt = MULTI_GROUP_BATCH_PROMPT.format(subtitle_batch_text=batch_input_text)
    response_text = await _api_call_with_retry(prompt)

    # Fallback mechanism: if API fails, return original text for the whole batch
    if response_text in ("API_CALL_FAILED", "API_CONFIGURATION_ERROR"):
        return original_text_map

    # Parse the entire response text for all groups in the batch
    translation_map = {}
    pattern = re.compile(r'\[(\d+)\]\s*(.*)')
    for line in response_text.split('\n'):
        match = pattern.match(line.strip())
        if match:
            index = int(match.group(1))
            translation = match.group(2).strip()
            if translation:
                translation_map[index] = translation

    # Verification and fallback for any missed indexes within the batch
    for group in batch_of_groups:
        for sub in group:
            if sub['index'] not in translation_map:
                print(f"Warning: Index {sub['index']} not found in batch response. Using original text.")
                translation_map[sub['index']] = original_text_map[sub['index']]

    return translation_map


async def translate_srt_stream(srt_content: str, display_mode: str = "only_translated") -> AsyncGenerator[str, None]:
    """
    The main translation orchestrator. Groups subtitles, batches the groups,
    translates batch by batch, and streams the results.
    """
    original_subtitles = parse_srt(srt_content)
    subtitle_groups = group_subtitles_by_sentence(original_subtitles)
    
    total_groups = len(subtitle_groups)
    # Process the groups in batches of GROUP_BATCH_SIZE
    for i in range(0, total_groups, GROUP_BATCH_SIZE):
        batch_of_groups = subtitle_groups[i:i + GROUP_BATCH_SIZE]
        
        start_index = batch_of_groups[0][0]['index']
        end_index = batch_of_groups[-1][-1]['index']
        status_message = f"[STATUS] 正在翻译批次 (字幕 {start_index} 到 {end_index})..."
        yield status_message

        # Make one API call for the entire batch of groups
        translation_map = await translate_batch_of_groups_and_parse(batch_of_groups)

        # Yield the processed SRT for each group within the completed batch
        for group in batch_of_groups:
            output_srt_chunk = ""
            for sub in group:
                translated_text = translation_map.get(sub['index'], sub['text'].replace('\n', ' ').strip())
                output_srt_chunk += f"{sub['index']}\n{sub['time']}\n"
                if display_mode == "only_translated":
                    output_srt_chunk += f"{translated_text}\n\n"
                elif display_mode == "original_above_translated":
                    output_srt_chunk += f"{sub['text']}\n{translated_text}\n\n"
                elif display_mode == "translated_above_original":
                    output_srt_chunk += f"{translated_text}\n{sub['text']}\n\n"
            yield output_srt_chunk
    
    yield "[STATUS] 全部翻译完成！"


@app.post("/translate", response_class=JSONResponse)
async def translate_endpoint(file: UploadFile = File(...), display_mode: str = "only_translated"):
    """Endpoint for a full, non-streamed translation. It waits for all chunks."""
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
    """Endpoint for streaming the translation results back to the client in real-time."""
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
        print("Please create a .env file and add your API key to it.")
    else:
        uvicorn.run(app, host="0.0.0.0", port=8000)
