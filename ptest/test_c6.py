import anyio
import pytest
import logging
import functools
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Callable, Any
import inspect


import anyio
import functools
import logging
from typing import Callable

def background_task_handler(func: Callable) -> Callable:
    """
    Decorator that runs your async fixture in its own task, shields the test from
    cancellation, and always cancels & closes your fixture cleanly—without buffering
    or re-raising errors yourself.
    """
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        fixture_value = None
        fixture_gen = None

        # Runs your fixture body (up to its `yield`), then sleeps forever
        async def fixture_runner():
            nonlocal fixture_value, fixture_gen
            fixture_gen = func(*args, **kwargs)           # call generator
            fixture_value = await fixture_gen.asend(None) # run up to first yield
            await anyio.sleep_forever()                   # keep it alive

        # 1) Launch the fixture_runner in its own task group…
        async with anyio.create_task_group() as tg:
            tg.start_soon(fixture_runner)

            # 2) give it a tick to start & yield
            await anyio.sleep(0.01)

            # 3) shield your test from cancellation
            with anyio.CancelScope(shield=True):
                try:
                    # hand the yielded value through to pytest
                    yield fixture_value
                finally:
                    logging.info("Cleaning up background task")
                    tg.cancel_scope.cancel()

        # 4) once the context exits (either success or error), run your fixture cleanup
        if fixture_gen is not None:
            await fixture_gen.aclose()

    return wrapper


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
    await anyio.sleep(2)  # Give background task time to fail
    assert True


# Test examples
@pytest.mark.anyio
async def test_background_success(background_task_success):
    logging.info("Test starting")
    await anyio.sleep(2)  # Give background task time to fail
    assert True