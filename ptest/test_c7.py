import anyio
import pytest
import logging


ERROR_AFTER_SECONDS = 1  # seconds before the worker raises


# Option 1: Using a cancel scope to stop the test (FIXED)
@pytest.fixture
async def background_task_fail():
    async def worker(cancel_scope):
        start = anyio.current_time()
        try:
            while True:
                logging.info("Background task running")
                if anyio.current_time() - start > ERROR_AFTER_SECONDS:
                    raise RuntimeError(f"Background task failed after {ERROR_AFTER_SECONDS}s")
                await anyio.sleep(0.1)
        except Exception as e:
            logging.error(f"Background task failed: {e}")
            cancel_scope.cancel()  # Cancel the entire scope
            raise

    with anyio.CancelScope() as cancel_scope:  # Regular context manager, not async
        async with anyio.create_task_group() as tg:
            tg.start_soon(worker, tg.cancel_scope)
            try:
                yield
            finally:
                if cancel_scope.cancelled_caught:
                    raise RuntimeError("Background task failed and cancelled the test")


@pytest.mark.anyio
async def test_background_fail(background_task_fail):
    logging.info("hello")
    await anyio.sleep(2)  # Give background task time to run
    assert True