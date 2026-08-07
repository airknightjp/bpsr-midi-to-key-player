from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

import numpy as np


ASSET_DIRECTORY = "assets"
BANK_FILENAME = "starra_guitar_bank.npy"
METADATA_FILENAME = "starra_guitar_bank.json"


def _resource_path(filename: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / ASSET_DIRECTORY / filename


@dataclass(frozen=True)
class StarraGuitarSample:
    bank_index: int
    source_note: int
    sample_length: int
    playback_step: float


class StarraGuitarBank:
    def __init__(self, bank_path: Path, metadata_path: Path) -> None:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        samples = np.load(bank_path, mmap_mode="r", allow_pickle=False)
        notes = np.asarray(metadata["notes"], dtype=np.int16)
        lengths = np.asarray(metadata["lengths"], dtype=np.int32)
        sample_rate = int(metadata["sample_rate"])

        if samples.dtype != np.int16 or samples.ndim != 2:
            raise ValueError("Starra guitar bank must be a two-dimensional int16 array")
        if len(notes) != len(lengths) or samples.shape[0] != len(notes):
            raise ValueError("Starra guitar bank metadata does not match the sample rows")
        if sample_rate <= 0 or len(notes) == 0:
            raise ValueError("Starra guitar bank metadata is empty or invalid")
        if np.any(lengths <= 0) or np.any(lengths > samples.shape[1]):
            raise ValueError("Starra guitar bank contains invalid sample lengths")
        if np.any(notes[1:] <= notes[:-1]):
            raise ValueError("Starra guitar bank notes must be strictly increasing")

        self.samples = samples
        self.notes = notes
        self.lengths = lengths
        self.sample_rate = sample_rate
        self.analysis = dict(metadata.get("analysis", {}))

    def select(self, note: int, output_sample_rate: int) -> StarraGuitarSample:
        requested_note = int(note)
        insertion = int(np.searchsorted(self.notes, requested_note))
        if insertion <= 0:
            index = 0
        elif insertion >= len(self.notes):
            index = len(self.notes) - 1
        else:
            lower = int(self.notes[insertion - 1])
            upper = int(self.notes[insertion])
            index = insertion - 1 if requested_note - lower <= upper - requested_note else insertion
        source_note = int(self.notes[index])
        pitch_ratio = 2.0 ** ((requested_note - source_note) / 12.0)
        playback_step = self.sample_rate * pitch_ratio / max(1, int(output_sample_rate))
        return StarraGuitarSample(
            bank_index=index,
            source_note=source_note,
            sample_length=int(self.lengths[index]),
            playback_step=playback_step,
        )


_BANK: StarraGuitarBank | None = None
_BANK_LOCK = Lock()


def get_starra_guitar_bank() -> StarraGuitarBank:
    global _BANK
    if _BANK is None:
        with _BANK_LOCK:
            if _BANK is None:
                _BANK = StarraGuitarBank(
                    _resource_path(BANK_FILENAME),
                    _resource_path(METADATA_FILENAME),
                )
    return _BANK
