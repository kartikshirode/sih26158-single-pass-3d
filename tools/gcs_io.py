# -*- coding: utf-8 -*-
"""
Pull a run's artefacts off GCS without shelling out.

`finish_kolu.py` and `finish_mvs.py` used `gsutil -m cp ... shell=True`, which needs
the gcloud CLI on PATH and a shell to resolve the Windows .cmd shim. That is fine on
this laptop and impossible inside the pipeline container, which is where these scripts
have to run once an upload can trigger a reconstruction. google-cloud-storage is
already a dependency (requirements.txt), so the client is free.

Sequential rather than parallel on purpose: the objects are few and large, so the
transfer is bandwidth-bound and `-m` bought nothing, while a thread pool would make
the progress line harder to read.
"""
from __future__ import annotations

import os

DEFAULT_BUCKET = "sih26158-mumbai"


def pull(prefix: str, dest: str, bucket: str = DEFAULT_BUCKET, log=print) -> list:
    """Download every object under `prefix` into `dest`. Returns the local paths.

    Mirrors what `gsutil -m cp gs://<bucket>/<prefix>/* <dest>` did, including
    flattening: only the basename is kept, so a nested key would collide. The
    prefixes this reads are flat, and a nested one is an error worth seeing.
    """
    from google.cloud import storage

    os.makedirs(dest, exist_ok=True)
    b = storage.Client().bucket(bucket)
    got = []
    for blob in b.list_blobs(prefix=prefix.rstrip("/") + "/"):
        name = os.path.basename(blob.name)
        if not name:                       # a directory placeholder
            continue
        p = os.path.join(dest, name)
        blob.download_to_filename(p)
        got.append(p)
        log(f"    pulled {name}  {blob.size / 1e6:.1f} MB")
    if not got:
        raise SystemExit(f"nothing under gs://{bucket}/{prefix}/ - wrong prefix?")
    return got
