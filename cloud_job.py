"""
Cloud Run Job entrypoint for the SIH26158 pipeline.

Runs in asia-south1 (Mumbai). That region choice is a REQUIREMENT, not a preference:
Indian geospatial regulation requires data at or finer than 1 m to be stored and
processed in India (R-NF8), so foreign regions are not available to this workload.

Uploads all artefacts to GCS and prints the run manifest.
"""
import json
import os
import sys

sys.path.insert(0, "src")

from eval3d.gnss import CONSUMER_GNSS, RTK_GNSS   # noqa: E402
from pipeline.run_demo import run                 # noqa: E402

BUCKET = os.environ.get("OUT_BUCKET", "")
PREFIX = os.environ.get("OUT_PREFIX", "runs")


def upload(local_dir, bucket_name, prefix):
    if not bucket_name:
        print("  (no OUT_BUCKET set - skipping upload)")
        return []
    from google.cloud import storage
    bucket = storage.Client().bucket(bucket_name)
    sent = []
    for fn in sorted(os.listdir(local_dir)):
        blob = bucket.blob(f"{prefix}/{fn}")
        blob.upload_from_filename(os.path.join(local_dir, fn))
        sent.append(f"gs://{bucket_name}/{prefix}/{fn}")
    return sent


def main():
    results = {}
    for name, spec in (("consumer", CONSUMER_GNSS), ("rtk", RTK_GNSS)):
        out = f"/tmp/out/{name}"
        m = run(out, gnss=spec, label=f"{name} GNSS")
        results[name] = m
        for u in upload(out, BUCKET, f"{PREFIX}/{name}"):
            print("  uploaded", u)

    print("\n" + "=" * 78)
    print("SUMMARY  (single-pass drone video -> georeferenced 3D)")
    print("=" * 78)
    print(f"{'GNSS':<10}{'abs RMSE':>11}{'shape RMSE':>12}{'complete@1m':>13}"
          f"{'runtime':>10}{'budget':>9}  R-O3")
    for k, m in results.items():
        print(f"{k:<10}{m['accuracy_absolute_rmse_m']:>10.3f}m"
              f"{m['accuracy_aligned_rmse_m']:>11.3f}m"
              f"{m['completeness_recall_at_1m_observable']:>12.1%}"
              f"{m['total_s']:>9.1f}s{'900s':>9}  "
              f"{'PASS' if m['accuracy_absolute_rmse_m'] <= 1.0 else 'FAIL'}")
    print(json.dumps({k: {'abs_rmse_m': v['accuracy_absolute_rmse_m'],
                          'crs': v['crs'], 'geoid_N_m': v['geoid_separation_m'],
                          'total_s': v['total_s']} for k, v in results.items()}, indent=2))


if __name__ == "__main__":
    main()
