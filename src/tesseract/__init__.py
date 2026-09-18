"""
tesseract - single-pass drone video to a metric 3D model.

The pipeline rebuilt on the research: typed contracts (docs/09), a scale service that
decides what may be called a metre (docs/08), and a stage DAG with resume, a cost
budget and a degradation ladder (docs/13).

    from tesseract import Pipeline, Context, SyntheticSource, DEFAULT_STAGES
"""

from .contracts import (Artefact, Code, Frame, LADDER, LEVELS, RunManifest,  # noqa: F401
                        StageError, StageResult, Units, validate_manifest)
from .pipeline import BaseStage, Context, Pipeline, State  # noqa: F401
from .sources import SyntheticSource, VideoSource  # noqa: F401
from .stages import DEFAULT_STAGES  # noqa: F401

__all__ = [
    "Artefact", "Code", "Frame", "LADDER", "LEVELS", "RunManifest", "StageError",
    "StageResult", "Units", "validate_manifest", "BaseStage", "Context", "Pipeline",
    "State", "SyntheticSource", "VideoSource", "DEFAULT_STAGES",
]
