from __future__ import annotations

from virea.data.registry import DatasetRegistry
from virea.data.types import PreviewPayload
from virea.motion.codecs import MotionCodec, default_codecs
from virea.pipelines.preview_builder import PreviewBuilder
from virea.pipelines.preview_reader import PreviewReader
from virea.pipelines.processing import ProcessingPipeline


class RawPreviewPipeline:
    """Source preview: read persisted snapshot or extract without full VRM conversion."""

    def __init__(
        self, registry: DatasetRegistry, codecs: dict[str, MotionCodec] | None = None
    ) -> None:
        self.registry = registry
        self.codecs = codecs or default_codecs()
        self._processing = ProcessingPipeline(registry, self.codecs)
        self._builder = PreviewBuilder()
        self._reader = PreviewReader(registry)

    def preview(
        self,
        dataset: str,
        sample_id: str,
        max_frames: int | None = None,
        prefer_artifacts: bool = False,
    ) -> PreviewPayload:
        if prefer_artifacts:
            try:
                return self._reader.read_source_preview(
                    dataset, sample_id, max_frames=max_frames
                )
            except FileNotFoundError:
                pass

        adapter = self.registry.adapter(dataset)
        clip = adapter.load(sample_id, max_frames=max_frames)
        source = self.codecs[clip.sample.codec_key].extract_source(clip)
        return self._builder.source_payload(clip, source)
