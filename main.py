from fastapi import FastAPI, HTTPException, File, UploadFile, Query
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
import os
import logging
from datetime import datetime
import uvicorn

from providers import QUALITY_MODES, get_provider_settings, has_working_provider_config, initialize_provider
from translation_core import translate_srt_stream

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="SRT翻译API",
    description="支持多语言字幕翻译和智能断句的API服务",
    version="6.4.1",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

MAX_TRANSLATION_BATCH_CONCURRENCY = max(1, int(os.getenv("MAX_TRANSLATION_BATCH_CONCURRENCY", "3")))
MAX_SPLIT_BATCH_CONCURRENCY = max(1, int(os.getenv("MAX_SPLIT_BATCH_CONCURRENCY", "2")))

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
    "Arabic": "阿拉伯文",
}

PROVIDER_SETTINGS = initialize_provider(get_provider_settings())
API_PROVIDER = PROVIDER_SETTINGS["api_provider"]
SUPPORTED_MODELS = PROVIDER_SETTINGS["supported_models"]
DEFAULT_MODEL = (
    PROVIDER_SETTINGS["openai_compat_model"]
    if API_PROVIDER == "openai_compat"
    else (SUPPORTED_MODELS[0] if SUPPORTED_MODELS else "gemini-1.5-flash")
)


@app.get("/", response_model=BaseModel, summary="API状态检查")
async def root():
    return {
        "status": "active",
        "message": "SRT Translation API (Dynamic Batch Split) is running.",
        "timestamp": datetime.now().isoformat(),
        "version": "6.4.1",
    }


@app.get("/health", summary="健康检查")
async def health():
    return {
        "status": "ok",
        "provider": API_PROVIDER,
        "api_key_configured": has_working_provider_config(PROVIDER_SETTINGS),
        "timestamp": datetime.now().isoformat(),
        "version": "6.4.1",
    }


@app.get("/config", summary="获取API配置")
async def get_config():
    return {
        "provider": API_PROVIDER,
        "supported_languages": SUPPORTED_LANGUAGES,
        "quality_modes": list(QUALITY_MODES.keys()),
        "default_target_language": "Simplified Chinese",
        "supported_models": SUPPORTED_MODELS,
        "default_model": DEFAULT_MODEL,
        "sentence_break_features": {
            "enabled": True,
            "min_duration_seconds": 4.0,
            "max_chars_for_break": 50,
        },
        "runtime_limits": {
            "max_translation_batch_concurrency": MAX_TRANSLATION_BATCH_CONCURRENCY,
            "max_split_batch_concurrency": MAX_SPLIT_BATCH_CONCURRENCY,
        },
    }


@app.post("/translate-stream", summary="流式翻译SRT文件")
async def translate_stream_endpoint(
    file: UploadFile = File(...),
    display_mode: str = Query("only_translated"),
    target_language: str = Query("Simplified Chinese"),
    quality_mode: str = Query("标准"),
    font_size: int | None = Query(None),
    split_long_lines: bool = Query(True),
    max_line_length: int = Query(40),
    model_name: str = Query(DEFAULT_MODEL),
    enable_sentence_break: bool = Query(False),
    min_duration_seconds: float = Query(6.0),
    max_chars_for_break: int = Query(60),
):
    try:
        srt_content = (await file.read()).decode("utf-8-sig")
        return StreamingResponse(
            translate_srt_stream(
                srt_content=srt_content,
                display_mode=display_mode,
                target_language=target_language,
                quality_mode=quality_mode,
                font_size=font_size,
                split_long_lines=split_long_lines,
                max_line_length=max_line_length,
                model_name=model_name,
                enable_sentence_break=enable_sentence_break,
                min_duration_seconds=min_duration_seconds,
                max_chars_for_break=max_chars_for_break,
                provider_settings=PROVIDER_SETTINGS,
                supported_languages=SUPPORTED_LANGUAGES,
                max_translation_batch_concurrency=MAX_TRANSLATION_BATCH_CONCURRENCY,
                max_split_batch_concurrency=MAX_SPLIT_BATCH_CONCURRENCY,
                logger=logger,
            ),
            media_type="text/plain; charset=utf-8",
        )
    except Exception as exc:
        logger.error(f"处理文件上传时出错: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"文件处理失败: {exc}")


if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
