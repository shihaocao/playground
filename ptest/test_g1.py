import anyio
import pytest
import logging
import functools
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Callable, Any
import inspect



import anyio
import functools

def background_task_handler(func):
    """
    Wrap an async-generator fixture so:
      - background exceptions don't hang the test
      - the test body isn't cancelled (we re-raise the real traceback at teardown)
      - the original generator is always closed cleanly
    """
    @functools.wraps(func)
    async def wrapped(*args, **kwargs):
        yielded_evt = anyio.Event()
        state = {"value": None, "exc": None}
        agen = None  # the original async-generator fixture

        async def driver():
            nonlocal agen
            agen = func(*args, **kwargs)
            try:
                # Advance to first `yield` of the original fixture
                state["value"] = await agen.asend(None)
                yielded_evt.set()
                # Keep it alive until teardown
                await anyio.sleep_forever()
            except anyio.get_cancelled_exc_class():
                # Normal during teardown
                raise
            except BaseException as e:
                # Record the first real error with its traceback
                state["exc"] = e
                yielded_evt.set()
                # Let the error propagate to the task group (it will cancel us),
                # but the parent is shielded during the test body.
                raise

        try:
            async with anyio.create_task_group() as tg:
                tg.start_soon(driver)

                # Wait until the fixture has yielded (or failed)
                await yielded_evt.wait()

                # Run the test body shielded so TG cancellation won't nuke it
                with anyio.CancelScope(shield=True):
                    # If we already have an error before the test body starts,
                    # fail fast with the original traceback.
                    if state["exc"] is not None:
                        raise state["exc"]

                    try:
                        # Hand the yielded value to the test
                        yield state["value"]
                    finally:
                        # Teardown: stop the background task
                        tg.cancel_scope.cancel()
        finally:
            # Ensure the original async generator is closed exactly once here
            if agen is not None:
                try:
                    await agen.aclose()
                except BaseException as e:
                    # Preserve the first error if we don't already have one
                    if state["exc"] is None:
                        state["exc"] = e

        # If the background failed while the test was running, re-raise now
        if state["exc"] is not None:
            raise state["exc"]

    return wrapped



# Example usage - simple and clean
@pytest.fixture
@background_task_handler
async def background_task_fail():
    fail_after = 1
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
    await anyio.sleep(10)  # Give background task time to fail
    assert True


# Test examples
@pytest.mark.anyio
async def test_background_success(background_task_success):
    logging.info("Test starting")
    await anyio.sleep(2)  # Give background task time to fail
    assert True