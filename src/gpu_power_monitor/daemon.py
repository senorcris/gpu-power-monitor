import asyncio
import logging
import os
import signal
from typing import Optional

from .config import (
    I2C_BUS, I2C_ADDRESS, I2C_REGISTER,
    REFRESH_INTERVAL, CURRENT_WARN_THRESHOLD, CURRENT_ALERT_THRESHOLD,
    get_socket_path,
)
from .i2c import IT8915Reader
from .gpu import GpuMonitor
from .protocol import MonitorSnapshot

logger = logging.getLogger(__name__)


def _build_alerts(snapshot: MonitorSnapshot) -> list[str]:
    """Check pin currents against thresholds, return alert strings."""
    alerts = []
    if snapshot.connector is None:
        return alerts
    for pin in snapshot.connector.pins:
        amps = pin.current
        if amps >= CURRENT_ALERT_THRESHOLD:
            alerts.append(f"ALERT: {pin.label} current {amps:.2f}A exceeds {CURRENT_ALERT_THRESHOLD}A limit")
        elif amps >= CURRENT_WARN_THRESHOLD:
            alerts.append(f"WARN: {pin.label} current {amps:.2f}A exceeds {CURRENT_WARN_THRESHOLD}A warning")
    return alerts


def _read_snapshot(reader: IT8915Reader, gpu_mon: GpuMonitor) -> MonitorSnapshot:
    """Take one reading from I2C and GPU, return a MonitorSnapshot."""
    try:
        connector = reader.read_pins()
    except Exception as e:
        logger.warning(f"I2C read failed: {e}")
        connector = None

    try:
        gpu = gpu_mon.read_stats()
    except Exception as e:
        logger.warning(f"GPU read failed: {e}")
        gpu = None

    try:
        processes = gpu_mon.get_processes()
    except Exception as e:
        logger.warning(f"Process list failed: {e}")
        processes = []

    snap = MonitorSnapshot(connector=connector, gpu=gpu, processes=processes)
    snap.alerts = _build_alerts(snap)
    return snap


def run_once(bus=None, address=None, register=None) -> str:
    """Single read, returns JSON string."""
    reader = IT8915Reader(
        bus=bus if bus is not None else I2C_BUS,
        address=address if address is not None else I2C_ADDRESS,
        register=register if register is not None else I2C_REGISTER,
    )
    gpu_mon = GpuMonitor()
    try:
        reader.open()
    except Exception as e:
        logger.warning(f"Could not open I2C bus: {e}")
    try:
        gpu_mon.open()
    except Exception as e:
        logger.warning(f"Could not open GPU monitor: {e}")

    try:
        snap = _read_snapshot(reader, gpu_mon)
        return snap.to_json()
    finally:
        reader.close()
        gpu_mon.close()


async def _daemon_main(bus=None, address=None, register=None):
    """Async entry point for the monitoring daemon."""
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    reader = IT8915Reader(
        bus=bus if bus is not None else I2C_BUS,
        address=address if address is not None else I2C_ADDRESS,
        register=register if register is not None else I2C_REGISTER,
    )
    gpu_mon = GpuMonitor()

    try:
        reader.open()
    except Exception as e:
        logger.warning(f"Could not open I2C bus: {e}")
    try:
        gpu_mon.open()
    except Exception as e:
        logger.warning(f"Could not open GPU monitor: {e}")

    clients: set[asyncio.StreamWriter] = set()
    socket_path = get_socket_path()

    async def _broadcast(data: bytes):
        dead = set()
        for writer in clients:
            try:
                writer.write(data)
                await writer.drain()
            except (BrokenPipeError, ConnectionResetError, OSError):
                dead.add(writer)
        for writer in dead:
            clients.discard(writer)
            try:
                writer.close()
            except Exception:
                pass

    async def _poll_loop():
        while not stop_event.is_set():
            snap = await loop.run_in_executor(None, _read_snapshot, reader, gpu_mon)
            data = snap.to_json().encode()
            await _broadcast(data)
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=REFRESH_INTERVAL)
            except asyncio.TimeoutError:
                pass

    async def _on_client(reader_stream: asyncio.StreamReader, writer: asyncio.StreamWriter):
        clients.add(writer)
        peer = writer.get_extra_info("peername") or "unknown"
        logger.info(f"Client connected: {peer}")
        try:
            # Keep connection open until client disconnects or daemon stops
            while not stop_event.is_set():
                # Wait for client disconnect (EOF) or stop signal
                try:
                    data = await asyncio.wait_for(reader_stream.read(1), timeout=1.0)
                    if not data:
                        break
                except asyncio.TimeoutError:
                    continue
        finally:
            clients.discard(writer)
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
            logger.info(f"Client disconnected: {peer}")

    # Clean up stale socket
    if os.path.exists(socket_path):
        os.unlink(socket_path)

    server = await asyncio.start_unix_server(_on_client, path=socket_path)
    logger.info(f"Listening on {socket_path}")

    poll_task = asyncio.create_task(_poll_loop())

    try:
        await stop_event.wait()
    finally:
        logger.info("Shutting down...")
        poll_task.cancel()
        try:
            await poll_task
        except asyncio.CancelledError:
            pass

        # Close all clients
        for writer in list(clients):
            try:
                writer.close()
            except Exception:
                pass
        clients.clear()

        server.close()
        await server.wait_closed()

        reader.close()
        gpu_mon.close()

        # Remove socket file
        if os.path.exists(socket_path):
            os.unlink(socket_path)

        logger.info("Daemon stopped.")


def run_daemon(bus=None, address=None, register=None):
    """Run the daemon (blocking). Call from __main__."""
    asyncio.run(_daemon_main(bus, address, register))
