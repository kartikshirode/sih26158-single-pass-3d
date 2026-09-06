# noble, not jammy: the OpenMVS v2.4.0 prebuilt binaries are linked against
# GLIBC_2.38 / GLIBCXX_3.4.31 and refuse to load on 22.04 (GLIBC 2.35).
FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive

# Retries and a cache bypass: the archive mirror served a stale index mid-update on
# the first build attempt and apt failed the whole layer on a hash mismatch.
RUN rm -rf /var/lib/apt/lists/* \
 && apt-get -o Acquire::Retries=5 -o Acquire::http::No-Cache=true update \
 && apt-get install -y --no-install-recommends \
      ca-certificates curl bzip2 unzip \
      libgomp1 libgl1 libglu1-mesa libxi6 libxrandr2 libxinerama1 libxcursor1 \
      libfreeimage3 libpng16-16t64 libjpeg-turbo8 libtiff6 \
      assimp-utils \
 && rm -rf /var/lib/apt/lists/*

# COLMAP from conda-forge, pinned to the explicit CPU build. The default solve can
# pick a CUDA variant, which would pull a toolkit this project can never use: GPU
# quota is zero in every region on this account, which is what closed the
# colmap patch_match_stereo path and sent us to OpenMVS in the first place.
RUN curl -Ls https://micro.mamba.pm/api/micromamba/linux-64/latest \
      | tar -xj -C /usr/local bin/micromamba
ENV MAMBA_ROOT_PREFIX=/opt/conda
RUN set -eux; \
    micromamba install -y -p /opt/conda -c conda-forge \
      colmap python=3.11 numpy scipy py-opencv google-cloud-storage; \
    micromamba clean -ay; \
    echo "--- what landed in /opt/conda/bin ---"; ls /opt/conda/bin | head -40; \
    test -x /opt/conda/bin/colmap; \
    micromamba list -p /opt/conda | grep -Ei '^ *(colmap|ceres|python) '
ENV PATH=/opt/conda/bin:$PATH

# open3d for the fuse stage (dedupe + Poisson). pip, not conda-forge: the conda
# build lags and this image already pins python 3.11, which has a manylinux wheel.
RUN pip install --no-cache-dir "open3d==0.18.0" trimesh laspy rasterio pygltflib && \
    python -c "import open3d,trimesh,laspy,rasterio; print('export deps ok')" && \
    assimp version | head -2

# OpenMVS: upstream prebuilt Ubuntu x64 release. Upstream publishes the CUDA build
# as a separate asset, so this one runs on CPU; DensifyPointCloud still takes
# --cuda-device -2 to force it. Building from source would add ~25 min per attempt.
RUN curl -Ls -o /tmp/mvs.zip \
      https://github.com/cdcseacave/openMVS/releases/download/v2.4.0/OpenMVS_Ubuntu_x64.zip \
 && mkdir -p /opt/openmvs && unzip -q /tmp/mvs.zip -d /opt/openmvs && rm /tmp/mvs.zip

# The zip's internal layout is not documented and has changed between releases, so
# locate the binaries rather than hard-coding a path, and put their own directory on
# the loader path (NOT conda's - conda ships a different libstdc++ and OpenCV).
RUN set -eux; \
    bin=$(find /opt/openmvs -name DensifyPointCloud -type f | head -1); \
    d=$(dirname "$bin"); echo "OpenMVS bin dir: $d"; ls -la "$d"; \
    chmod +x "$d"/* || true; \
    echo "$d" > /etc/ld.so.conf.d/openmvs.conf; ldconfig; \
    for b in InterfaceCOLMAP DensifyPointCloud ReconstructMesh RefineMesh TextureMesh; do \
      test -f "$d/$b" && ln -sf "$d/$b" /usr/local/bin/$b || echo "MISSING $b"; done

# Fail the BUILD, not a 40-minute job, if the binaries cannot load their libraries.
# Check the loader's own complaint rather than the exit code: OpenMVS tools exit
# non-zero on --help, so an exit-code test cannot tell "no args" from "will not run",
# and a test that cannot fail is worse than no test.
RUN set -eux; \
    colmap help > /dev/null; echo "colmap loads"; \
    for b in InterfaceCOLMAP DensifyPointCloud ReconstructMesh RefineMesh TextureMesh; do \
      if "$b" --help 2>&1 | grep -qE "version .GLIBC|GLIBCXX|error while loading|symbol lookup"; then \
        echo "LOADER FAILURE: $b"; "$b" --help 2>&1 | head -5; exit 1; \
      fi; echo "  $b loads"; done; \
    python -c "import numpy, scipy, cv2, google.cloud.storage; print('python deps ok')"

WORKDIR /app
COPY src/pipeline/colmap_export.py /app/colmap_export.py
COPY src/pipeline/gravity.py /app/gravity.py
COPY src/pipeline/export_formats.py /app/export_formats.py
COPY mvs_job/run_mvs.py /app/run_mvs.py
COPY mvs_job/run_mvs_sharded.py /app/run_mvs_sharded.py
ENTRYPOINT ["python", "/app/run_mvs.py"]
