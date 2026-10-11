import asyncio
import multiprocessing
import socket
import time

import pytest

from virea.vrchat.contracts import BridgeConfig
from virea.vrchat.osc import decode, message
from virea.vrchat.transport import OSCTransport, reset_packet, sender_process


@pytest.mark.parametrize("failure_at", ["poll", "recv"])
def test_sender_releases_when_windows_pipe_is_broken(failure_at):
    class BrokenPipe:
        closed = False

        def poll(self, timeout):
            if failure_at == "poll":
                raise BrokenPipeError(109, "The pipe has been ended")
            return True

        def recv_bytes(self, limit):
            raise BrokenPipeError(109, "The pipe has been ended")

        def close(self):
            self.closed = True

    pipe = BrokenPipe()
    reset = reset_packet(BridgeConfig())
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver:
        receiver.bind(("127.0.0.1", 0))
        receiver.settimeout(1)
        sender_process(pipe, receiver.getsockname(), reset)
        assert [receiver.recv(65507) for _ in range(3)] == [reset] * 3
    assert pipe.closed


def socket_port():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.mark.parametrize("stop", ["timeout", "pipe_eof"])
def test_independent_sender_releases_without_parent_event_loop(stop):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver:
        receiver.bind(("127.0.0.1", 0))
        receiver.settimeout(8)
        ctx = multiprocessing.get_context("spawn")
        read, write = ctx.Pipe(duplex=False)
        ready = ctx.Event()
        reset = reset_packet(BridgeConfig())
        process = ctx.Process(
            target=sender_process,
            args=(read, receiver.getsockname(), reset, 0.2, ready),
        )
        process.start()
        read.close()
        try:
            # Cold spawn/import time is independent of the dead-man deadline.
            assert ready.wait(30), "OSC child failed to start"
            write.send_bytes(message("/input/Vertical", 0.5))
            assert dict(decode(receiver.recv(65507)))["/input/Vertical"] == [0.5]
            started = time.monotonic()
            if stop == "pipe_eof":
                write.close()
            data = receiver.recv(65507)
            assert dict(decode(data))["/input/Vertical"] == [0.0]
            assert time.monotonic() - started < 1.5
        finally:
            if not write.closed:
                write.close()
            process.join(3)
            if process.is_alive():
                process.terminate()
                process.join(1)
            assert process.exitcode == 0
            process.close()


def test_real_udp_feedback_gate_and_clean_rebind():
    async def run():
        config = BridgeConfig(
            send_port=socket_port(),
            receive_port=socket_port(),
            avatar_id="avtr_expected",
        )
        transport = OSCTransport(config)
        await transport.open()
        try:
            assert not transport.ready()[0]
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
                sender.sendto(
                    message("/avatar/change", "avtr_expected"),
                    ("127.0.0.1", config.receive_port),
                )
                await asyncio.sleep(0.05)
                assert transport.ready()[0]
                sender.sendto(
                    message("/avatar/change", "avtr_other"),
                    ("127.0.0.1", config.receive_port),
                )
                await asyncio.sleep(0.05)
                assert not transport.ready()[0]
        finally:
            await transport.close()
        second = OSCTransport(config)
        await second.open()
        await second.close()

    asyncio.run(run())


def test_slow_sender_shutdown_keeps_handle_and_closes_receiver():
    class SlowProcess:
        def __init__(self):
            self.alive = True
            self.terminated = False
            self.closed = False

        def is_alive(self):
            return self.alive

        def join(self, timeout):
            pass

        def terminate(self):
            self.terminated = True

        def close(self):
            assert not self.alive
            self.closed = True

    async def run():
        transport = OSCTransport(BridgeConfig(receive_port=socket_port()))
        loop = asyncio.get_running_loop()
        transport.receiver, _ = await loop.create_datagram_endpoint(
            lambda: transport.protocol,
            local_addr=("127.0.0.1", transport.config.receive_port),
        )
        child = transport.process = SlowProcess()
        with pytest.raises(RuntimeError, match="did not stop"):
            await transport.close()
        assert child.terminated and not child.closed
        assert transport.receiver is None
        assert transport.process is child
        child.alive = False
        await transport.close()
        assert child.closed and transport.process is None

    asyncio.run(run())


def test_busy_receive_port_fails_without_leaking_sender():
    async def run():
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.bind(("127.0.0.1", 0))
            transport = OSCTransport(BridgeConfig(receive_port=sock.getsockname()[1]))
            with pytest.raises(OSError):
                await transport.open()
            assert transport.process is None

    asyncio.run(run())
