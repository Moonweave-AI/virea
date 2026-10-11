import json

from scripts.character import build_unified_gallery as gallery


def test_new_recording_does_not_reuse_an_older_github_video(tmp_path, monkeypatch):
    monkeypatch.setattr(gallery, "ROOT", tmp_path)
    directory = tmp_path / "doc/assets/unified-motion-demos"
    directory.mkdir(parents=True)
    url = "https://github.com/user-attachments/assets/5a641799-897b-4f66-934e-22227d4a27b3"
    (directory / "github-videos.json").write_text(
        json.dumps({"motioncraft-01-introduction": {"sha256": "a" * 64, "url": url}}),
        encoding="utf-8",
    )
    entry = {
        "id": "motioncraft-01-introduction",
        "title": "介绍",
        "title_en": "Introduction",
        "duration_seconds": 32,
        "motions": [1],
        "speech": [1],
        "backend": "motioncraft",
        "hashes": {"mp4": "a" * 64},
    }
    assert f'<video src="{url}" controls muted' in gallery.table([entry], False)
    entry["hashes"]["mp4"] = "b" * 64
    changed = gallery.table([entry], False)
    assert url not in changed
    assert (
        "raw/refs/heads/main/doc/assets/unified-motion-demos/motioncraft-01-introduction.mp4"
        in changed
    )
    entry.pop("hashes")
    assert "<video" not in gallery.table([entry], False)
