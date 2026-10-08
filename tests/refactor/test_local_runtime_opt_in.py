import pytest
from virea_core.paths import VireaPaths


def checkout(tmp_path):
    root = tmp_path / "project"
    (root / "src/virea").mkdir(parents=True)
    (root / "src/virea/__init__.py").write_text("")
    (root / "registries/bundles").mkdir(parents=True)
    (root / "registries/bundles/release-assets.v1.json").write_text("{}")
    (root / "pyproject.toml").write_text("[project]\n")
    (root / ".gitignore").write_text("/.virea-runtime/\n")
    return root


def test_checkout_runtime_requires_explicit_opt_in(tmp_path, monkeypatch):
    root = checkout(tmp_path)
    paths = VireaPaths(root / ".virea-runtime/vrchat/home")
    monkeypatch.delenv("VIREA_ALLOW_CHECKOUT_RUNTIME", raising=False)
    with pytest.raises(ValueError, match="must be outside"):
        paths.ensure_layout()
    monkeypatch.setenv("VIREA_ALLOW_CHECKOUT_RUNTIME", "1")
    paths.ensure_layout()
    assert paths.state.is_dir() and paths.model_assets.is_dir()


@pytest.mark.parametrize(
    "name",
    [".", "src", "runtime-data", ".virea-runtime-lookalike", ".virea-runtime/../src"],
)
def test_opt_in_never_allows_source_or_similarly_named_directories(
    tmp_path, monkeypatch, name
):
    root = checkout(tmp_path)
    monkeypatch.setenv("VIREA_ALLOW_CHECKOUT_RUNTIME", "1")
    with pytest.raises(ValueError, match="must be outside"):
        VireaPaths(root / name).ensure_layout()


def test_opt_in_requires_runtime_to_be_git_ignored(tmp_path, monkeypatch):
    root = checkout(tmp_path)
    monkeypatch.setenv("VIREA_ALLOW_CHECKOUT_RUNTIME", "1")
    (root / ".gitignore").write_text("/.cache/\n")
    with pytest.raises(ValueError, match="must be outside"):
        VireaPaths(root / ".virea-runtime/vrchat/home").ensure_layout()
