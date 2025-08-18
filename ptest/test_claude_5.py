import anyio
import pytest
import logging
import functools
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Callable, Any
import inspect


ERROR_AFTER_SECONDS = 3  # Set this constant to control after how many seconds to raise the error


def background_task_handler(func: Callable) -> Callable:
    """
    Decorator that automatically manages background task lifecycle and error handling.
    
    The decorated fixture can simply yield to hand control to the test, and any
    background tasks started in the fixture will be automatically monitored.
    
    Usage:
        @pytest.fixture
        @background_task_handler
        async def my_background_task():
            async def worker():
                # Your background work here
                while True:
                    await do_something()
            
            async with anyio.create_task_group() as tg:
                tg.start_soon(worker)
                yield  # Just yield, decorator handles the rest
    """
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        background_errors = []
        fixture_value = None
        fixture_gen = None
        
        # Create a nursery to monitor background tasks
        async def fixture_runner():
            nonlocal fixture_value, fixture_gen
            try:
                if inspect.isasyncgenfunction(func):
                    # Handle async generator (pytest fixture with yield)
                    fixture_gen = func(*args, **kwargs)
                    # Get the yielded value from the fixture
                    fixture_value = await fixture_gen.asend(None)
                    # The fixture has started its background work and yielded
                    # We keep this task alive to maintain the fixture context
                    await anyio.sleep_forever()
                else:
                    # Handle regular async function
                    result = await func(*args, **kwargs)
                    fixture_value = result
                    await anyio.sleep_forever()
            except anyio.get_cancelled_exc_class():
                # Expected when we cancel during cleanup
                logging.debug("Fixture runner cancelled (expected during cleanup)")
                raise
            except Exception as e:
                logging.error(f"Background fixture failed: {e}", exc_info=True)
                background_errors.append(e)
                raise
        
        try:
            async with anyio.create_task_group() as tg:
                tg.start_soon(fixture_runner)
                
                # Give the fixture a moment to start and yield
                await anyio.sleep(0.01)
                
                # Always shield the test from cancellation
                with anyio.CancelScope(shield=True):
                    try:
                        # Yield the fixture value (None if fixture just yields without value)
                        yield fixture_value
                    finally:
                        logging.info("Cleaning up background task")
                        
                        # Cancel the task group to stop background work
                        tg.cancel_scope.cancel()
                        
        except* Exception as eg:
            # Collect any background errors that occurred
            for exc in eg.exceptions:
                if not isinstance(exc, anyio.get_cancelled_exc_class()):
                    logging.error(f"Background task error: {exc}", exc_info=True)
                    if exc not in background_errors:
                        background_errors.append(exc)
        
        # Properly close the fixture generator if it exists
        if fixture_gen is not None:
            try:
                await fixture_gen.aclose()
            except* Exception as cleanup_eg:
                # Handle exception groups from generator cleanup
                for exc in cleanup_eg.exceptions:
                    if not isinstance(exc, (anyio.get_cancelled_exc_class(), GeneratorExit, StopAsyncIteration)):
                        logging.error(f"Error during fixture cleanup: {exc}", exc_info=True)
                        background_errors.append(exc)
        
        # Re-raise any background errors after cleanup
        if background_errors:
            logging.error("Background task failed during test execution")
            raise background_errors[0]
    
    return wrapper


# Example usage - simple and clean
@pytest.fixture
@background_task_handler
async def background_task():
    async def worker():
        start_time = anyio.current_time()
        while True:
            logging.info("Background task running")
            if anyio.current_time() - start_time > ERROR_AFTER_SECONDS:
                raise RuntimeError(f"Background task failed after {ERROR_AFTER_SECONDS}s")
            await anyio.sleep(0.1)

    async with anyio.create_task_group() as tg:
        tg.start_soon(worker)
        yield  # Yield control to the test while the background task runs
        logging.info("Yielding control back to fixture")
        # The decorator will handle cancellation and error propagation


# Test examples
@pytest.mark.anyio
async def test_background_fail(background_task):
    logging.info("Test starting")
    await anyio.sleep(2)  # Give background task time to fail
    assert True