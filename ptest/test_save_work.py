import anyio
import pytest
import logging
from contextlib import asynccontextmanager

ERROR_AFTER_SECONDS = 1  # seconds before the worker raises

@asynccontextmanager
async def background_worker():
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
    async with anyio.create_task_group() as tg:
        tg.start_soon(worker)
        try:
            # run the test body here
            yield
        except* RuntimeError as eg:
            # catch the worker’s exception group immediately
            logging.info("Swallowed background task errors: %s", eg)
        finally:
            # always run cleanup, inside Trio
            logging.info("Background task cleanup complete")
            tg.cancel_scope.cancel()


@pytest.fixture
async def background_task():
    # simply enter the asynccontextmanager
    async with background_worker():
        yield


@pytest.mark.anyio
async def test_background_fail(background_task):
    logging.info("hello")
    # At ~1s the worker raises; we catch above, then tear down the nursery;
    # this sleep will continue un-cancelled and the test will finish cleanly.
    await anyio.sleep(2)
    assert True
