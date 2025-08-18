import anyio
import pytest
import logging
import functools
from typing import Callable


def background_task_handler(func: Callable) -> Callable:
    """
    Simplified decorator that prevents hanging and preserves stack traces.
    
    Key insight: We don't need complex error collection - just let exceptions
    bubble up naturally and ensure proper cleanup happens.
    """
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        fixture_gen = None
        
        async def fixture_runner():
            nonlocal fixture_gen
            fixture_gen = func(*args, **kwargs)
            # Get the yielded value and return it
            return await fixture_gen.asend(None)
        
        try:
            async with anyio.create_task_group() as tg:
                # Start fixture in background - any errors will bubble up through task group
                fixture_value = await tg.start(lambda tg: fixture_runner())
                
                # Yield to test - if background task fails, task group will raise
                yield fixture_value
                
        finally:
            # Always cleanup the generator
            if fixture_gen is not None:
                try:
                    await fixture_gen.aclose()
                except Exception as e:
                    logging.error(f"Error during fixture cleanup: {e}")
                    # Don't re-raise cleanup errors - they mask the real issue
    
    return wrapper


# Even simpler alternative - let's question if we need the wrapper at all
def minimal_background_task_handler(func: Callable) -> Callable:
    """
    Minimal version - just ensure proper cleanup, let errors bubble naturally.
    """
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        fixture_gen = func(*args, **kwargs)
        try:
            fixture_value = await fixture_gen.asend(None)
            yield fixture_value
        finally:
            try:
                await fixture_gen.aclose()
            except Exception:
                pass  # Suppress cleanup errors
    
    return wrapper


# Test with the original fixtures to see if this works
@pytest.fixture
@minimal_background_task_handler
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
    await anyio.sleep(2)  # This should fail when background task raises
    assert True