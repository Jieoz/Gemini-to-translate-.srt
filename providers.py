from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Dict, List

import google.generativeai as genai
import httpx
from google.generativeai.types import HarmBlockThreshold, HarmCategory

logger = logging.getLogger(__name__)

QUALITY_MODES = {
    "快速": {"temperature": 0.3, "max_tokens": 4096},
    "标准": {"temperature": 0.7, "max_tokens": 6144},
    "高质量": {"temperature": 0.9, "max_tokens": 8192},
}
DEFAULT_GEMINI_MODELS = ["gemini-2.0-flash", "gemini-1.5-flash", "gemini-1.5-pro"]
API_TIMEOUT_SECONDS = 120
MAX_RETRIES = 3
RATE_LIMIT_DELAY = 5

SAFETY_SETTINGS = {
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
}


def get_provider_settings() -> Dict:
    api_provider = os.getenv("API_PROVIDER", "gemini").strip().lower() or "gemini"
    gemini_api_key = os.getenv("GEMINI_API_KEY", "").strip()
    openai_compat_base_url = os.getenv("OPENAI_COMPAT_BASE_URL", "").strip().rstrip("/")
    openai_compat_api_key = os.getenv("OPENAI_COMPAT_API_KEY", "").strip()
    openai_compat_model = os.getenv("OPENAI_COMPAT_MODEL", "gpt-4o-mini").strip()
    openai_compat_models = [
        model.strip()
        for model in os.getenv("OPENAI_COMPAT_MODELS", openai_compat_model).split(",")
        if model.strip()
    ]
    supported_models = DEFAULT_GEMINI_MODELS if api_provider == "gemini" else openai_compat_models
    return {
        "api_provider": api_provider,
        "gemini_api_key": gemini_api_key,
        "openai_compat_base_url": openai_compat_base_url,
        "openai_compat_api_key": openai_compat_api_key,
        "openai_compat_model": openai_compat_model,
        "openai_compat_models": openai_compat_models,
        "supported_models": supported_models,
    }


def normalize_api_error_message(exc: Exception, api_timeout_seconds: int = API_TIMEOUT_SECONDS) -> str:
    message = str(exc)
    lower = message.lower()
    if "deadlineexceeded" in message or "timeout" in lower or "timed out" in lower:
        return f"API_TIMEOUT_ERROR:{api_timeout_seconds}秒"
    if isinstance(exc, httpx.HTTPStatusError):
        status_code = exc.response.status_code
        if status_code == 401:
            return "API_AUTH_ERROR:第三方API认证失败，请检查密钥"
        if status_code == 403:
            return "API_PERMISSION_ERROR:第三方API无权访问该模型或接口"
        if status_code == 404:
            return "API_NOT_FOUND_ERROR:第三方API地址或模型不存在"
        if status_code == 429:
            return "API_RATE_LIMIT_ERROR:请求过多，请稍后重试"
        if 500 <= status_code < 600:
            return f"API_SERVER_ERROR:第三方API服务异常({status_code})"
        return f"API_HTTP_ERROR:{status_code}"
    return f"API_CALL_FAILED:{message}"


def has_working_provider_config(settings: Dict | None = None) -> bool:
    settings = settings or get_provider_settings()
    if settings["api_provider"] == "gemini":
        return bool(settings["gemini_api_key"])
    if settings["api_provider"] == "openai_compat":
        return bool(
            settings["openai_compat_base_url"]
            and settings["openai_compat_api_key"]
            and settings["openai_compat_model"]
        )
    return False


def initialize_provider(settings: Dict | None = None) -> Dict:
    settings = settings or get_provider_settings()
    try:
        if settings["api_provider"] == "gemini":
            if settings["gemini_api_key"]:
                genai.configure(api_key=settings["gemini_api_key"])
                logger.info("Gemini API Key配置成功")
            else:
                logger.warning("Gemini API Key未配置，Gemini 翻译接口将不可用")
        elif settings["api_provider"] == "openai_compat":
            if has_working_provider_config(settings):
                logger.info("OpenAI兼容API配置成功")
            else:
                logger.warning("OpenAI兼容API未完整配置，翻译接口将不可用")
        else:
            logger.warning(f"未知API_PROVIDER: {settings['api_provider']}，翻译接口将不可用")
    except Exception as exc:
        logger.error(f"API提供商初始化失败: {exc}")
    return settings


async def call_gemini_api(prompt: str, quality_mode: str, model_name: str, settings: Dict | None = None) -> str:
    settings = settings or get_provider_settings()
    if not settings["gemini_api_key"]:
        return "API_KEY_MISSING_ERROR"
    cfg = QUALITY_MODES.get(quality_mode, QUALITY_MODES["标准"])
    request_options = {"timeout": API_TIMEOUT_SECONDS}
    try:
        model = genai.GenerativeModel(model_name)
    except Exception:
        return f"INVALID_MODEL_NAME_ERROR:{model_name}"
    response = await model.generate_content_async(
        prompt,
        safety_settings=SAFETY_SETTINGS,
        generation_config=genai.types.GenerationConfig(
            temperature=cfg["temperature"],
            max_output_tokens=cfg["max_tokens"],
        ),
        request_options=request_options,
    )
    return response.text.strip() if getattr(response, "text", None) else "EMPTY_RESPONSE"


async def call_openai_compat_api(prompt: str, quality_mode: str, model_name: str, settings: Dict | None = None) -> str:
    settings = settings or get_provider_settings()
    if not has_working_provider_config(settings):
        return "API_KEY_MISSING_ERROR"
    cfg = QUALITY_MODES.get(quality_mode, QUALITY_MODES["标准"])
    url = f"{settings['openai_compat_base_url']}/chat/completions"
    payload = {
        "model": model_name or settings["openai_compat_model"],
        "messages": [{"role": "user", "content": prompt}],
        "temperature": cfg["temperature"],
        "max_tokens": cfg["max_tokens"],
        "stream": False,
    }
    headers = {
        "Authorization": f"Bearer {settings['openai_compat_api_key']}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=API_TIMEOUT_SECONDS) as client:
        response = await client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()
    try:
        content = data["choices"][0]["message"]["content"]
    except Exception:
        return f"API_CALL_FAILED:INVALID_OPENAI_COMPAT_RESPONSE:{json.dumps(data, ensure_ascii=False)[:300]}"
    if isinstance(content, list):
        text_parts = [part.get("text", "") for part in content if isinstance(part, dict)]
        content = "".join(text_parts)
    return content.strip() if isinstance(content, str) and content.strip() else "EMPTY_RESPONSE"


async def api_call_with_retry(prompt: str, quality_mode: str, model_name: str, settings: Dict | None = None) -> str:
    settings = settings or get_provider_settings()
    if not has_working_provider_config(settings):
        return "API_KEY_MISSING_ERROR"
    for attempt in range(MAX_RETRIES):
        try:
            if settings["api_provider"] == "gemini":
                return await call_gemini_api(prompt, quality_mode, model_name, settings)
            if settings["api_provider"] == "openai_compat":
                return await call_openai_compat_api(prompt, quality_mode, model_name, settings)
            return f"UNSUPPORTED_PROVIDER_ERROR:{settings['api_provider']}"
        except Exception as exc:
            normalized = normalize_api_error_message(exc)
            logger.error(
                f"API调用失败(att {attempt + 1}/{MAX_RETRIES}, provider={settings['api_provider']}): {normalized}"
            )
            if normalized.startswith("API_AUTH_ERROR") or normalized.startswith("API_PERMISSION_ERROR") or normalized.startswith("API_NOT_FOUND_ERROR"):
                return normalized
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(RATE_LIMIT_DELAY * (2 ** attempt))
            else:
                return normalized
    return "API_CALL_FAILED:重试次数已用尽。"
