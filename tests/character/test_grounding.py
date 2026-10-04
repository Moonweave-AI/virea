from virea.character.decision_schema import decision_schema
from virea.character.grounding import explicit_positions


def test_coordinates_are_explicit_recent_and_inside_the_scene():
    assert (
        explicit_positions(
            [
                {"role": "user", "content": "x=1, y=0, z=2"},
                {"role": "assistant", "content": "x=4, y=0, z=6"},
                {"role": "user", "content": "去旁边"},
            ]
        )
        == []
    )
    assert explicit_positions([{"role": "user", "content": "X：-2，Y：0，Z：.5"}]) == [
        {"x": -2.0, "y": 0.0, "z": 0.5}
    ]
    for text in ["x=21,y=0,z=0", "x=0,y=6,z=0", "x=0,y=-3,z=0"]:
        assert explicit_positions([{"role": "user", "content": text}]) == []


def test_empty_scene_cannot_decode_a_fabricated_destination():
    schema = decision_schema([], [])
    variants = schema["$defs"]["SceneAction"]["oneOf"]
    assert [action["properties"]["kind"]["const"] for action in variants] == [
        "stop",
        "stand",
        "perform",
    ]
    assert all(
        action["properties"]["position"] == {"type": "null"} for action in variants
    )
