from typing import Dict, List, Optional
import re


def parse_time(t: str) -> float:
    try:
        h, m, s, ms = map(int, re.split(r'[:,]', t))
        return ms + 1e3 * s + 6e4 * m + 3.6e6 * h
    except Exception:
        return 0


def format_time(ms: float) -> str:
    h, r = divmod(ms, 3.6e6)
    m, r = divmod(r, 6e4)
    s, ms = divmod(r, 1e3)
    return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{int(ms):03d}"


def parse_time_range(tr: str):
    try:
        start, end = tr.split(' --> ')
        return parse_time(start), parse_time(end)
    except Exception:
        return 0, 0


def format_time_range(start: float, end: float) -> str:
    return f"{format_time(start)} --> {format_time(end)}"


def strip_tags(text: str) -> str:
    return re.sub(r'\{.*?\}|<.*?>', '', text).strip()


def create_template_and_clean_text(original_line: str) -> Dict[str, str]:
    clean_text = strip_tags(original_line)
    template = original_line
    placeholder = "___PLACEHOLDER___"
    if clean_text:
        try:
            template = re.sub(re.escape(clean_text), placeholder, template, 1)
        except Exception:
            template = template.replace(clean_text, placeholder, 1)
    template = template.replace('{', '{{').replace('}', '}}').replace(placeholder, '{}')
    return {"clean": clean_text, "template": template}


# 健壮的SRT解析函数

def parse_srt(srt_content: str, logger=None) -> List[Dict]:
    lines = srt_content.strip().replace('\r', '').split("\n")
    subtitles = []
    i = 0
    while i < len(lines):
        try:
            line_content = lines[i].strip()
            if line_content.isdigit():
                index = int(line_content)
                i += 1
                if i >= len(lines) or "-->" not in lines[i]:
                    continue

                time_str = lines[i]
                i += 1

                text_lines_raw = []
                while i < len(lines) and lines[i].strip() != "":
                    text_lines_raw.append(lines[i])
                    i += 1

                processed_lines = [
                    create_template_and_clean_text(raw_line)
                    for raw_line in text_lines_raw
                    if raw_line.strip()
                ]
                if processed_lines:
                    subtitles.append({"index": index, "time": time_str, "lines": processed_lines})

                while i < len(lines) and lines[i].strip() == "":
                    i += 1
            else:
                i += 1
        except Exception as exc:
            if logger:
                logger.warning(f"解析SRT时跳过一个无效块: {exc} at line index {i}")
            i += 1
    return subtitles


def group_subtitles_by_sentence(subtitles: List[Dict]) -> List[List[Dict]]:
    if not subtitles:
        return []
    groups, current_group = [], []
    sentence_enders = ('.', '?', '!', "''", '""', '。', '！', '？')
    for subtitle in subtitles:
        text = " ".join([line['clean'] for line in subtitle['lines']]).strip()
        current_group.append(subtitle)
        if text.endswith(sentence_enders) or len(current_group) >= 5:
            groups.append(current_group)
            current_group = []
    if current_group:
        groups.append(current_group)
    return groups


def build_final_text_chunk(
    subtitle: Dict,
    original_text: str,
    translated_text: str,
    display_mode: str,
    font_size: Optional[int],
    split_long_lines: bool,
    max_line_length: int,
) -> str:
    translated_lines = []
    if split_long_lines and len(translated_text) > max_line_length:
        for i in range(0, len(translated_text), max_line_length):
            translated_lines.append(translated_text[i:i + max_line_length])
    else:
        translated_lines.append(translated_text)

    template = subtitle['lines'][0]['template'] if subtitle['lines'] else '{}'
    formatted_translated = template.format('\n'.join(translated_lines))

    if display_mode == "only_translated":
        return formatted_translated

    formatted_original = template.format(original_text)
    if font_size:
        formatted_original = f'<font size="{font_size}">{formatted_original}</font>'

    if display_mode == "original_above_translated":
        return f"{formatted_original}\n{formatted_translated}"
    return f"{formatted_translated}\n{formatted_original}"
