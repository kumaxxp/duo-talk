"""
Florence-2 API Client for duo-talk

Connects to the Florence-2 Docker service for image analysis.

Usage:
    client = Florence2Client("http://localhost:5001")
    
    # Caption generation
    result = client.caption(image_base64)
    
    # Object detection
    result = client.detect_objects(image_base64)
    
    # Segmentation (with text prompt)
    result = client.segment(image_base64, "the car on the left")
"""

import base64
import httpx
from pathlib import Path
from typing import Optional, Dict, Any, Union
from dataclasses import dataclass


@dataclass
class Florence2Result:
    """Florence-2 inference result"""
    task: str
    result: Dict[str, Any]
    processing_time_ms: float
    success: bool = True
    error: Optional[str] = None
    
    @property
    def text(self) -> str:
        """Get text result (for caption tasks)"""
        if isinstance(self.result, dict):
            # Handle different result formats
            for key in ["<CAPTION>", "<DETAILED_CAPTION>", "<MORE_DETAILED_CAPTION>", 
                       "<OCR>", "text", "caption"]:
                if key in self.result:
                    return self.result[key]
        return str(self.result)
    
    @property
    def objects(self) -> list:
        """Get detected objects (for detection tasks)"""
        if isinstance(self.result, dict):
            for key in ["<OD>", "<DENSE_REGION_CAPTION>", "labels", "objects"]:
                if key in self.result:
                    val = self.result[key]
                    if isinstance(val, dict):
                        return val.get("labels", [])
                    return val
        return []
    
    @property
    def bboxes(self) -> list:
        """Get bounding boxes (for detection tasks)"""
        if isinstance(self.result, dict):
            for key in ["<OD>", "<DENSE_REGION_CAPTION>", "bboxes"]:
                if key in self.result:
                    val = self.result[key]
                    if isinstance(val, dict):
                        return val.get("bboxes", [])
                    return val
        return []


class Florence2Client:
    """Client for Florence-2 Docker API service"""
    
    def __init__(
        self, 
        base_url: str = "http://localhost:5001",
        timeout: float = 60.0,
    ):
        """
        Initialize Florence-2 client.
        
        Args:
            base_url: Florence-2 API server URL
            timeout: Request timeout in seconds
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client = httpx.Client(timeout=timeout)
    
    def health(self) -> Dict[str, Any]:
        """Check service health"""
        try:
            resp = self._client.get(f"{self.base_url}/health")
            if resp.status_code == 200:
                return resp.json()
            return {"status": "error", "code": resp.status_code}
        except Exception as e:
            return {"status": "error", "error": str(e)}
    
    def is_ready(self) -> bool:
        """Check if service is ready"""
        health = self.health()
        return health.get("status") == "healthy" and health.get("model_loaded", False)
    
    def wait_until_ready(self, timeout: float = 300.0, interval: float = 5.0) -> bool:
        """Wait until service is ready"""
        import time
        start = time.time()
        while time.time() - start < timeout:
            if self.is_ready():
                return True
            time.sleep(interval)
        return False
    
    def list_tasks(self) -> list:
        """Get list of available tasks"""
        try:
            resp = self._client.get(f"{self.base_url}/tasks")
            if resp.status_code == 200:
                return resp.json().get("tasks", [])
        except Exception:
            pass
        return []
    
    def _encode_image(self, image: Union[str, bytes, Path]) -> str:
        """Encode image to base64"""
        if isinstance(image, bytes):
            return base64.b64encode(image).decode("utf-8")
        
        if isinstance(image, Path):
            with open(image, "rb") as f:
                return base64.b64encode(f.read()).decode("utf-8")
        
        if isinstance(image, str):
            # Check if it's a short string that could be a file path
            # Base64 strings are typically much longer than file paths
            if len(image) < 500:
                path = Path(image)
                if path.exists():
                    with open(path, "rb") as f:
                        return base64.b64encode(f.read()).decode("utf-8")
            
            # Assume it's already base64
            # Remove data URL prefix if present
            if image.startswith("data:"):
                image = image.split(",", 1)[-1]
            return image
        
        raise ValueError(f"Unsupported image type: {type(image)}")
    
    def infer(
        self, 
        image: Union[str, bytes, Path],
        task: str = "caption",
        text_input: Optional[str] = None,
    ) -> Florence2Result:
        """
        Run inference on an image.
        
        Args:
            image: Image as file path, bytes, or base64 string
            task: Task type (caption, object_detection, etc.)
            text_input: Optional text input for some tasks
        
        Returns:
            Florence2Result with inference results
        """
        try:
            image_b64 = self._encode_image(image)
            
            payload = {
                "image_base64": image_b64,
                "task": task,
            }
            if text_input:
                payload["text_input"] = text_input
            
            resp = self._client.post(
                f"{self.base_url}/infer",
                json=payload,
            )
            
            if resp.status_code == 200:
                data = resp.json()
                return Florence2Result(
                    task=data["task"],
                    result=data["result"],
                    processing_time_ms=data["processing_time_ms"],
                )
            else:
                return Florence2Result(
                    task=task,
                    result={},
                    processing_time_ms=0,
                    success=False,
                    error=f"HTTP {resp.status_code}: {resp.text}",
                )
                
        except Exception as e:
            return Florence2Result(
                task=task,
                result={},
                processing_time_ms=0,
                success=False,
                error=str(e),
            )
    
    # ============================================================
    # Convenience Methods
    # ============================================================
    
    def caption(self, image: Union[str, bytes, Path], detailed: bool = False) -> Florence2Result:
        """
        Generate image caption.
        
        Args:
            image: Image to caption
            detailed: If True, use detailed_caption task
        
        Returns:
            Florence2Result with caption text
        """
        task = "detailed_caption" if detailed else "caption"
        return self.infer(image, task=task)
    
    def detect_objects(self, image: Union[str, bytes, Path]) -> Florence2Result:
        """
        Detect objects in image.
        
        Args:
            image: Image to analyze
        
        Returns:
            Florence2Result with detected objects and bounding boxes
        """
        return self.infer(image, task="object_detection")
    
    def dense_caption(self, image: Union[str, bytes, Path]) -> Florence2Result:
        """
        Generate dense region captions.
        
        Args:
            image: Image to analyze
        
        Returns:
            Florence2Result with region captions
        """
        return self.infer(image, task="dense_region_caption")
    
    def ocr(self, image: Union[str, bytes, Path], with_regions: bool = False) -> Florence2Result:
        """
        Extract text from image (OCR).
        
        Args:
            image: Image to analyze
            with_regions: If True, include text bounding boxes
        
        Returns:
            Florence2Result with extracted text
        """
        task = "ocr_with_region" if with_regions else "ocr"
        return self.infer(image, task=task)
    
    def segment(self, image: Union[str, bytes, Path], text_prompt: str) -> Florence2Result:
        """
        Segment image based on text description.
        
        Args:
            image: Image to segment
            text_prompt: Text description of region to segment
        
        Returns:
            Florence2Result with segmentation mask
        """
        return self.infer(
            image, 
            task="referring_expression_segmentation",
            text_input=text_prompt,
        )
    
    def ground_phrase(self, image: Union[str, bytes, Path], phrase: str) -> Florence2Result:
        """
        Ground a phrase to image regions.
        
        Args:
            image: Image to analyze
            phrase: Phrase to ground
        
        Returns:
            Florence2Result with grounded regions
        """
        return self.infer(image, task="phrase_grounding", text_input=phrase)
    
    # ============================================================
    # Context Manager
    # ============================================================
    
    def close(self):
        """Close the HTTP client"""
        self._client.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


# ============================================================
# Singleton Instance
# ============================================================

_default_client: Optional[Florence2Client] = None


def get_florence2_client(base_url: str = "http://localhost:5001") -> Florence2Client:
    """Get or create default Florence-2 client"""
    global _default_client
    if _default_client is None:
        _default_client = Florence2Client(base_url)
    return _default_client


# ============================================================
# CLI Test
# ============================================================

if __name__ == "__main__":
    import sys
    
    url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:5001"
    
    print(f"Testing Florence-2 API at {url}")
    print("=" * 50)
    
    client = Florence2Client(url)
    
    # Health check
    health = client.health()
    print(f"Health: {health}")
    
    if not client.is_ready():
        print("Service not ready!")
        sys.exit(1)
    
    # List tasks
    tasks = client.list_tasks()
    print(f"Available tasks: {tasks}")
    
    # Test with sample image if provided
    if len(sys.argv) > 2:
        image_path = sys.argv[2]
        print(f"\nTesting with image: {image_path}")
        
        # Caption
        result = client.caption(image_path)
        print(f"Caption: {result.text}")
        print(f"Time: {result.processing_time_ms:.1f}ms")
        
        # Object detection
        result = client.detect_objects(image_path)
        print(f"Objects: {result.objects}")
        print(f"Time: {result.processing_time_ms:.1f}ms")
    
    client.close()
    print("\nDone!")
