from __future__ import annotations

import json
import os
from pathlib import Path

from piano_arrangement_models import (
    ARRANGEMENT_ALGORITHM_VERSION,
    ArrangementPlan,
    PianoArrangementConfig,
    arrangement_cache_path,
)


def load_arrangement_cache(
    source_file_hash: str,
    config: PianoArrangementConfig,
) -> ArrangementPlan | None:
    path = arrangement_cache_path(source_file_hash, config)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        plan = ArrangementPlan.from_dict(payload)
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None
    if (
        plan.algorithm_version != ARRANGEMENT_ALGORITHM_VERSION
        or plan.source_file_hash != source_file_hash
        or plan.config_key != config.cache_key()
    ):
        return None
    return plan


def save_arrangement_cache(
    plan: ArrangementPlan,
    config: PianoArrangementConfig,
) -> Path:
    path = arrangement_cache_path(plan.source_file_hash, config)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(".tmp")
    temporary_path.write_text(
        json.dumps(
            plan.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    os.replace(temporary_path, path)
    return path


def remove_stale_temporary_cache_files(root: Path) -> None:
    if not root.exists():
        return
    for path in root.rglob("*.tmp"):
        try:
            path.unlink()
        except OSError:
            pass
