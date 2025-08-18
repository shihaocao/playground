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


try:
    import trio
except ImportError:
    trio = None

if trio:
    class CrashLoggerInstrument(trio.abc.Instrument):
        def task_failed(self, task, exc):
            tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            logging.error("Trio task crashed: %r\n%s", getattr(task, "name", task), tb)
            # Optional: make it visible even if log capture is off:
            # print(f"Trio task crashed: {task!r}\n{tb}", file=sys.stderr, flush=True)

    @pytest.fixture(autouse=True)
    async def _install_trio_crash_logger():
        # Only run if we're actually under Trio
        try:
            trio.lowlevel.current_trio_token()
        except RuntimeError:
            # Not in a Trio run (e.g., asyncio backend)
            yield
            return

        inst = CrashLoggerInstrument()
        trio.lowlevel.add_instrument(inst)
        try:
            yield
        finally:
            trio.lowlevel.remove_instrument(inst)


def background_task_handler(func):
    """
    Wrap an async-generator fixture so:
      - background exceptions don't hang the test
      - the test body isn't cancelled (we re-raise the real traceback at teardown)
      - the original generator is always closed cleanly
    """
    @functools.wraps(func)
    async def wrapped(*args, **kwargs):
        logging.warning("[wrapped] starting wrapper for %s", func.__name__)
        yielded_evt = anyio.Event()
        state = {"value": None, "exc": None}
        agen = None  # the original async-generator fixture

        async def driver():
            nonlocal agen
            logging.warning("[driver] starting driver for %s", func.__name__)
            agen = func(*args, **kwargs)
            try:
                logging.warning("[driver] advancing to first yield")
                state["value"] = await agen.asend(None)
                logging.warning("[driver] fixture yielded first value: %r", state["value"])
                yielded_evt.set()
                logging.warning("[driver] sleeping forever until cancelled")
                await anyio.sleep_forever()
            except anyio.get_cancelled_exc_class():
                logging.warning("[driver] got CancelledError (normal during teardown)")
                raise
            except BaseException as e:
                logging.warning("[driver] caught BaseException in background task: %r", e)
                logging.error("Background task failed immediately:\n%s", traceback.format_exc())
                state["exc"] = e
                yielded_evt.set()
                logging.warning("[driver] re-raising background exception to task group")
                raise

        try:
            logging.warning("[wrapped] creating task group")
            async with anyio.create_task_group() as tg:
                tg.start_soon(driver)
                logging.warning("[wrapped] waiting for fixture to yield or fail")
                await yielded_evt.wait()
                logging.warning("[wrapped] yielded_evt triggered")

                with anyio.CancelScope(shield=True):
                    logging.warning("[wrapped] entering shielded CancelScope for test body")
                    if state["exc"] is not None:
                        logging.warning("[wrapped] state.exc already set before test body")
                        raise state["exc"]

                    try:
                        logging.warning("[wrapped] yielding value to test body")
                        yield state["value"]
                    finally:
                        logging.warning("[wrapped] test body finished, cancelling task group")
                        tg.cancel_scope.cancel()
        finally:
            logging.warning("[wrapped] finally block starting")
            if agen is not None:
                try:
                    logging.warning("[wrapped] closing original async generator")
                    await agen.aclose()
                except BaseException as e:
                    logging.warning("[wrapped] exception during agen.aclose(): %r", e)
                    logging.error("Error during async generator close:\n%s", traceback.format_exc())
                    if state["exc"] is None:
                        logging.warning("[wrapped] storing close error as state.exc")
                        state["exc"] = e

        if state["exc"] is not None:
            logging.warning("[wrapped] re-raising stored exception at end of fixture")
            raise state["exc"]

        logging.warning("[wrapped] fixture completed cleanly")

    return wrapped



# Example usage - simple and clean
@pytest.fixture
@background_task_handler
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
@background_task_handler
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