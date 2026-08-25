from __future__ import annotations

import ctypes
import errno
import struct

import pytest
import virea_runtime.process_identity as process_identity


def _procargs_fixture(
    *,
    executable: str = "/usr/bin/python3",
    argv: tuple[str, ...] = (
        "/usr/bin/python3",
        "-m",
        "virea_model_sdk.worker",
    ),
    environment: tuple[str, ...] = ("HOME=/Users/test",),
    padding: int = 3,
    argc: int | None = None,
) -> bytes:
    values = (
        struct.pack("=i", len(argv) if argc is None else argc),
        executable.encode(),
        b"\0",
        b"\0" * padding,
        *(value.encode() + b"\0" for value in argv),
        *(value.encode() + b"\0" for value in environment),
    )
    return b"".join(values)


@pytest.mark.parametrize("padding", [0, 1, 3, 15])
def test_macos_procargs_parser_handles_padding_and_stops_before_environment(
    padding: int,
) -> None:
    argv = (
        "/usr/bin/python3",
        "-m",
        "virea_model_sdk.worker",
        "--prompt",
        "walk forward",
        "A=B",
    )
    data = _procargs_fixture(
        argv=argv,
        environment=(
            "HOME=/Users/test",
            "--job-id=must-not-become-an-argument",
        ),
        padding=padding,
    )

    executable, parsed_argv = process_identity._parse_macos_procargs(data, 41)

    assert executable == "/usr/bin/python3"
    assert parsed_argv == argv


def test_macos_procargs_parser_fails_closed_for_truncated_argv() -> None:
    data = _procargs_fixture(
        argv=("/usr/bin/python3", "-m"),
        environment=(),
        argc=3,
    )

    with pytest.raises(
        process_identity.ProcessInspectionError,
        match="truncated KERN_PROCARGS2 argv",
    ):
        process_identity._parse_macos_procargs(data, 42)


def test_macos_procargs_reads_argmax_capacity_without_process_size_preflight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _procargs_fixture(padding=7)
    calls: list[tuple[int, ...]] = []

    class FakeFunction:
        argtypes: object = None
        restype: object = None

        def __call__(self, mib, count, output, output_size, _newp, _newlen):
            names = tuple(int(mib[index]) for index in range(count))
            calls.append(names)
            size_pointer = ctypes.cast(output_size, ctypes.POINTER(ctypes.c_size_t))
            if names == (1, 8):
                ctypes.cast(output, ctypes.POINTER(ctypes.c_int))[0] = 4096
                size_pointer[0] = ctypes.sizeof(ctypes.c_int)
                return 0
            assert names == (1, 49, 43)
            assert output is not None
            assert size_pointer[0] == 4096 + struct.calcsize("=i")
            ctypes.memmove(output, payload, len(payload))
            size_pointer[0] = len(payload)
            return 0

    class FakeLibC:
        sysctl = FakeFunction()

    monkeypatch.setattr(process_identity.ctypes, "CDLL", lambda *_a, **_k: FakeLibC())

    result = process_identity._macos_procargs(43)

    assert result is not None
    executable, argv = result
    assert executable == "/usr/bin/python3"
    assert argv == (
        "/usr/bin/python3",
        "-m",
        "virea_model_sdk.worker",
    )
    assert calls == [(1, 8), (1, 49, 43)]


def test_macos_creation_token_uses_proc_bsdinfo_microseconds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[int, int, int]] = []

    class FakeFunction:
        argtypes: object = None
        restype: object = None

        def __call__(self, pid, flavor, _arg, output, output_size):
            calls.append((pid, flavor, output_size))
            info = ctypes.cast(
                output, ctypes.POINTER(process_identity._DarwinProcBsdInfo)
            ).contents
            info.pbi_pid = pid
            info.pbi_start_tvsec = 1_725_000_001
            info.pbi_start_tvusec = 73
            return ctypes.sizeof(info)

    class FakeLibProc:
        proc_pidinfo = FakeFunction()

    monkeypatch.setattr(
        process_identity.ctypes, "CDLL", lambda *_a, **_k: FakeLibProc()
    )

    token = process_identity._macos_creation_token(44)

    assert token == "1725000001.000073"
    assert ctypes.sizeof(process_identity._DarwinProcBsdInfo) == 136
    assert process_identity._DarwinProcBsdInfo.pbi_start_tvsec.offset == 120
    assert process_identity._DarwinProcBsdInfo.pbi_start_tvusec.offset == 128
    assert calls == [(44, 3, 136)]


def test_macos_creation_token_only_treats_esrch_as_process_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeFunction:
        argtypes: object = None
        restype: object = None
        error = errno.ESRCH

        def __call__(self, *_args):
            ctypes.set_errno(self.error)
            return 0

    class FakeLibProc:
        proc_pidinfo = FakeFunction()

    library = FakeLibProc()
    monkeypatch.setattr(process_identity.ctypes, "CDLL", lambda *_a, **_k: library)

    assert process_identity._macos_creation_token(45) is None

    library.proc_pidinfo.error = 0
    with pytest.raises(
        process_identity.ProcessInspectionError,
        match="returned 0 bytes with errno 0",
    ):
        process_identity._macos_creation_token(45)


def test_macos_inspection_retries_transient_spawn_exec_truncation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    argv = ("/usr/bin/python3", "-m", "virea_model_sdk.worker")
    procargs_results: list[
        process_identity.ProcessInspectionError | tuple[str, tuple[str, ...]]
    ] = [
        process_identity.ProcessInspectionError(
            "Worker process 45 has truncated KERN_PROCARGS2 argv"
        ),
        (argv[0], argv),
        (argv[0], argv),
    ]
    sleeps: list[float] = []

    def read_procargs(_pid: int) -> tuple[str, tuple[str, ...]]:
        value = procargs_results.pop(0)
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(
        process_identity, "_macos_creation_token", lambda _pid: "1725000001.1"
    )
    monkeypatch.setattr(process_identity, "_macos_procargs", read_procargs)
    monkeypatch.setattr(process_identity.time, "sleep", sleeps.append)

    identity = process_identity._inspect_macos_process(45)

    assert identity is not None
    assert identity.creation_token == "1725000001.1"
    assert identity.argv == argv
    assert sleeps == [process_identity._MACOS_INSPECTION_RETRY_SECONDS]
    assert not procargs_results


def test_macos_inspection_retries_command_line_change_during_exec(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    launcher = ("/usr/libexec/spawn-helper",)
    worker = ("/usr/bin/python3", "-m", "virea_model_sdk.worker")
    procargs_results = [
        (launcher[0], launcher),
        (worker[0], worker),
        (worker[0], worker),
        (worker[0], worker),
    ]

    monkeypatch.setattr(
        process_identity, "_macos_creation_token", lambda _pid: "1725000001.2"
    )
    monkeypatch.setattr(
        process_identity, "_macos_procargs", lambda _pid: procargs_results.pop(0)
    )
    monkeypatch.setattr(process_identity.time, "sleep", lambda _delay: None)

    identity = process_identity._inspect_macos_process(46)

    assert identity is not None
    assert identity.argv == worker
    assert not procargs_results


def test_macos_inspection_never_retries_into_reused_pid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    creation_tokens = ["old-process", "new-process"]
    calls = 0

    def read_procargs(_pid: int):
        nonlocal calls
        calls += 1
        raise process_identity.ProcessInspectionError("transient KERN_PROCARGS2 read")

    monkeypatch.setattr(
        process_identity,
        "_macos_creation_token",
        lambda _pid: creation_tokens.pop(0),
    )
    monkeypatch.setattr(process_identity, "_macos_procargs", read_procargs)
    monkeypatch.setattr(process_identity.time, "sleep", lambda _delay: None)

    identity = process_identity._inspect_macos_process(47)

    assert identity is None
    assert calls == 1
    assert not creation_tokens


def test_macos_inspection_permanent_failure_remains_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def fail_procargs(_pid: int):
        nonlocal calls
        calls += 1
        raise process_identity.ProcessInspectionError("permanent read failure")

    monkeypatch.setattr(
        process_identity, "_macos_creation_token", lambda _pid: "stable-process"
    )
    monkeypatch.setattr(process_identity, "_macos_procargs", fail_procargs)
    monkeypatch.setattr(process_identity.time, "sleep", lambda _delay: None)

    with pytest.raises(
        process_identity.ProcessInspectionError,
        match="cannot establish stable identity.*after 6 attempts",
    ):
        process_identity._inspect_macos_process(48)

    assert calls == process_identity._MACOS_INSPECTION_ATTEMPTS
