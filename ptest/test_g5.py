import sys
import anyio
import functools
import logging
import traceback
import anyio
import pytest
import logging
import functools
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Callable, Any
import inspect
import sys


import anyio
import functools
import os
import sys
import time
import signal
import threading
import faulthandler
import pytest


HARD_TIMEOUT_DEFAULT = 6  # second

@pytest.fixture(autouse=True)
def hard_timeout_watchdog(request):
    """
    Per-test hard timeout. If the test (setup -> call -> teardown) exceeds the
    timeout, dump all thread stacks and kill the whole pytest process.

    Configure with env var: PYTEST_HARD_TIMEOUT=<seconds>
    """
    timeout = int(os.getenv("PYTEST_HARD_TIMEOUT", HARD_TIMEOUT_DEFAULT))
    start = time.monotonic()
    cancelled = threading.Event()

    def _kill_now():
        os._exit(124)  # 124 is a common "timeout" exit code

    def _watchdog():
        # Poll so we can cancel promptly
        while not cancelled.wait(0.1):
            if time.monotonic() - start >= timeout:
                _kill_now()

    t = threading.Thread(target=_watchdog, name="pytest-hard-timeout", daemon=True)
    t.start()
    try:
        yield
    finally:
        # Cancel the watchdog after the test (including teardown) completes
        cancelled.set()
        # Don't join a daemon thread; if teardown hangs, the watchdog will still fire
        logging.warning("Hard timeout watchdog stopped")

# Example usage - simple and clean
@pytest.fixture
async def background_task_fail():
    fail_after = 1
    async def worker():
        try:
            start_time = anyio.current_time()
            while True:
                logging.info("Background task running")
                if anyio.current_time() - start_time > fail_after:
                    raise RuntimeError(f"Background task failed after {fail_after}s")
                await anyio.sleep(0.1)
        except BaseException as e:
            te = traceback.TracebackException.from_exception(e, capture_locals=True)
            logging.error("Background task crashed (with locals):\n%s", "".join(te.format(chain=True)))
            raise

    async with anyio.create_task_group() as tg:
        tg.start_soon(worker)
        yield  # Yield control to the test while the background task runs
        logging.info("Yielding control back to fixture")
        # The decorator will handle cancellation and error propagation


@pytest.fixture
async def background_task_success():
    fail_after = 3
    async def worker():
        start_time = anyio.current_time()
        while True:
            logging.info("Background task running")
            if anyio.current_time() - start_time > fail_after:
                raise RuntimeError(f"Background task failed after {fail_after}s")
            await anyio.sleep(0.1)

    async with anyio.create_task_group() as tg:
        tg.start_soon(worker)
        yield  # Yield control to the test while the background task runs
        logging.info("Yielding control back to fixture")
        # The decorator will handle cancellation and error propagation



# Test examples
@pytest.mark.anyio
async def test_background_fail(background_task_fail):
    logging.info("Test starting")
    await anyio.sleep(3)  # Give background task time to fail
    assert True


# Test examples
@pytest.mark.anyio
async def test_background_success(background_task_success):
    logging.info("Test starting")
    await anyio.sleep(2)  # Give background task time to fail
    assert True

@pytest.mark.anyio
async def test_4s_test1():
    logging.info("Test starting")
    await anyio.sleep(4)  # Give background task time to fail
    assert True


@pytest.mark.anyio
async def test_4s_test2():
    logging.info("Test starting")
    await anyio.sleep(4)  # Give background task time to fail
    assert True