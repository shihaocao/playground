import anyio
import pytest
import logging
from contextlib import asynccontextmanager, aclosing


@asynccontextmanager
async def background_task_context():
    """Context manager that properly handles background task lifecycle."""
    ERROR_AFTER_SECONDS = 1  # seconds before the worker raises
    
    async def worker():
        start_time = anyio.current_time()
        while True:
            logging.info("Background task running")
            if anyio.current_time() - start_time > ERROR_AFTER_SECONDS:
                raise RuntimeError(f"Background task failed after {ERROR_AFTER_SECONDS}s")
            await anyio.sleep(0.1)
    
    async with anyio.create_task_group() as tg:
        tg.start_soon(worker)
        try:
            yield
        except GeneratorExit:
            # Catch GeneratorExit to prevent it from being part of the exception group
            raise
        finally:
            logging.info("Yielding control back to fixture")
            tg.cancel_scope.cancel()


@pytest.fixture
async def background_task():
    """Fixture that uses aclosing to properly handle the async generator."""
    async with aclosing(background_task_context()) as ctx:
        async with ctx:
            yield


@pytest.mark.anyio
async def test_background_fail(background_task):
    logging.info("hello")
    await anyio.sleep(2)  # Give background task time to run
    assert True