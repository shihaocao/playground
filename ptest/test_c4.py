import anyio
import pytest
import logging
import functools
from contextlib import asynccontextmanager
from typing import Callable, AsyncGenerator


def background_task_handler(func: Callable) -> Callable:
    """
    Decorator that manages background task lifecycle and prevents hanging.
    
    Key insight: We need to handle GeneratorExit properly to avoid hanging
    during fixture teardown.
    """
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        fixture_gen = None
        
        try:
            fixture_gen = func(*args, **kwargs)
            fixture_value = await fixture_gen.asend(None)
            yield fixture_value
            
        except GeneratorExit:
            # Handle generator close during teardown
            if fixture_gen is not None:
                try:
                    await fixture_gen.athrow(GeneratorExit)
                except (GeneratorExit, StopAsyncIteration):
                    pass
                except Exception as e:
                    logging.error(f"Error during fixture teardown: {e}")
            raise
            
        finally:
            # Cleanup if generator wasn't closed via GeneratorExit
            if fixture_gen is not None:
                try:
                    await fixture_gen.aclose()
                except (GeneratorExit, StopAsyncIteration):
                    pass
                except Exception as e:
                    logging.error(f"Error during fixture cleanup: {e}")
    
    return wrapper


# Alternative approach - restructure the fixture to handle cleanup properly
@pytest.fixture
async def background_task_fail_v2():
    """
    Alternative fixture structure that handles cleanup better.
    """
    task_group = None
    
    async def worker():
        start_time = anyio.current_time()
        while True:
            logging.info("Background task running")
            if anyio.current_time() - start_time > 1:
                raise RuntimeError("Background task failed after 1s")
            await anyio.sleep(0.1)
    
    try:
        task_group = anyio.create_task_group()
        await task_group.__aenter__()
        task_group.start_soon(worker)
        
        yield  # Yield to test
        
    except BaseExceptionGroup as eg:
        # Re-raise the first real error
        for exc in eg.exceptions:
            if not isinstance(exc, (anyio.get_cancelled_exc_class(), GeneratorExit)):
                raise exc from exc
        raise
    
    finally:
        if task_group is not None:
            try:
                # Cancel and cleanup
                task_group.cancel_scope.cancel()
                await task_group.__aexit__(None, None, None)
            except Exception as e:
                logging.debug(f"Task group cleanup error: {e}")


# Or even simpler - just catch and handle the specific hanging case
@pytest.fixture  
async def background_task_fail_v3():
    """
    Simplest fix - just handle GeneratorExit to prevent hanging.
    """
    async def worker():
        start_time = anyio.current_time()
        while True:
            logging.info("Background task running")
            if anyio.current_time() - start_time > 1:
                raise RuntimeError("Background task failed after 1s")
            await anyio.sleep(0.1)

    try:
        async with anyio.create_task_group() as tg:
            tg.start_soon(worker)
            yield
    except GeneratorExit:
        # This prevents hanging during teardown
        logging.info("Generator closing, cancelling background tasks")
        # The context manager will handle cancellation
        raise
    except BaseExceptionGroup as eg:
        # Propagate non-cancellation errors
        for exc in eg.exceptions:
            if not isinstance(exc, anyio.get_cancelled_exc_class()):
                raise exc
        raise


@pytest.mark.anyio
async def test_background_fail_v2(background_task_fail_v2):
    logging.info("Test starting")
    await anyio.sleep(2)  # Should fail when background task raises after 1s
    assert True


@pytest.mark.anyio  
async def test_background_fail_v3(background_task_fail_v3):
    logging.info("Test starting")
    await anyio.sleep(2)  # Should fail when background task raises after 1s
    assert True