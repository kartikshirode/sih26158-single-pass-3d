# The web orchestrator: one uploaded clip, S0 to the final model, as one job.
#
# Python 3.12, matching the root image: open3d ships no 3.13 wheels and MapAnything
# specifies 3.12. This image does NOT contain torch or OpenMVS - it delegates poses to
# kolu-ma and densification to sih26158-mvs and waits. Keeping those out is what lets
# this stay small enough to cold-start in seconds, which matters because the browser is
# watching status.json from the first moment.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PROJ_NETWORK=ON

# libexpat1/libgomp1: rasterio's wheels link them at runtime and the failure only shows
#   at import time inside the export stage.
# libgl1/libglib2.0-0: opencv-python-headless still wants them for some codecs.
# assimp-utils: the FBX writer. docs/16 L-3 keeps the Blender fallback off anything
#   distributable, because a published bpy script is treated as GPL.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libexpat1 libgomp1 libgl1 libglib2.0-0 assimp-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
 && pip install --no-cache-dir \
        "opencv-python-headless==4.11.0.86" \
        "av==13.1.0" \
        "open3d==0.19.0" \
        "google-cloud-run==0.10.10"

# Same geoid pre-cache as the root image: without the EGM2008 grid PROJ silently
# returns ellipsoidal height unchanged, which is a 24-98 m error over India
# (research/02-ingestion-export-findings.md).
RUN python -c "\
import pyproj; pyproj.network.set_network_enabled(True); \
from pyproj.transformer import Transformer, TransformerGroup; \
g=TransformerGroup('EPSG:4979','EPSG:9518',always_xy=True); \
assert g.best_available, 'EGM2008 grid unavailable at build time'; \
t=Transformer.from_crs('EPSG:4979','EPSG:9518',always_xy=True,allow_ballpark=False); \
print('geoid N at Delhi =', round(250.0-t.transform(77.2090,28.6139,250.0)[2],3),'m')"

RUN python -c "import cv2, av, open3d, rasterio, laspy, trimesh; print('imports OK')"

COPY src/ ./src/
COPY tools/ ./tools/
COPY tesseract.py .
COPY run_job/run_upload.py .

ENTRYPOINT ["python", "run_upload.py"]
