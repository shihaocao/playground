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
        
        # Helper to filter and collect real errors
        def collect_real_errors(exc):
            """Collect non-cancellation/cleanup errors"""
            ignored_types = (anyio.get_cancelled_exc_class(), GeneratorExit, StopAsyncIteration)
            
            if isinstance(exc, BaseExceptionGroup):
                for e in exc.exceptions:
                    if not isinstance(e, ignored_types):
                        background_errors.append(e)
            elif not isinstance(exc, ignored_types):
                background_errors.append(exc)
        
        # Create a task to run the fixture
        async def fixture_runner():
            nonlocal fixture_value, fixture_gen
            try:
                # Start the fixture generator
                fixture_gen = func(*args, **kwargs)
                # Get the yielded value
                fixture_value = await fixture_gen.asend(None)
                # Keep the fixture context alive
                await anyio.sleep_forever()
            except anyio.get_cancelled_exc_class():
                # Expected during cleanup
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
                
                # Shield the test from cancellation
                with anyio.CancelScope(shield=True):
                    try:
                        # Yield the fixture value to the test
                        yield fixture_value
                    finally:
                        logging.info("Cleaning up background task")
                        # Cancel all background tasks
                        tg.cancel_scope.cancel()
                        
        except BaseExceptionGroup as eg:
            collect_real_errors(eg)
        except Exception as e:
            collect_real_errors(e)
        
        # Close the fixture generator if it exists
        if fixture_gen is not None:
            try:
                await fixture_gen.aclose()
            except BaseExceptionGroup as eg:
                collect_real_errors(eg)
            except Exception as e:
                collect_real_errors(e)
        
        # Re-raise any real errors that occurred
        if background_errors:
            logging.error("Background task failed during test execution")
            raise background_errors[0]
    
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