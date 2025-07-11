from fastapi import FastAPI, HTTPException, File, UploadFile, Query
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
import os
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
from typing import List, AsyncGenerator, Dict, Optional, Tuple
import re
import asyncio
import logging
from datetime import datetime
import uvicorn

# 加载环境变量
load_dotenv()

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# FastAPI应用初始化
app = FastAPI(
    title="SRT翻译API",
    description="支持多语言字幕翻译和智能断句的API服务",
    version="6.4.1" # 修复parse_srt函数的语法错误
)

# 中间件配置
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)

# --- 核心配置 ---
MAX_CHARS_PER_BATCH = 8000
MAX_RETRIES = 3
RATE_LIMIT_DELAY = 5
API_TIMEOUT_SECONDS = 120 
SPLIT_BATCH_TOKEN_LIMIT = 8000 

# --- 数据映射与API配置 ---
SUPPORTED_LANGUAGES = {"Simplified Chinese":"简体中文", "English":"英文", "Japanese":"日文", "Korean":"韩文", "French":"法文", "German":"德文", "Spanish":"西班牙文", "Italian":"意大利文", "Russian":"俄文", "Arabic":"阿拉伯文"}
QUALITY_MODES = {"快速":{"temperature":0.3,"max_tokens":4096},"标准":{"temperature":0.7,"max_tokens":6144},"高质量":{"temperature":0.9,"max_tokens":8192}}
SUPPORTED_MODELS = ["gemini-2.0-flash", "gemini-1.5-flash", "gemini-1.5-pro"]
try:
    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
    logger.info("Gemini API Key配置成功")
except Exception as e:
    logger.error(f"Gemini API Key配置失败: {e}")
SAFETY_SETTINGS = {
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
}

# --- 时间与文本处理函数 ---
def parse_time(t):
    try: h,m,s,ms=map(int,re.split('[:,]',t)); return ms+1e3*s+6e4*m+3.6e6*h
    except: return 0
def format_time(ms):
    h,r=divmod(ms,3.6e6); m,r=divmod(r,6e4); s,ms=divmod(r,1e3)
    return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{int(ms):03d}"
def parse_time_range(tr):
    try: s,e=tr.split(' --> '); return parse_time(s),parse_time(e)
    except: return 0,0
def format_time_range(s,e): return f"{format_time(s)} --> {format_time(e)}"
def strip_tags(t): return re.sub(r'\{.*?\}|<.*?>','',t).strip()
def create_template_and_clean_text(ol):
    ct=strip_tags(ol); t=ol; p="___PLACEHOLDER___"
    if ct:
        try: t=re.sub(re.escape(ct),p,t,1)
        except: t=t.replace(ct,p,1)
    t=t.replace('{','{{').replace('}','}}').replace(p,'{}')
    return {"clean":ct,"template":t}

# [语法修正] 替换为健壮的SRT解析函数
def parse_srt(srt_content: str) -> List[Dict]:
    lines = srt_content.strip().replace('\r', '').split("\n")
    subtitles = []
    i = 0
    while i < len(lines):
        try:
            line_content = lines[i].strip()
            # 检查当前行是否为纯数字（即字幕序号）
            if line_content.isdigit():
                index = int(line_content)
                i += 1
                # 检查下一行是否为时间轴
                if i >= len(lines) or "-->" not in lines[i]:
                    continue # 如果不是，说明格式错误，跳过这个块
                
                time_str = lines[i]
                i += 1
                
                # 读取所有文本行，直到遇到空行
                text_lines_raw = []
                while i < len(lines) and lines[i].strip() != "":
                    text_lines_raw.append(lines[i])
                    i += 1
                
                processed_lines = [create_template_and_clean_text(raw_line) for raw_line in text_lines_raw if raw_line.strip()]
                if processed_lines:
                    subtitles.append({"index": index, "time": time_str, "lines": processed_lines})
                
                # 跳过字幕块之间的空行
                while i < len(lines) and lines[i].strip() == "":
                    i += 1
            else:
                # 如果当前行不是数字，说明它不是一个合法的字幕块开头，跳过
                i += 1
        except Exception as e:
            # 如果任何其他错误发生（如索引越界），记录警告并安全地推进循环
            logger.warning(f"解析SRT时跳过一个无效块: {e} at line index {i}")
            i += 1
    return subtitles

def group_subtitles_by_sentence(subs):
    if not subs: return []
    grps,cg=[],[]; enders=('.','?','!',"''",'""','。','！','？')
    for s in subs:
        t=" ".join([l['clean'] for l in s['lines']]).strip()
        cg.append(s)
        if t.endswith(enders) or len(cg)>=5: grps.append(cg); cg=[]
    if cg: grps.append(cg)
    return grps

async def api_call_with_retry(p,qm,mn):
    if not os.getenv("GEMINI_API_KEY"): return "API_KEY_MISSING_ERROR"
    cfg=QUALITY_MODES.get(qm,QUALITY_MODES["标准"]); ro={"timeout":API_TIMEOUT_SECONDS}
    try: mdl=genai.GenerativeModel(mn)
    except: return f"INVALID_MODEL_NAME_ERROR:{mn}"
    for att in range(MAX_RETRIES):
        try:
            resp=await mdl.generate_content_async(p,safety_settings=SAFETY_SETTINGS,generation_config=genai.types.GenerationConfig(temperature=cfg["temperature"],max_output_tokens=cfg["max_tokens"]),request_options=ro)
            return resp.text.strip() if resp.text else "EMPTY_RESPONSE"
        except Exception as e:
            emsg=str(e); logger.error(f"API调用失败(att {att+1}/{MAX_RETRIES}): {emsg}")
            if "DeadlineExceeded" in emsg or "Timeout" in emsg: return f"API_TIMEOUT_ERROR:{API_TIMEOUT_SECONDS}秒"
            if att<MAX_RETRIES-1: await asyncio.sleep(RATE_LIMIT_DELAY*(2**att))
            else: return f"API_CALL_FAILED:{emsg}"
    return "API_CALL_FAILED:重试次数已用尽。"
def get_translation_prompt(tl,qm):
    ln=SUPPORTED_LANGUAGES.get(tl,"简体中文")
    return f"Translate subtitle groups into {ln}. CRITICAL RULE:You MUST provide a translation for EACH `[index]` in the input group. Intelligently distribute the full translation across all original `[index]` lines. Input format:[GROUP START][index1] text1 [index2] text2 [GROUP END]. Your output MUST be in the format:[index1] translation1 [index2] translation2. Input:\n{{subtitle_batch_text}}"
async def split_text_simple(t,np,qm,mn):
    p=f"Split the following text into {np} natural parts. Each part on a new line. No extra text or labels. Text:\"{t}\""; resp=await api_call_with_retry(p,qm,mn)
    if any(err in resp for err in ["FAILED","ERROR","EMPTY"]):
        pl=len(t)//np; return [t[i*pl:(i+1)*pl] for i in range(np-1)]+[t[(np-1)*pl:]]
    return [l.strip() for l in resp.strip().split('\n') if l.strip()]

async def translate_batch_of_groups_and_parse(bog,tl,qm,mn):
    txt,omap,pt={},{},get_translation_prompt(tl,qm)
    p_txt=""
    for grp in bog:
        p_txt+="[GROUP START]\n"
        for sub in grp:
            cl=" ".join([l['clean'] for l in sub['lines']]); p_txt+=f"[{sub['index']}] {cl}\n"; omap[sub['index']]=cl
        p_txt+="[GROUP END]\n"
    resp=await api_call_with_retry(pt.format(subtitle_batch_text=p_txt),qm,mn)
    if any(err in resp for err in ["FAILED","ERROR","EMPTY","MISSING"]): return {s['index']:omap.get(s['index'],"") for g in bog for s in g}
    tmap={int(m.group(1)):re.sub(r'\[\d+\]','',m.group(2)).strip() for m in re.finditer(r'\[(\d+)\]\s*(.*)',resp) if m.group(2).strip()}
    for grp in bog:
        g_idxs=[s['index'] for s in grp]; t_idxs=[i for i in g_idxs if i in tmap]
        if len(g_idxs)>1 and len(t_idxs)==1:
            s_t_idx=t_idxs[0]; l_trans=tmap[s_t_idx]; n_parts=len(g_idxs)
            try:
                s_trans=await split_text_simple(l_trans,n_parts,qm,mn)
                if len(s_trans)==n_parts:
                    for i,idx_u in enumerate(g_idxs): tmap[idx_u]=s_trans[i]
            except: pass
    for grp in bog:
        for sub in grp:
            if sub['index'] not in tmap: tmap[sub['index']]=omap.get(sub['index'],"")
    return tmap

def get_batch_split_prompt(batch: List[Dict], final_translation_map: Dict) -> Tuple[str, Dict, int]:
    prompt_text = "You are an expert subtitle editor. For each sentence pair below, split BOTH the original and translated text into the specified number of parts. The split must be at natural pauses, and corresponding parts must be accurate translations of each other.\n\n"
    metadata = {}; estimated_tokens = len(prompt_text) / 2.5
    for i, sub in enumerate(batch):
        original_text = " ".join([line['clean'] for line in sub['lines']])
        translated_text = final_translation_map.get(sub['index'], "")
        if not translated_text: continue
        start_ms, end_ms = parse_time_range(sub['time'])
        duration_sec = (end_ms - start_ms) / 1000.0
        num_parts = max(2, min(4, int(duration_sec / 4.0)))
        task_text = f"--- TASK {i+1} ---\nSPLIT_INTO: {num_parts}\n[ORIGINAL-{i+1}]\n{original_text}\n[TRANSLATED-{i+1}]\n{translated_text}\n\n"
        prompt_text += task_text
        estimated_tokens += len(task_text) / 2.5
        metadata[i+1] = {"original_index": sub['index'], "num_parts": num_parts}
    prompt_text += "Provide the results strictly in the following format for all tasks:\n[SPLIT-TaskNum-ORIGINAL-PartNum] text\n[SPLIT-TaskNum-TRANSLATED-PartNum] text"
    estimated_tokens += len("Provide the results...") / 2.5
    return prompt_text, metadata, int(estimated_tokens)

def parse_batch_split_response(response_text: str, metadata: Dict) -> Dict:
    split_results = {}
    for task_num, meta in metadata.items():
        split_originals = [""] * meta['num_parts']; split_translations = [""] * meta['num_parts']
        for line in response_text.split('\n'):
            line = line.strip()
            match = re.match(r'\[SPLIT-(\d+)-(ORIGINAL|TRANSLATED)-(\d+)\]\s*(.*)', line)
            if match:
                res_task_num, lang, res_part_num, text = int(match.group(1)), match.group(2), int(match.group(3)), match.group(4)
                if res_task_num == task_num and 1 <= res_part_num <= meta['num_parts']:
                    if lang == "ORIGINAL": split_originals[res_part_num - 1] = text
                    elif lang == "TRANSLATED": split_translations[res_part_num - 1] = text
        if all(split_originals) and all(split_translations): split_results[meta['original_index']] = (split_originals, split_translations)
    return split_results

async def process_split_batch(batch: List[Dict], final_translation_map: Dict, quality_mode: str, model_name: str) -> Dict:
    prompt, metadata, _ = get_batch_split_prompt(batch, final_translation_map)
    if not metadata: return {}
    response_text = await api_call_with_retry(prompt, quality_mode, model_name)
    if any(err in response_text for err in ["FAILED","ERROR","EMPTY"]): return {}
    return parse_batch_split_response(response_text, metadata)

async def translate_srt_stream(
    srt_content: str, display_mode: str, target_language: str, quality_mode: str,
    font_size: Optional[int], split_long_lines: bool, max_line_length: int, model_name: str,
    enable_sentence_break: bool, min_duration_seconds: float, max_chars_for_break: int
) -> AsyncGenerator[str, None]:
    try:
        yield "[STATUS] 解析SRT文件..."
        original_subtitles = parse_srt(srt_content)
        if not original_subtitles: yield "[STATUS] 错误: 文件为空或无法解析"; return

        yield "[STATUS] 正在分组并完整翻译..."
        subtitle_groups = group_subtitles_by_sentence(original_subtitles)
        all_translation_batches, current_batch, current_chars = [], [], 0
        for group in subtitle_groups:
            group_chars = sum(len(line['clean']) for sub in group for line in sub['lines'])
            if current_batch and (current_chars + group_chars > MAX_CHARS_PER_BATCH):
                all_translation_batches.append(current_batch); current_batch, current_chars = [], 0
            current_batch.append(group); current_chars += group_chars
        if current_batch: all_translation_batches.append(current_batch)
        tasks = [translate_batch_of_groups_and_parse(batch, target_language, quality_mode, model_name) for batch in all_translation_batches]
        results_list = await asyncio.gather(*tasks)
        final_translation_map = {k: v for d in results_list for k, v in d.items()}
        yield "[STATUS] 翻译完成，正在处理断句任务..."

        split_results_map = {}
        if enable_sentence_break:
            subs_to_split = [sub for sub in original_subtitles if sum(len(l['clean']) for l in sub['lines']) >= max_chars_for_break and (parse_time_range(sub['time'])[1] - parse_time_range(sub['time'])[0]) / 1000 >= min_duration_seconds]
            if subs_to_split:
                yield f"[STATUS] 检测到 {len(subs_to_split)} 条长句，正在动态打包处理..."
                split_batches = []; current_split_batch = []; current_batch_tokens = 0
                for sub in subs_to_split:
                    original_text = " ".join([line['clean'] for line in sub['lines']])
                    translated_text = final_translation_map.get(sub['index'], "")
                    task_tokens = len(original_text) + len(translated_text)
                    if current_split_batch and (current_batch_tokens + task_tokens > SPLIT_BATCH_TOKEN_LIMIT):
                        split_batches.append(current_split_batch); current_split_batch = []; current_batch_tokens = 0
                    current_split_batch.append(sub); current_batch_tokens += task_tokens
                if current_split_batch: split_batches.append(current_split_batch)
                yield f"[STATUS] 动态打包完成，共 {len(split_batches)} 个断句批次。正在并行处理..."
                split_tasks = [process_split_batch(batch, final_translation_map, quality_mode, model_name) for batch in split_batches]
                split_results_list = await asyncio.gather(*split_tasks)
                for res_map in split_results_list: split_results_map.update(res_map)
                yield "[STATUS] 所有断句任务处理完成，正在生成最终字幕..."

        output_index = 1
        for sub in original_subtitles:
            if sub['index'] in split_results_map:
                split_originals, split_translations = split_results_map[sub['index']]
                start_ms, end_ms = parse_time_range(sub['time'])
                total_chars = sum(len(p) for p in split_originals)
                current_time_ms = start_ms
                for i in range(len(split_originals)):
                    part_original, part_translated = split_originals[i], split_translations[i]
                    part_duration = int((end_ms - start_ms) * (len(part_original) / total_chars)) if total_chars > 0 else 0
                    part_start = current_time_ms
                    part_end = current_time_ms + part_duration if i < len(split_originals) - 1 else end_ms
                    final_text_chunk = build_final_text_chunk(sub, part_original, part_translated, display_mode, font_size, split_long_lines, max_line_length)
                    yield f"{output_index}\n{format_time_range(part_start, part_end)}\n{final_text_chunk}\n\n"
                    output_index += 1; current_time_ms = part_end
            else:
                full_translated_text = final_translation_map.get(sub['index'], "")
                full_original_text = " ".join([line['clean'] for line in sub['lines']])
                final_text_chunk = build_final_text_chunk(sub, full_original_text, full_translated_text, display_mode, font_size, split_long_lines, max_line_length)
                yield f"{output_index}\n{sub['time']}\n{final_text_chunk}\n\n"
                output_index += 1
        yield "[STATUS] 所有任务完成！"
    except Exception as e:
        logger.error(f"翻译主流程出错: {e}", exc_info=True)
        yield f"[STATUS] 错误: {str(e)}"

def build_final_text_chunk(sub, o_txt, t_txt, dm, fs, sll, mll):
    t_lines=[]
    if sll and len(t_txt)>mll:
        for i in range(0,len(t_txt),mll):t_lines.append(t_txt[i:i+mll])
    else:t_lines.append(t_txt)
    tmpl=sub['lines'][0]['template'] if sub['lines'] else '{}'
    f_t_txt=tmpl.format('\n'.join(t_lines))
    if dm=="only_translated": return f_t_txt
    o_txt_f=tmpl.format(o_txt)
    if fs: o_txt_f=f'<font size="{fs}">{o_txt_f}</font>'
    return f"{o_txt_f}\n{f_t_txt}" if dm=="original_above_translated" else f"{f_t_txt}\n{o_txt_f}"

@app.get("/", response_model=BaseModel, summary="API状态检查")
async def root():
    return {"status": "active", "message": "SRT Translation API (Dynamic Batch Split) is running.", "timestamp": datetime.now().isoformat(), "version": "6.4.1"}
@app.get("/config", summary="获取API配置")
async def get_config():
    return { "supported_languages": SUPPORTED_LANGUAGES, "quality_modes": list(QUALITY_MODES.keys()), "default_target_language": "Simplified Chinese", "supported_models": SUPPORTED_MODELS, "sentence_break_features": {"enabled": True, "min_duration_seconds": 4.0, "max_chars_for_break": 50}}
@app.post("/translate-stream", summary="流式翻译SRT文件")
async def translate_stream_endpoint(
    file: UploadFile=File(...), display_mode:str=Query("only_translated"), target_language:str=Query("Simplified Chinese"),
    quality_mode:str=Query("标准"), font_size:Optional[int]=Query(None), split_long_lines:bool=Query(True),
    max_line_length:int=Query(40), model_name:str=Query("gemini-1.5-flash"), enable_sentence_break:bool=Query(False),
    min_duration_seconds:float=Query(6.0), max_chars_for_break:int=Query(60)
):
    try:
        sc = (await file.read()).decode('utf-8-sig')
        return StreamingResponse(translate_srt_stream(
            sc,display_mode,target_language,quality_mode,font_size,split_long_lines,max_line_length,
            model_name,enable_sentence_break,min_duration_seconds,max_chars_for_break), 
            media_type="text/plain; charset=utf-8")
    except Exception as e:
        logger.error(f"处理文件上传时出错: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"文件处理失败: {e}")

if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
