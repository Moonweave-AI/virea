from __future__ import annotations

from virea.data.registry import DatasetRegistry
from virea.data.types import PreviewPayload
from virea.motion.codecs import MotionCodec, default_codecs
from virea.pipelines.artifacts import motion_uid
from virea.pipelines.preview_builder import PreviewBuilder
from virea.pipelines.preview_reader import PreviewReader
from virea.pipelines.processing import ProcessingPipeline

__all__ = ["ProcessedPreviewPipeline", "motion_uid"]


class ProcessedPreviewPipeline:
    """On-demand processing + preview payload build, or read from persisted artifacts."""

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
        persist: bool = False,
        prefer_artifacts: bool = False,
    ) -> PreviewPayload:
        if persist or not prefer_artifacts:
            output = self._processing.run(
                dataset,
                sample_id,
                max_frames=max_frames,
                persist=persist,
                skip_existing=persist,
            )
            return self._builder.processed_payload(
                output.clip,
                output.canonical,
                source=output.source,
                files=output.paths,
            )

        try:
            return self._reader.read_processed_preview(
                dataset, sample_id, max_frames=max_frames
            )
        except FileNotFoundError:
            output = self._processing.run(
                dataset, sample_id, max_frames=max_frames, persist=False
            )
            return self._builder.processed_payload(
                output.clip,
                output.canonical,
                source=output.source,
            )

    def persist(self, clip, result):  # noqa: ANN001 — backward compat for tests importing persist
        from virea.pipelines.processing import ProcessingOutput

        output = ProcessingOutput(
            clip=clip,
            source=self.codecs[clip.sample.codec_key].extract_source(clip),
            canonical=result,
            quality={},
            motion_uid=motion_uid(
                clip.sample.dataset,
                clip.sample.sample_id,
                int(result.positions.shape[0]),
            ),
            paths={},
        )
        return self._processing.persist(output)
