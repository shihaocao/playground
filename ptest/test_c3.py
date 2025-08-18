import anyio
import pytest
import logging
import functools
from typing import Callable


def background_task_handler(func: Callable) -> Callable:
    """
    Decorator that manages background task lifecycle and error propagation.
    
    The key insight: We need to run the fixture and test in the same task group
    so that background task failures are immediately propagated to the test.
    """
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        fixture_gen = None
        fixture_value = None
        
        async def fixture_setup():
            nonlocal fixture_gen, fixture_value
            fixture_gen = func(*args, **kwargs)
            fixture_value = await fixture_gen.asend(None)
        
        try:
            # Run everything in the same task group so errors propagate immediately
            async with anyio.create_task_group() as tg:
                # Start the fixture setup
                await fixture_setup()
                
                # Now yield to the test - if background tasks fail, 
                # the task group will propagate the exception immediately
                yield fixture_value
                
        except BaseExceptionGroup as eg:
            # Re-raise the first non-cancellation error with proper stack trace
            for exc in eg.exceptions:
                if not isinstance(exc, anyio.get_cancelled_exc_class()):
                    raise exc from exc.__cause__
            raise  # If only cancellation errors, re-raise the group
            
        finally:
            # Always cleanup the fixture generator
            if fixture_gen is not None:
                try:
                    await fixture_gen.aclose()
                except Exception as cleanup_error:
                    logging.debug(f"Fixture cleanup error (suppressed): {cleanup_error}")
    
    return wrapper


# Alternative approach - monitor background tasks explicitly
def background_task_handler_v2(func: Callable) -> Callable:
    """
    Alternative: Explicitly monitor background task health during test execution.
    """
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        fixture_gen = None
        background_failed = False
        background_error = None
        
        async def fixture_runner():
            nonlocal fixture_gen, background_failed, background_error
            try:
                fixture_gen = func(*args, **kwargs)
                return await fixture_gen.asend(None)
            except Exception as e:
                background_failed = True
                background_error = e
                raise
        
        async def error_monitor():
            """Monitor for background failures and propagate them"""
            while not background_failed:
                await anyio.sleep(0.01)  # Check frequently
            if background_error:
                raise background_error
        
        try:
            async with anyio.create_task_group() as tg:
                # Start fixture
                fixture_value = await fixture_runner()
                
                # Start error monitor
                tg.start_soon(error_monitor)
                
                # Yield to test
                yield fixture_value
                
        finally:
            if fixture_gen is not None:
                try:
                    await fixture_gen.aclose()
                except Exception:
                    pass
    
    return wrapper


# Test the approach
@pytest.fixture
@background_task_handler
async def background_task_fail():
    async def worker():
        start_time = anyio.current_time()
        while True:
            logging.info("Background task running")
            if anyio.current_time() - start_time > 1:
                raise RuntimeError("Background task failed after 1s")
            await anyio.sleep(0.1)

    async with anyio.create_task_group() as tg:
        tg.start_soon(worker)
        yield
        logging.info("Fixture cleanup")


@pytest.mark.anyio
async def test_background_fail(background_task_fail):
    logging.info("Test starting")
    await anyio.sleep(2)  # Should fail when background task raises after 1s
    assert True