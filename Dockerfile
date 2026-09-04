# Python 3.12, not 3.13: open3d ships no 3.13 wheels and MapAnything specifies 3.12.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PROJ_NETWORK=ON

# rasterio's wheels link against libexpat at runtime; python:3.12-slim does not ship
# it, and the failure only surfaces at import time inside the export stage.
RUN apt-get update && apt-get install -y --no-install-recommends         libexpat1 libgomp1     && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-cache the EGM2008 geoid grid into the image so the run is correct even with no
# network. Without it PROJ silently returns ellipsoidal height unchanged - a 24-98 m
# error over India (see research/02-ingestion-export-findings.md).
RUN python -c "\
import pyproj; pyproj.network.set_network_enabled(True); \
from pyproj.transformer import Transformer, TransformerGroup; \
g=TransformerGroup('EPSG:4979','EPSG:9518',always_xy=True); \
assert g.best_available, 'EGM2008 grid unavailable at build time'; \
t=Transformer.from_crs('EPSG:4979','EPSG:9518',always_xy=True,allow_ballpark=False); \
print('geoid N at Delhi =', round(250.0-t.transform(77.2090,28.6139,250.0)[2],3),'m')"

RUN python -c "import rasterio, laspy, trimesh, pyproj; print('imports OK', rasterio.__version__)"

COPY src/ ./src/
COPY cloud_job.py .

ENTRYPOINT ["python", "cloud_job.py"]
