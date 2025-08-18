import anyio
import pytest
import logging
import time


@pytest.fixture
async def background_task_fail():
    async def worker():
        start = time.time()
        while True:
            logging.info("Background task running")
            await anyio.sleep(0.1)
            if time.time() - start > 1:
                logging.error("Background task error!")
                raise RuntimeError("Something failed")

    async with anyio.create_task_group() as tg:
        tg.start_soon(worker)
        try:
            yield
        finally:
            tg.cancel_scope.cancel()  # Explicit cleanup if needed

@pytest.mark.anyio
async def test_background_fail(background_task_fail):
    logging.info("Test starting")
    await anyio.sleep(2)  # This should fail when background task raises
    assert True