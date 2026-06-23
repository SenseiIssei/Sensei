from __future__ import annotations

from fastapi import APIRouter

from sensei.models.registry import list_available_models, detect_gpu

router = APIRouter(prefix="/models", tags=["models"])


@router.get("")
async def get_models():
    """List all available models."""
    models = await list_available_models()
    return {
        "models": [m.model_dump() for m in models],
        "gpu_detected": detect_gpu(),
    }


@router.get("/gpu")
async def gpu_status():
    """Check GPU availability for local inference."""
    return {"gpu_available": detect_gpu()}
