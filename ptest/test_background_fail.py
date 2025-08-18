import anyio
import pytest
import logging
import traceback
import sys
from contextlib import asynccontextmanager

ERROR_AFTER_SECONDS = 1  # seconds before the worker raises

@asynccontextmanager
async def background_worker():
    background_tracebacks = []
    
    async def worker():
        start_time = anyio.current_time()
        while True:
            logging.info("Background task running")
            if anyio.current_time() - start_time > ERROR_AFTER_SECONDS:
                raise RuntimeError(
                    f"Background task failed after {ERROR_AFTER_SECONDS}s"
                )
            await anyio.sleep(0.1)

    # Start the nursery and your worker:
    try:
        async with anyio.create_task_group() as tg:
            tg.start_soon(worker)
            with anyio.CancelScope(shield=True):
                try:
                    # run the test body here, shielded from cancellation
                    yield background_tracebacks
                finally:
                    # always run cleanup, inside Trio
                    logging.info("Background task cleanup complete")
                    tg.cancel_scope.cancel()
    except* RuntimeError as eg:
        # capture the worker's exception group with full traceback info
        background_tracebacks.append(eg)
        logging.info("Captured background task errors: %s", eg)
        
    # Re-raise background errors during teardown if any occurred
    if background_tracebacks:
        logging.error("Background task failed during test execution")
        # Create a new exception that includes the original traceback info
        raise RuntimeError(f"Background task failures detected: ") from background_tracebacks[0]


@pytest.fixture
async def background_task():
    # enter the asynccontextmanager and get access to background_errors
    async with background_worker() as background_errors:
        yield background_errors


@pytest.mark.anyio
async def test_background_fail(background_task):
    logging.info("hello")
    # At ~1s the worker raises; we catch above, then tear down the nursery;
    # this sleep will continue un-cancelled and the test will finish cleanly.
    await anyio.sleep(2)
    
    # Optionally check for background errors during test execution
    if background_task:
        logging.warning(f"Background errors detected during test: {background_task}")
    
    assert True