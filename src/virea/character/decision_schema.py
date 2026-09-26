"""Expose mode invariants to constrained decoders, not just Python validation."""

from __future__ import annotations

from copy import deepcopy

from .contracts import Decision


def decision_schema() -> dict:
    schema = Decision.model_json_schema()
    actions = []
    for kind in ("stop", "look_at", "move_to"):
        for destination in (None,) if kind == "stop" else ("target_id", "position"):
            properties = {
                "kind": {"const": kind, "type": "string"},
                "target_id": {"type": "null"},
                "position": {"type": "null"},
            }
            required = ["kind"]
            if destination:
                properties[destination] = (
                    {"type": "string", "minLength": 1, "maxLength": 80}
                    if destination == "target_id"
                    else {"$ref": "#/$defs/Position"}
                )
                required.append(destination)
            actions.append(
                {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                    "additionalProperties": False,
                }
            )
    schema["$defs"]["SceneAction"] = {"oneOf": actions}
    variants = []
    for mode in ("SPEAK", "ACT_SILENTLY", "WAIT"):
        properties = deepcopy(schema["properties"])
        properties["mode"] = {"const": mode, "type": "string"}
        if mode == "SPEAK":
            properties["text"]["minLength"] = 1
        else:
            properties["text"] = {"const": "", "type": "string"}
        if mode == "WAIT":
            properties["actions"]["maxItems"] = 0
        elif mode == "ACT_SILENTLY":
            properties["actions"]["minItems"] = 1
        variants.append(
            {
                "type": "object",
                "properties": properties,
                "required": ["mode", "text", "actions"],
                "additionalProperties": False,
            }
        )
    return {"$defs": schema["$defs"], "oneOf": variants}
