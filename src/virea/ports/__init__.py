"""Dependency-neutral capability boundaries used by application services."""

from typing import Protocol

from virea_contracts.performance import (
    AudioArtifactV1,
    ExecutablePerformanceV1,
    ExecutionCommandV1,
    ExecutionReceiptV1,
    InteractionRequestV1,
    MotionRequestV1,
    NativeMotionArtifactV1,
    ResponsePlanV1,
)


class LanguagePort(Protocol):
    async def plan(
        self, request: InteractionRequestV1, context: dict
    ) -> ResponsePlanV1: ...


class AudioPort(Protocol):
    async def synthesize(self, text: str) -> AudioArtifactV1: ...


class MotionPort(Protocol):
    async def generate(
        self, request: MotionRequestV1, *, resolve_before, resolve_all, record
    ) -> NativeMotionArtifactV1:
        """Resolve measured audio lazily; native history stays with the provider."""
        ...


class MotionAdapterPort(Protocol):
    def normalize(self, native: NativeMotionArtifactV1):
        """Return the existing virea_motion_ir.MotionIR, preserving auxiliary tracks."""
        ...


class EmbodimentPort(Protocol):
    async def execute(
        self,
        command: ExecutionCommandV1,
        performance: ExecutablePerformanceV1,
    ) -> ExecutionReceiptV1: ...
