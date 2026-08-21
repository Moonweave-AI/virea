from __future__ import annotations

import pytest
from pydantic import ValidationError
from virea_api.routes.models import InstallRequest
from virea_cli.commands.model import _named_install_values
from virea_cli.main import build_parser


def test_cli_accepts_explicit_external_root_and_revision_pairs() -> None:
    args = build_parser().parse_args(
        [
            "model",
            "install",
            "prism-tp2m-1-4b",
            "--apply",
            "--artifact-root",
            "prism-source=/opt/prism/source",
            "--artifact-revision",
            "prism-source=3c58bc5d946f0827171a3712ed36314f4b1a5186",
        ]
    )
    assert args.artifact_root == ["prism-source=/opt/prism/source"]
    assert args.artifact_revision == [
        "prism-source=3c58bc5d946f0827171a3712ed36314f4b1a5186"
    ]
    assert _named_install_values(args.artifact_root, option="--artifact-root") == {
        "prism-source": "/opt/prism/source"
    }


@pytest.mark.parametrize(
    "values",
    (
        ["missing-separator"],
        ["=missing-id"],
        ["missing-value="],
        ["weights=/one", "weights=/two"],
    ),
)
def test_cli_external_root_parser_rejects_ambiguous_values(values) -> None:
    with pytest.raises(ValueError):
        _named_install_values(values, option="--artifact-root")


def test_api_external_root_contract_requires_matching_revision_ids() -> None:
    request = InstallRequest(
        model_id="prism-tp2m-1-4b",
        apply=True,
        artifact_roots={"weights": "/opt/prism/weights"},
        artifact_revisions={"weights": "pinned-revision"},
    )
    assert request.artifact_roots == {"weights": "/opt/prism/weights"}
    with pytest.raises(ValidationError, match="identical IDs"):
        InstallRequest(
            model_id="prism-tp2m-1-4b",
            apply=True,
            artifact_roots={"weights": "/opt/prism/weights"},
            artifact_revisions={},
        )
