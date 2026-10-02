from scripts.check_docs import owner_directed_recording


def test_recording_direction_requires_basis_and_existing_provenance():
    policy = dict(
        kind="owner-directed-recorded-performance",
        decision="owner-directed-display-permission-unverified",
        legal_permission_verified=False,
        publication_basis="Explicit repository owner request to record and publish demos",
        provenance="README.md",
    )
    assert owner_directed_recording(policy)
    for field in ("publication_basis", "provenance", "decision"):
        assert not owner_directed_recording({**policy, field: None})
    assert not owner_directed_recording({**policy, "legal_permission_verified": True})
    assert not owner_directed_recording(
        {**policy, "provenance": "missing-provenance.md"}
    )
