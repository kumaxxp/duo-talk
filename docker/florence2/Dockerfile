# Florence-2 Docker Image for duo-talk
# SDPA attention backend - no flash-attn dependency
#
# Build: docker build -t duo-talk-florence2 .
# Run:   docker run --gpus all -p 5001:5001 duo-talk-florence2

FROM nvidia/cuda:12.4.0-runtime-ubuntu22.04

# Prevent interactive prompts
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

# System dependencies
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-dev \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgl1-mesa-glx \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create app directory
WORKDIR /app

# Install Python dependencies
# CRITICAL: Pin transformers to 4.49.0 for Florence-2 stability
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

# Copy application code
COPY main.py .

# Pre-download model on build (optional, can be mounted instead)
# RUN python3 -c "from transformers import AutoModelForCausalLM, AutoProcessor; \
#     AutoModelForCausalLM.from_pretrained('microsoft/Florence-2-large', trust_remote_code=True); \
#     AutoProcessor.from_pretrained('microsoft/Florence-2-large', trust_remote_code=True)"

# Expose port
EXPOSE 5001

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
    CMD curl -f http://localhost:5001/health || exit 1

# Run the server
CMD ["python3", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "5001"]
