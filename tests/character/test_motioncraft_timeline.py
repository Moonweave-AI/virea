from types import SimpleNamespace

import numpy as np
from scipy.spatial.transform import Rotation

from scripts.character.unified_motion.motioncraft_timeline import (
    blend_gestures,
    connect_native_clip,
    speech_gesture_weights,
)
from virea.character.performance_contracts import MotionSegment


def test_physical_actions_keep_body_ownership_during_speech():
    action = MotionSegment(
        id="walk", start_seconds=0, duration_seconds=4, prompt="A person walks forward."
    )
    request = SimpleNamespace(
        audio_start_frame=0, motions=[action], speech_ranges=[(1, 6)]
    )
    weights = speech_gesture_weights(request, 180)
    assert not weights[:120].any()
    assert weights[135:165].min() == 1
    request.audio_start_frame = 90
    np.testing.assert_allclose(speech_gesture_weights(request, 90), weights[90:])


def test_conversational_segments_fade_in_on_the_audio_timeline():
    action = MotionSegment(
        id="talk",
        start_seconds=0,
        duration_seconds=4,
        prompt="A person gestures during a speech.",
        speech_gestures=True,
    )
    request = SimpleNamespace(
        audio_start_frame=0, motions=[action], speech_ranges=[(1, 3)]
    )
    weights = speech_gesture_weights(request, 120)
    assert not weights[:30].any() and not weights[90:].any()
    assert 0 < weights[30] < weights[35] <= 1


def test_gesture_blending_preserves_root_legs_and_rotation_equivalence():
    rng = np.random.default_rng(3)
    text = rng.normal(0, 0.2, (30, 322)).astype(np.float32)
    speech = rng.normal(0, 0.2, text.shape).astype(np.float32)
    out = blend_gestures(text, speech, np.ones(30))
    np.testing.assert_array_equal(out[:, :36], text[:, :36])
    np.testing.assert_array_equal(out[:, 156:], text[:, 156:])
    np.testing.assert_allclose(
        Rotation.from_rotvec(out[:, 48:51]).as_matrix(),
        Rotation.from_rotvec(speech[:, 48:51]).as_matrix(),
        atol=1e-6,
    )
    np.testing.assert_allclose(
        blend_gestures(text, speech, np.zeros(30)), text, atol=1e-6
    )


def test_clip_connection_preserves_travel_and_does_not_edit_sources():
    previous = np.zeros((16, 322), dtype=np.float32)
    previous[:, 309] = np.arange(16) / 30
    previous[:, 48] = 0.4
    current = np.zeros((60, 322), dtype=np.float32)
    current[:, 309] = np.arange(60) / 30
    out = connect_native_clip(previous, current)
    assert out[0, 309] > previous[-1, 309]
    np.testing.assert_allclose(np.diff(out[:, 309]), 1 / 30, atol=1e-6)
    np.testing.assert_allclose(out[0, 48:51], previous[-1, 48:51], atol=1e-6)
    np.testing.assert_allclose(out[12:, 48:51], 0)
    assert not current[:, 48].any()
