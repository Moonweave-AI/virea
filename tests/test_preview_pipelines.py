from __future__ import annotations

import numpy as np
import pytest

from virea.data.registry import DatasetRegistry
from virea.pipelines.processed_preview import ProcessedPreviewPipeline
from virea.pipelines.raw_preview import RawPreviewPipeline


@pytest.mark.parametrize("dataset", ["amass", "babel", "beat", "grab", "humanml3d", "motionx", "susuinteracts"])
def test_first_sample_has_raw_and_processed_preview(dataset: str, monkeypatch: pytest.MonkeyPatch) -> None:
    if dataset in {"grab", "susuinteracts"}:
        monkeypatch.setenv("VIREA_ALLOW_TRUSTED_RAW_PICKLE", "1")
    registry = DatasetRegistry.default()
    adapter = registry.adapter(dataset)
    if not adapter.exists():
        pytest.skip(f"raw root not available for {dataset}")
    samples = adapter.discover(limit=1)
    if not samples:
        pytest.skip(f"no samples found for {dataset}")

    raw = RawPreviewPipeline(registry).preview(dataset, samples[0].sample_id, max_frames=8)
    processed = ProcessedPreviewPipeline(registry).preview(dataset, samples[0].sample_id, max_frames=8)

    assert raw.stage == "raw"
    assert processed.stage == "processed"
    assert raw.positions.ndim == 3
    assert processed.positions.ndim == 3
    if raw.positions.shape == processed.positions.shape:
        assert not np.allclose(raw.positions, processed.positions)
    assert raw.positions.shape[0] <= 8
    assert processed.positions.shape[0] <= 8
    assert raw.quality["status"] == "passed"
    assert processed.quality["status"] == "passed"
    assert raw.annotations == processed.annotations
    assert raw.channels == processed.channels
    assert len({item["id"] for item in raw.annotations}) == len(raw.annotations)
    assert all(item["schema_version"] == "virea.annotation.v1.0.0" for item in raw.annotations)
    assert all(item["provenance"] in {"native", "derived", "fallback"} for item in raw.annotations)
    assert all(item["schema_version"] == "virea.channel.v1.0.0" for item in raw.channels)
    assert raw.sample.duration_sec == pytest.approx(raw.positions.shape[0] / raw.fps)
