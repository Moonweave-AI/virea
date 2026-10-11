import json
import subprocess
import sys
from pathlib import Path

from jsonschema import Draft202012Validator
from virea_contracts.schema_export import documents


def test_published_runtime_schemas_match_the_portable_messages():
    root = Path(__file__).resolve().parents[2] / "packages/contracts/schemas/v1"
    for filename, expected in documents():
        actual = (root / filename).read_text(encoding="utf-8")
        assert actual == expected, filename
        Draft202012Validator.check_schema(json.loads(actual))


def test_contract_import_does_not_load_numerical_or_model_runtimes():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys, virea_contracts; "
            "assert not set(('numpy', 'torch', 'virea', 'openvr')) & sys.modules.keys()",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
