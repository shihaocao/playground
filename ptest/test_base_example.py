import anyio
import pytest
import logging


@pytest.fixture
async def background_task_fail():
    async def worker():
        start = anyio.current_time()
        while True:
            logging.info("Background task running")
            if anyio.current_time() - start > 1:
                raise RuntimeError(f"Background task failed after {ERROR_AFTER_SECONDS}s")
            await anyio.sleep(0.1)

    async with anyio.create_task_group() as tg:
        tg.start_soon(worker)
        yield


@pytest.mark.anyio
async def test_background_fail(background_task_fail):
    logging.info("hello")
    await anyio.sleep(2)  # Give background task time to run
    assert True