from __future__ import annotations

import asyncio
import re
from typing import AsyncGenerator, Dict, List, Optional, Tuple

from providers import api_call_with_retry
from srt_utils import (
    build_final_text_chunk,
    format_time_range,
    group_subtitles_by_sentence,
    parse_srt,
    parse_time_range,
)

MAX_CHARS_PER_BATCH = 8000
SPLIT_BATCH_TOKEN_LIMIT = 8000


async def gather_with_concurrency(limit: int, coroutines):
    semaphore = asyncio.Semaphore(max(1, limit))

    async def run_one(coro):
        async with semaphore:
            return await coro

    return await asyncio.gather(*(run_one(coro) for coro in coroutines))


def get_translation_prompt(target_language: str, supported_languages: Dict[str, str]) -> str:
    language_name = supported_languages.get(target_language, "简体中文")
    return (
        f"Translate subtitle groups into {language_name}. "
        "CRITICAL RULE:You MUST provide a translation for EACH `[index]` in the input group. "
        "Intelligently distribute the full translation across all original `[index]` lines. "
        "Input format:[GROUP START][index1] text1 [index2] text2 [GROUP END]. "
        "Your output MUST be in the format:[index1] translation1 [index2] translation2. "
        "Input:\n{subtitle_batch_text}"
    )


async def split_text_simple(
    text: str,
    num_parts: int,
    quality_mode: str,
    model_name: str,
    provider_settings: Dict,
) -> List[str]:
    prompt = (
        f'Split the following text into {num_parts} natural parts. '
        f'Each part on a new line. No extra text or labels. Text:"{text}"'
    )
    response = await api_call_with_retry(prompt, quality_mode, model_name, provider_settings)
    if any(err in response for err in ["FAILED", "ERROR", "EMPTY"]):
        part_len = len(text) // num_parts
        return [text[i * part_len:(i + 1) * part_len] for i in range(num_parts - 1)] + [text[(num_parts - 1) * part_len:]]
    return [line.strip() for line in response.strip().split('\n') if line.strip()]


async def translate_batch_of_groups_and_parse(
    batch_of_groups: List[List[Dict]],
    target_language: str,
    quality_mode: str,
    model_name: str,
    provider_settings: Dict,
    supported_languages: Dict[str, str],
) -> Dict[int, str]:
    original_map = {}
    prompt_template = get_translation_prompt(target_language, supported_languages)
    prompt_text = ""
    for group in batch_of_groups:
        prompt_text += "[GROUP START]\n"
        for subtitle in group:
            clean_line = " ".join([line["clean"] for line in subtitle["lines"]])
            prompt_text += f'[{subtitle["index"]}] {clean_line}\n'
            original_map[subtitle["index"]] = clean_line
        prompt_text += "[GROUP END]\n"

    response = await api_call_with_retry(
        prompt_template.format(subtitle_batch_text=prompt_text),
        quality_mode,
        model_name,
        provider_settings,
    )
    if any(err in response for err in ["FAILED", "ERROR", "EMPTY", "MISSING"]):
        return {subtitle["index"]: original_map.get(subtitle["index"], "") for group in batch_of_groups for subtitle in group}

    translation_map = {
        int(match.group(1)): re.sub(r'\[\d+\]', '', match.group(2)).strip()
        for match in re.finditer(r'\[(\d+)\]\s*(.*)', response)
        if match.group(2).strip()
    }

    for group in batch_of_groups:
        group_indexes = [subtitle["index"] for subtitle in group]
        translated_indexes = [index for index in group_indexes if index in translation_map]
        if len(group_indexes) > 1 and len(translated_indexes) == 1:
            single_translation_index = translated_indexes[0]
            long_translation = translation_map[single_translation_index]
            try:
                split_translations = await split_text_simple(
                    long_translation,
                    len(group_indexes),
                    quality_mode,
                    model_name,
                    provider_settings,
                )
                if len(split_translations) == len(group_indexes):
                    for idx, subtitle_index in enumerate(group_indexes):
                        translation_map[subtitle_index] = split_translations[idx]
            except Exception:
                pass

    for group in batch_of_groups:
        for subtitle in group:
            if subtitle["index"] not in translation_map:
                translation_map[subtitle["index"]] = original_map.get(subtitle["index"], "")
    return translation_map


def get_batch_split_prompt(batch: List[Dict], final_translation_map: Dict) -> Tuple[str, Dict, int]:
    prompt_text = "You are an expert subtitle editor. For each sentence pair below, split BOTH the original and translated text into the specified number of parts. The split must be at natural pauses, and corresponding parts must be accurate translations of each other.\n\n"
    metadata = {}
    estimated_tokens = len(prompt_text) / 2.5
    for i, sub in enumerate(batch):
        original_text = " ".join([line["clean"] for line in sub["lines"]])
        translated_text = final_translation_map.get(sub["index"], "")
        if not translated_text:
            continue
        start_ms, end_ms = parse_time_range(sub["time"])
        duration_sec = (end_ms - start_ms) / 1000.0
        num_parts = max(2, min(4, int(duration_sec / 4.0)))
        task_text = (
            f"--- TASK {i + 1} ---\n"
            f"SPLIT_INTO: {num_parts}\n"
            f"[ORIGINAL-{i + 1}]\n{original_text}\n"
            f"[TRANSLATED-{i + 1}]\n{translated_text}\n\n"
        )
        prompt_text += task_text
        estimated_tokens += len(task_text) / 2.5
        metadata[i + 1] = {"original_index": sub["index"], "num_parts": num_parts}
    prompt_text += "Provide the results strictly in the following format for all tasks:\n[SPLIT-TaskNum-ORIGINAL-PartNum] text\n[SPLIT-TaskNum-TRANSLATED-PartNum] text"
    estimated_tokens += len("Provide the results...") / 2.5
    return prompt_text, metadata, int(estimated_tokens)


def parse_batch_split_response(response_text: str, metadata: Dict) -> Dict:
    split_results = {}
    for task_num, meta in metadata.items():
        split_originals = [""] * meta["num_parts"]
        split_translations = [""] * meta["num_parts"]
        for line in response_text.split("\n"):
            line = line.strip()
            match = re.match(r'\[SPLIT-(\d+)-(ORIGINAL|TRANSLATED)-(\d+)\]\s*(.*)', line)
            if match:
                res_task_num, lang, res_part_num, text = int(match.group(1)), match.group(2), int(match.group(3)), match.group(4)
                if res_task_num == task_num and 1 <= res_part_num <= meta["num_parts"]:
                    if lang == "ORIGINAL":
                        split_originals[res_part_num - 1] = text
                    elif lang == "TRANSLATED":
                        split_translations[res_part_num - 1] = text
        if all(split_originals) and all(split_translations):
            split_results[meta["original_index"]] = (split_originals, split_translations)
    return split_results


async def process_split_batch(
    batch: List[Dict],
    final_translation_map: Dict,
    quality_mode: str,
    model_name: str,
    provider_settings: Dict,
) -> Dict:
    prompt, metadata, _ = get_batch_split_prompt(batch, final_translation_map)
    if not metadata:
        return {}
    response_text = await api_call_with_retry(prompt, quality_mode, model_name, provider_settings)
    if any(err in response_text for err in ["FAILED", "ERROR", "EMPTY"]):
        return {}
    return parse_batch_split_response(response_text, metadata)


async def translate_srt_stream(
    srt_content: str,
    display_mode: str,
    target_language: str,
    quality_mode: str,
    font_size: Optional[int],
    split_long_lines: bool,
    max_line_length: int,
    model_name: str,
    enable_sentence_break: bool,
    min_duration_seconds: float,
    max_chars_for_break: int,
    provider_settings: Dict,
    supported_languages: Dict[str, str],
    max_translation_batch_concurrency: int,
    max_split_batch_concurrency: int,
    logger,
) -> AsyncGenerator[str, None]:
    try:
        yield "[STATUS] 解析SRT文件..."
        original_subtitles = parse_srt(srt_content, logger=logger)
        if not original_subtitles:
            yield "[STATUS] 错误: 文件为空或无法解析"
            return

        yield "[STATUS] 正在分组并完整翻译..."
        subtitle_groups = group_subtitles_by_sentence(original_subtitles)
        all_translation_batches, current_batch, current_chars = [], [], 0
        for group in subtitle_groups:
            group_chars = sum(len(line["clean"]) for sub in group for line in sub["lines"])
            if current_batch and (current_chars + group_chars > MAX_CHARS_PER_BATCH):
                all_translation_batches.append(current_batch)
                current_batch, current_chars = [], 0
            current_batch.append(group)
            current_chars += group_chars
        if current_batch:
            all_translation_batches.append(current_batch)

        tasks = [
            translate_batch_of_groups_and_parse(
                batch,
                target_language,
                quality_mode,
                model_name,
                provider_settings,
                supported_languages,
            )
            for batch in all_translation_batches
        ]
        results_list = await gather_with_concurrency(max_translation_batch_concurrency, tasks)
        final_translation_map = {k: v for result in results_list for k, v in result.items()}
        yield "[STATUS] 翻译完成，正在处理断句任务..."

        split_results_map = {}
        if enable_sentence_break:
            subs_to_split = [
                sub for sub in original_subtitles
                if sum(len(line["clean"]) for line in sub["lines"]) >= max_chars_for_break
                and (parse_time_range(sub["time"])[1] - parse_time_range(sub["time"])[0]) / 1000 >= min_duration_seconds
            ]
            if subs_to_split:
                yield f"[STATUS] 检测到 {len(subs_to_split)} 条长句，正在动态打包处理..."
                split_batches, current_split_batch, current_batch_tokens = [], [], 0
                for sub in subs_to_split:
                    original_text = " ".join([line["clean"] for line in sub["lines"]])
                    translated_text = final_translation_map.get(sub["index"], "")
                    task_tokens = len(original_text) + len(translated_text)
                    if current_split_batch and (current_batch_tokens + task_tokens > SPLIT_BATCH_TOKEN_LIMIT):
                        split_batches.append(current_split_batch)
                        current_split_batch, current_batch_tokens = [], 0
                    current_split_batch.append(sub)
                    current_batch_tokens += task_tokens
                if current_split_batch:
                    split_batches.append(current_split_batch)
                yield f"[STATUS] 动态打包完成，共 {len(split_batches)} 个断句批次。正在并行处理..."
                split_tasks = [
                    process_split_batch(batch, final_translation_map, quality_mode, model_name, provider_settings)
                    for batch in split_batches
                ]
                split_results_list = await gather_with_concurrency(max_split_batch_concurrency, split_tasks)
                for result_map in split_results_list:
                    split_results_map.update(result_map)
                yield "[STATUS] 所有断句任务处理完成，正在生成最终字幕..."

        output_index = 1
        for sub in original_subtitles:
            if sub["index"] in split_results_map:
                split_originals, split_translations = split_results_map[sub["index"]]
                start_ms, end_ms = parse_time_range(sub["time"])
                total_chars = sum(len(part) for part in split_originals)
                current_time_ms = start_ms
                for i in range(len(split_originals)):
                    part_original, part_translated = split_originals[i], split_translations[i]
                    part_duration = int((end_ms - start_ms) * (len(part_original) / total_chars)) if total_chars > 0 else 0
                    part_start = current_time_ms
                    part_end = current_time_ms + part_duration if i < len(split_originals) - 1 else end_ms
                    final_text_chunk = build_final_text_chunk(
                        sub,
                        part_original,
                        part_translated,
                        display_mode,
                        font_size,
                        split_long_lines,
                        max_line_length,
                    )
                    yield f"{output_index}\n{format_time_range(part_start, part_end)}\n{final_text_chunk}\n\n"
                    output_index += 1
                    current_time_ms = part_end
            else:
                full_translated_text = final_translation_map.get(sub["index"], "")
                full_original_text = " ".join([line["clean"] for line in sub["lines"]])
                final_text_chunk = build_final_text_chunk(
                    sub,
                    full_original_text,
                    full_translated_text,
                    display_mode,
                    font_size,
                    split_long_lines,
                    max_line_length,
                )
                yield f"{output_index}\n{sub['time']}\n{final_text_chunk}\n\n"
                output_index += 1
        yield "[STATUS] 所有任务完成！"
    except Exception as exc:
        logger.error(f"翻译主流程出错: {exc}", exc_info=True)
        yield f"[STATUS] 错误: {str(exc)}"
