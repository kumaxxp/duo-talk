"""
Florence-2 Vision API Server for duo-talk

Features:
- SDPA attention (no flash-attn dependency)
- GPU memory management for vLLM coexistence
- Caption generation, object detection, segmentation
- Production-ready with health checks

Usage:
    uvicorn main:app --host 0.0.0.0 --port 5001
"""

import asyncio
import base64
import io
import time
from contextlib import asynccontextmanager
from typing import Optional, Dict, Any, List
from unittest.mock import patch

import torch
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from PIL import Image

# Patch flash_attn import BEFORE importing transformers model classes
from transformers.dynamic_module_utils import get_imports


def fixed_get_imports(filename: str) -> List[str]:
    """Remove flash_attn from required imports for Florence-2"""
    if not str(filename).endswith("modeling_florence2.py"):
        return get_imports(filename)
    imports = get_imports(filename)
    if "flash_attn" in imports:
        imports.remove("flash_attn")
    return imports


# ============================================================
# Configuration
# ============================================================

class Config:
    MODEL_ID = "microsoft/Florence-2-large"
    DEVICE = "cuda:0" if torch.cuda.is_available() else "cpu"
    DTYPE = torch.float16 if torch.cuda.is_available() else torch.float32
    # GPU memory fraction (25% for Florence-2, leaving room for vLLM)
    GPU_MEMORY_FRACTION = 0.25
    # Maximum image dimension
    MAX_IMAGE_SIZE = 1024


# ============================================================
# Task Definitions
# ============================================================

TASK_PROMPTS = {
    # Captioning
    "caption": "<CAPTION>",
    "detailed_caption": "<DETAILED_CAPTION>",
    "more_detailed_caption": "<MORE_DETAILED_CAPTION>",
    
    # Detection
    "object_detection": "<OD>",
    "dense_region_caption": "<DENSE_REGION_CAPTION>",
    "region_proposal": "<REGION_PROPOSAL>",
    
    # OCR
    "ocr": "<OCR>",
    "ocr_with_region": "<OCR_WITH_REGION>",
    
    # Segmentation
    "referring_expression_segmentation": "<REFERRING_EXPRESSION_SEGMENTATION>",
    "region_to_segmentation": "<REGION_TO_SEGMENTATION>",
    "open_vocabulary_detection": "<OPEN_VOCABULARY_DETECTION>",
    
    # Grounding
    "phrase_grounding": "<CAPTION_TO_PHRASE_GROUNDING>",
    "region_to_category": "<REGION_TO_CATEGORY>",
    "region_to_description": "<REGION_TO_DESCRIPTION>",
}


# ============================================================
# Model State
# ============================================================

class ModelState:
    """Global model state"""
    model = None
    processor = None
    device = Config.DEVICE
    dtype = Config.DTYPE
    loaded = False
    load_time = 0.0


state = ModelState()


# ============================================================
# Request/Response Models
# ============================================================

class InferenceRequest(BaseModel):
    """Request model for base64 image input"""
    image_base64: str
    task: str = "caption"
    text_input: Optional[str] = None


class InferenceResponse(BaseModel):
    """Response model for inference results"""
    task: str
    result: Dict[str, Any]
    processing_time_ms: float


class HealthResponse(BaseModel):
    """Health check response"""
    status: str
    model_loaded: bool
    device: str
    gpu_memory_gb: Optional[float] = None


# ============================================================
# Lifespan Management
# ============================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage model lifecycle"""
    print("=" * 60)
    print("Florence-2 Vision API Server Starting...")
    print("=" * 60)
    
    # Set GPU memory fraction BEFORE loading model
    if torch.cuda.is_available():
        torch.cuda.set_per_process_memory_fraction(
            Config.GPU_MEMORY_FRACTION, 
            device=0
        )
        print(f"GPU memory fraction set to {Config.GPU_MEMORY_FRACTION * 100}%")
    
    # Load model with SDPA attention
    start_time = time.time()
    
    try:
        from transformers import AutoModelForCausalLM, AutoProcessor
        
        print(f"Loading model: {Config.MODEL_ID}")
        print(f"Device: {Config.DEVICE}, Dtype: {Config.DTYPE}")
        
        with patch("transformers.dynamic_module_utils.get_imports", fixed_get_imports):
            state.model = AutoModelForCausalLM.from_pretrained(
                Config.MODEL_ID,
                attn_implementation="sdpa",  # Use PyTorch native SDPA
                torch_dtype=Config.DTYPE,
                trust_remote_code=True,
            ).to(Config.DEVICE)
        
        state.processor = AutoProcessor.from_pretrained(
            Config.MODEL_ID,
            trust_remote_code=True,
        )
        
        state.loaded = True
        state.load_time = time.time() - start_time
        
        if torch.cuda.is_available():
            mem_gb = torch.cuda.memory_allocated() / 1024**3
            print(f"✅ Model loaded in {state.load_time:.1f}s")
            print(f"✅ GPU memory used: {mem_gb:.2f} GB")
        else:
            print(f"✅ Model loaded in {state.load_time:.1f}s (CPU mode)")
        
    except Exception as e:
        print(f"❌ Failed to load model: {e}")
        raise
    
    print("=" * 60)
    print("Server ready!")
    print("=" * 60)
    
    yield
    
    # Cleanup
    print("Shutting down...")
    del state.model
    del state.processor
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    print("Cleanup complete")


# ============================================================
# FastAPI App
# ============================================================

app = FastAPI(
    title="Florence-2 Vision API",
    description="Image analysis API using Microsoft Florence-2-large with SDPA attention",
    version="1.0.0",
    lifespan=lifespan,
)


# ============================================================
# Utility Functions
# ============================================================

def decode_image(image_base64: str) -> Image.Image:
    """Decode base64 image to PIL Image"""
    try:
        # Remove data URL prefix if present
        if "," in image_base64:
            image_base64 = image_base64.split(",")[1]
        
        image_data = base64.b64decode(image_base64)
        image = Image.open(io.BytesIO(image_data)).convert("RGB")
        
        # Resize if too large
        if max(image.size) > Config.MAX_IMAGE_SIZE:
            ratio = Config.MAX_IMAGE_SIZE / max(image.size)
            new_size = (int(image.width * ratio), int(image.height * ratio))
            image = image.resize(new_size, Image.Resampling.LANCZOS)
        
        return image
    except Exception as e:
        raise ValueError(f"Failed to decode image: {e}")


def run_inference(image: Image.Image, task: str, text_input: Optional[str] = None) -> Dict[str, Any]:
    """Run Florence-2 inference"""
    if task not in TASK_PROMPTS:
        raise ValueError(f"Invalid task: {task}. Available: {list(TASK_PROMPTS.keys())}")
    
    # Build prompt
    prompt = TASK_PROMPTS[task]
    if text_input:
        prompt = prompt + text_input
    
    # Prepare inputs
    inputs = state.processor(
        text=prompt,
        images=image,
        return_tensors="pt",
    ).to(state.device, state.dtype)
    
    # Generate
    with torch.inference_mode():
        generated_ids = state.model.generate(
            input_ids=inputs["input_ids"],
            pixel_values=inputs["pixel_values"],
            max_new_tokens=1024,
            num_beams=3,
            do_sample=False,
        )
    
    # Decode
    generated_text = state.processor.batch_decode(
        generated_ids, 
        skip_special_tokens=False
    )[0]
    
    # Post-process
    result = state.processor.post_process_generation(
        generated_text,
        task=TASK_PROMPTS[task],
        image_size=(image.width, image.height),
    )
    
    return result


# ============================================================
# API Endpoints
# ============================================================

@app.get("/health", response_model=HealthResponse)
async def health():
    """Health check endpoint"""
    gpu_mem = None
    if torch.cuda.is_available():
        gpu_mem = round(torch.cuda.memory_allocated() / 1024**3, 2)
    
    return HealthResponse(
        status="healthy" if state.loaded else "loading",
        model_loaded=state.loaded,
        device=str(state.device),
        gpu_memory_gb=gpu_mem,
    )


@app.get("/ready")
async def readiness():
    """Kubernetes-style readiness check"""
    if not state.loaded:
        return JSONResponse(
            status_code=503,
            content={"status": "not ready", "reason": "Model not loaded"}
        )
    return {"status": "ready"}


@app.get("/tasks")
async def list_tasks():
    """List available tasks"""
    return {
        "tasks": list(TASK_PROMPTS.keys()),
        "descriptions": {
            "caption": "Simple image caption",
            "detailed_caption": "Detailed image description",
            "more_detailed_caption": "Very detailed image description",
            "object_detection": "Detect objects with bounding boxes",
            "dense_region_caption": "Caption for each region",
            "ocr": "Extract text from image",
            "ocr_with_region": "Extract text with bounding boxes",
            "referring_expression_segmentation": "Segment based on text description",
            "phrase_grounding": "Ground phrases to image regions",
        }
    }


@app.post("/infer", response_model=InferenceResponse)
async def infer_base64(request: InferenceRequest):
    """
    Run inference on base64-encoded image
    
    Args:
        request: InferenceRequest with image_base64, task, and optional text_input
    
    Returns:
        InferenceResponse with task results
    """
    if not state.loaded:
        raise HTTPException(503, "Model not loaded yet")
    
    try:
        # Decode image
        image = decode_image(request.image_base64)
        
        # Run inference
        start_time = time.time()
        result = await asyncio.to_thread(
            run_inference, 
            image, 
            request.task, 
            request.text_input
        )
        processing_time = (time.time() - start_time) * 1000
        
        return InferenceResponse(
            task=request.task,
            result=result,
            processing_time_ms=round(processing_time, 2),
        )
        
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"Inference failed: {e}")


@app.post("/infer/upload")
async def infer_upload(
    file: UploadFile = File(...),
    task: str = Form(default="caption"),
    text_input: Optional[str] = Form(default=None),
):
    """
    Run inference on uploaded image file
    
    Args:
        file: Image file upload
        task: Task type (default: caption)
        text_input: Optional text input for some tasks
    
    Returns:
        InferenceResponse with task results
    """
    if not state.loaded:
        raise HTTPException(503, "Model not loaded yet")
    
    try:
        # Read and decode image
        image_data = await file.read()
        image = Image.open(io.BytesIO(image_data)).convert("RGB")
        
        # Resize if too large
        if max(image.size) > Config.MAX_IMAGE_SIZE:
            ratio = Config.MAX_IMAGE_SIZE / max(image.size)
            new_size = (int(image.width * ratio), int(image.height * ratio))
            image = image.resize(new_size, Image.Resampling.LANCZOS)
        
        # Run inference
        start_time = time.time()
        result = await asyncio.to_thread(run_inference, image, task, text_input)
        processing_time = (time.time() - start_time) * 1000
        
        return InferenceResponse(
            task=task,
            result=result,
            processing_time_ms=round(processing_time, 2),
        )
        
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"Inference failed: {e}")


@app.get("/stats")
async def stats():
    """Get server statistics"""
    result = {
        "model_loaded": state.loaded,
        "model_id": Config.MODEL_ID,
        "device": str(state.device),
        "dtype": str(state.dtype),
        "load_time_seconds": round(state.load_time, 2),
    }
    
    if torch.cuda.is_available():
        result["gpu"] = {
            "name": torch.cuda.get_device_name(0),
            "memory_allocated_gb": round(torch.cuda.memory_allocated() / 1024**3, 2),
            "memory_reserved_gb": round(torch.cuda.memory_reserved() / 1024**3, 2),
            "memory_total_gb": round(torch.cuda.get_device_properties(0).total_memory / 1024**3, 2),
        }
    
    return result


# ============================================================
# Main
# ============================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5001)
