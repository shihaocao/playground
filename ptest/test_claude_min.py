import anyio
import pytest
import logging
import functools
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Callable, Any


ERROR_AFTER_SECONDS = 1  # Set this constant to control after how many seconds to raise the error


def background_task_handler(func: Callable) -> Callable:
    """
    Decorator that converts a simple background worker into a robust fixture
    that properly handles exceptions and provides tracebacks.
    
    Usage:
        @pytest.fixture
        @background_task_handler
        async def my_background_task():
            # Your background logic here
            while True:
                await do_something()
    """
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        background_errors = []
        
        async def worker_wrapper():
            try:
                await func(*args, **kwargs)
            except Exception as e:
                logging.error(f"Background task failed: {e}", exc_info=True)
                background_errors.append(e)
                raise
        
        try:
            async with anyio.create_task_group() as tg:
                tg.start_soon(worker_wrapper)
                
                # Always shield the test from cancellation
                with anyio.CancelScope(shield=True):
                    try:
                        yield background_errors
                    finally:
                        logging.info("Cleaning up background task")
                        tg.cancel_scope.cancel()
                        
        except* Exception as eg:
            logging.error(f"Captured background task errors: {eg}")
            # Don't raise here, we want the original error with traceback
        
        # Re-raise any background errors after cleanup
        if background_errors:
            logging.error("Background task failed during test execution")
            raise background_errors[0]
    
    return wrapper


# ============= EXAMPLES =============

# Example 1: Using the decorator (simplest approach)
@pytest.fixture
@background_task_handler
async def example_background_task_decorator():
    """Example using the decorator approach"""
    async def background_task():
        start_time = anyio.current_time()
        while True:
            logging.info("Background task running")
            if anyio.current_time() - start_time > 1:
                raise RuntimeError("Background task failed after 1s")
            await anyio.sleep(0.1)
            
    async with anyio.create_task_group() as tg:
        tg.start_soon(background_task)
        logging.info("Background task started")
        yield "test"
        logging.info("Background task finished")


# Test example
@pytest.mark.anyio
async def test_background_fail(example_background_task_decorator):
    logging.info("Test starting")
    await anyio.sleep(5)  # This will complete even if background task fails

    assert True