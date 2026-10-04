"""Reproduce cancellation after inference, before retarget/export completes."""

from threading import Event

from test_resident_workers import completed, resident_control  # noqa: F401


def test_discard_during_normalization_retains_worker(resident_control, monkeypatch):  # noqa: F811
    control, request = resident_control
    completed(control, request)
    original = control.residents._entry.handle
    entered, resume = Event(), Event()
    adapt = control._adapt_native_output

    def delayed(**kwargs):
        entered.set()
        assert resume.wait(5)
        return adapt(**kwargs)

    monkeypatch.setattr(control, "_adapt_native_output", delayed)
    job = control.submit(request, keep_worker_alive=True)
    assert entered.wait(5)
    assert control.store.get_job(job["id"])["state"] == "NORMALIZING"
    control.discard(job["id"])
    resume.set()
    assert control.wait(job["id"], timeout=5)["state"] == "CANCELLED"
    assert control.store.result_for_job(job["id"]) is None
    completed(control, request)
    assert control.residents._entry.handle is original and original.running


def test_character_keepalive_does_not_override_explicit_reclamation(resident_control):  # noqa: F811
    control, request = resident_control
    completed(control, request)
    original = control.residents._entry.handle
    assert control.residents.touch(request.model_id)
    assert not control.residents.touch("another-model")
    control.residents.evict_idle()
    assert not original.running
