from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Annotated

import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from backend.config import PipelineConfig
from backend.full_pipeline import FullPipeline, full_pipeline_result_to_dict
from backend.pipeline import OCRPipeline
from backend.utils import (
    bytes_to_ndarray,
    ocr_response_to_dict,
    validate_image_bytes,
)

logger = logging.getLogger("auto-comic-translator")

_ocr_pipeline: OCRPipeline | None = None
_full_pipeline: FullPipeline | None = None


def get_ocr_pipeline() -> OCRPipeline:
    global _ocr_pipeline
    if _ocr_pipeline is None:
        _ocr_pipeline = OCRPipeline(PipelineConfig(use_gpu=False))
    return _ocr_pipeline


def get_full_pipeline() -> FullPipeline:
    global _full_pipeline
    if _full_pipeline is None:
        _full_pipeline = FullPipeline(PipelineConfig(use_gpu=False))
    return _full_pipeline


@asynccontextmanager
async def lifespan(application: FastAPI):
    logger.info("Warming up OCR pipeline...")
    try:
        p = get_ocr_pipeline()
        warmup = np.zeros((100, 100, 3), dtype=np.uint8)
        p._preprocessor.enhance(warmup)
        _ = p._ocr.readers
        logger.info("PaddleOCR pipeline ready")
    except Exception as e:
        logger.warning("Pipeline warmup incomplete: %s", e)
    yield


app = FastAPI(
    title="Auto Comic Translator — Phase 2",
    version="0.2.0",
    description="OCR + Translation pipeline for comic images",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": "0.2.0", "pipeline": "ocr+translate"}


@app.post("/ocr", response_model=dict)
async def ocr_endpoint(
    image: Annotated[UploadFile, File(...)],
    source_language: Annotated[str, Form()] = "auto",
    group_text: Annotated[bool, Form()] = True,
) -> dict:
    if not image.content_type or not image.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")

    data = await image.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty image file")

    try:
        validate_image_bytes(data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    nd = bytes_to_ndarray(data)
    pipeline = get_ocr_pipeline()

    if group_text:
        response = pipeline.run_with_grouping(nd, source_language=source_language)
    else:
        response = pipeline.run(nd, source_language=source_language)

    return ocr_response_to_dict(response)


@app.post("/translate", response_model=dict)
async def translate_endpoint(
    image: Annotated[UploadFile, File(...)],
    source_language: Annotated[str, Form()] = "auto",
    target_language: Annotated[str, Form()] = "en",
) -> dict:
    if not image.content_type or not image.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")

    data = await image.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty image file")

    try:
        validate_image_bytes(data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    nd = bytes_to_ndarray(data)
    pipeline = get_full_pipeline()
    result = pipeline.run(nd, source_language=source_language, target_language=target_language)
    return full_pipeline_result_to_dict(result)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)
