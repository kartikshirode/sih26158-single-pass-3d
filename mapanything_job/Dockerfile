# MapAnything on CPU. Python 3.12 because MapAnything specifies it (and open3d ships
# no 3.13 wheels). CPU-only torch: GPU quota on this GCP account is 0 across Compute
# Engine, Cloud Run AND Vertex AI, verified by submission, so this measures what the
# model actually costs without one.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    HF_HOME=/opt/hf \
    OMP_NUM_THREADS=8 \
    MKL_NUM_THREADS=8

RUN apt-get update && apt-get install -y --no-install-recommends \
        git build-essential libexpat1 libgomp1 libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# CPU-only torch first, so the MapAnything install does not pull a CUDA build (~2.5 GB)
RUN pip install --no-cache-dir torch==2.6.0 torchvision==0.21.0 \
        --index-url https://download.pytorch.org/whl/cpu

RUN pip install --no-cache-dir "numpy<3" pillow huggingface_hub \
        google-cloud-storage einops opencv-python-headless

RUN git clone --depth 1 https://github.com/facebookresearch/map-anything.git /opt/map-anything \
    && cd /opt/map-anything \
    && pip install --no-cache-dir -e . \
    && python -c "import mapanything; print('mapanything import OK')"

# Bake the APACHE-licensed weights into the image. The default checkpoint is
# CC-BY-NC and unusable for this customer; the -apache variant carries no
# field-of-use restriction, which matters because NTRO is an intelligence agency.
RUN python -c "\
from huggingface_hub import snapshot_download; \
p=snapshot_download('facebook/map-anything-apache'); \
print('weights cached at', p)"

WORKDIR /app
COPY run_mapanything.py .
ENTRYPOINT ["python", "run_mapanything.py"]
