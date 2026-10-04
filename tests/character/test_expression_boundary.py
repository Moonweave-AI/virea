from types import SimpleNamespace

import numpy as np

from virea.character.contracts import BodyState
from virea.character.coordination import SpeechObservation
from virea.character.expression_boundary import expression_boundary
from virea.motion.canonical import pack_sequence


def test_boundary_follows_audible_time_across_packet_edges(tmp_path):
    angles = np.array([0, np.pi / 2])
    rotations = np.stack(
        [np.zeros(2), np.sin(angles / 2), np.zeros(2), np.cos(angles / 2)], axis=-1
    )
    np.savez(
        tmp_path / "canonical211.npz",
        sequence=pack_sequence(np.zeros((2, 3)), rotations),
    )
    control = SimpleNamespace(
        paths=SimpleNamespace(result_directory=lambda _: tmp_path)
    )
    packets = [
        dict(
            id=str(i),
            stream_id="s",
            offset_seconds=i * 2,
            audio_seconds=2,
            motion_status="ready",
            motion=dict(result_id=str(i)),
        )
        for i in range(2)
    ]
    speech = SpeechObservation(active=True, packet_id="0", remaining_seconds=1)
    result = expression_boundary(control, packets, speech, 1.1, BodyState(), fps=20)
    assert result["stream_offset"] == 2.1
    assert [s["packet_id"] for s in result["sources"]] == ["0", "1", "1", "1"]
    for sample in result["samples"]:
        for q in sample["pose"].values():
            np.testing.assert_allclose(np.linalg.norm(q), 1, atol=1e-6)
    last = result["samples"][-1]["pose"]["hips"]
    np.testing.assert_allclose(last[1], np.sin(np.pi / 80), atol=1e-6)
    packets[1]["motion_status"] = "pending"
    assert (
        expression_boundary(control, packets, speech, 1.1, BodyState(), fps=20) is None
    )


def test_no_native_boundary_is_invented_without_active_speech():
    assert (
        expression_boundary(None, [], SpeechObservation(), 2, BodyState(), fps=20)
        is None
    )
