from __future__ import annotations

from pathlib import Path

from virea_dart.backend import _yaml_mapping


def test_tyro_tagged_args_are_loaded_as_inert_data(tmp_path: Path) -> None:
    path = tmp_path / "args.yaml"
    path.write_text(
        '"!dataclass:MLDArgs\\n'
        "denoiser_args: !dataclass:DenoiserArgs\\n"
        "  model_args: !dataclass:DenoiserTransformerArgs\\n"
        "    noise_shape: !!python/tuple\\n"
        "    - 1\\n"
        '    - 256\\n"\n',
        encoding="utf-8",
    )
    payload = _yaml_mapping(path)
    assert payload["denoiser_args"]["model_args"]["noise_shape"] == [1, 256]
