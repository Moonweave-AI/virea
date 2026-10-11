"""Explicitly registered capabilities translate intent into permitted operations."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Capability:
    arguments: type
    execute: object
    side_effect: str = "read"


class ToolDispatcher:
    def __init__(self, capabilities):
        self.capabilities = dict(capabilities)

    async def dispatch(self, intent, *, allowed_capabilities, allowed_effects):
        if intent.capability not in allowed_capabilities:
            raise ValueError("capability is not authorized for this request")
        capability = self.capabilities.get(intent.capability)
        if capability is None or capability.side_effect not in allowed_effects:
            raise ValueError("capability or side effect is unavailable")
        arguments = capability.arguments.model_validate(intent.arguments)
        return await capability.execute(arguments)
