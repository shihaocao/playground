import anyio
import pytest
import logging
import functools
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Callable, Any
import inspect


ERROR_AFTER_SECONDS = 1  # Set this constant to control after how many seconds to raise the error


def background_task_handler(func: Callable) -> Callable:
    """
    Decorator that converts a simple background worker into a robust fixture
    that properly handles exceptions and provides tracebacks.
    
    Works with both async generators (fixtures with yield) and regular async functions.
    
    Usage:
        @pytest.fixture
        @background_task_handler
        async def my_background_task():
            # Setup code here
            async with some_context():
                yield "fixture_value"  # This works!
            # Cleanup code here
    """
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        background_errors = []
        fixture_value = None
        fixture_gen = None
        
        async def worker_wrapper():
            nonlocal fixture_value, fixture_gen
            try:
                if inspect.isasyncgenfunction(func):
                    # Handle async generator (pytest fixture with yield)
                    fixture_gen = func(*args, **kwargs)
                    # Get the yielded value from the fixture
                    fixture_value = await fixture_gen.asend(None)
                    # Keep the fixture alive by waiting indefinitely
                    await anyio.sleep_forever()
                else:
                    # Handle regular async function
                    result = await func(*args, **kwargs)
                    fixture_value = result
            except GeneratorExit:
                # This is expected when we close the generator, don't treat as error
                logging.debug("Generator exit received (expected during cleanup)")
                raise
            except Exception as e:
                logging.error(f"Background task failed: {e}", exc_info=True)
                background_errors.append(e)
                raise
        
        try:
            async with anyio.create_task_group() as tg:
                tg.start_soon(worker_wrapper)
                
                # Give the worker a moment to start and get the fixture value
                await anyio.sleep(0.01)
                
                # Always shield the test from cancellation
                with anyio.CancelScope(shield=True):
                    try:
                        # Yield the fixture value (or errors list if no fixture value)
                        yield fixture_value if fixture_value is not None else background_errors
                    finally:
                        logging.info("Cleaning up background task")
                        
                        # Cancel the task group first to stop the worker
                        tg.cancel_scope.cancel()
                        
        except* GeneratorExit:
            # Expected when closing generators, don't log as error
            logging.debug("Generator cleanup completed")
        except* Exception as eg:
            # Only log actual unexpected errors
            for exc in eg.exceptions:
                if not isinstance(exc, GeneratorExit):
                    logging.error(f"Unexpected background task error: {exc}", exc_info=True)
                    if exc not in background_errors:
                        background_errors.append(exc)
        
        # Properly close the fixture generator if it exists
        if fixture_gen is not None:
            try:
                await fixture_gen.aclose()
            except GeneratorExit:
                # Expected when closing generator
                pass
            except Exception as cleanup_error:
                logging.error(f"Error during fixture cleanup: {cleanup_error}", exc_info=True)
                background_errors.append(cleanup_error)
        
        # Re-raise any background errors after cleanup
        if background_errors:
            logging.error("Background task failed during test execution")
            raise background_errors[0]
    
    return wrapper


@pytest.fixture(scope="session")
@background_task_handler
async def session_example_fixture():
    async with anyio.create_task_group() as tg:
        # Simulate some setup work
        await anyio.sleep(0.1)
        logging.info("Yielding session_example_fixture")
        yield "example_fixture_value"
        logging.info("Post yield in session_example_fixture")
        # Simulate cleanup work
        logging.info("Cleaning up session_example_fixture")
        await anyio.sleep(0.1)

# Example 1: Existing fixture style with yield (backwards compatible)
@pytest.fixture
@background_task_handler
async def example_background_task_decorator(session_example_fixture):
    """Example using the decorator approach with yield"""
    background_errors = []
    
    async def background_task():
        try:
            start_time = anyio.current_time()
            while True:
                logging.info("Background task running")
                if anyio.current_time() - start_time > ERROR_AFTER_SECONDS:
                    raise RuntimeError(f"Background task failed after {ERROR_AFTER_SECONDS}s")
                await anyio.sleep(0.1)
        except Exception as e:
            logging.error(f"Inner background task failed: {e}", exc_info=True)
            background_errors.append(e)
            raise
            
    async with anyio.create_task_group() as tg:
        tg.start_soon(background_task)
        logging.info("Background task started")
        
        yield "test_fixture_value"  # This is what gets passed to the test


# Test examples
@pytest.mark.anyio
async def test_background_fail(example_background_task_decorator):
    logging.info(f"Test starting with fixture value: {example_background_task_decorator}")
    await anyio.sleep(2)  # This will complete even if background task fails