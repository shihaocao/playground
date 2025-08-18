import anyio
import pytest
import logging
import functools
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Callable, Any


ERROR_AFTER_SECONDS = 1  # Set this constant to control after how many seconds to raise the error



def background_task_handler(worker_func: Callable = None, *, shield_test: bool = True):
    """
    Decorator that converts a simple background worker into a robust fixture
    that properly handles exceptions and provides tracebacks.
    
    Args:
        worker_func: The async function to run in the background
        shield_test: If True, shields the test from cancellation when worker fails
    
    Usage:
        @pytest.fixture
        @background_task_handler
        async def my_background_task():
            # Your background logic here
            while True:
                await do_something()
                
        # Or with parameters:
        @pytest.fixture
        @background_task_handler(shield_test=False)
        async def my_background_task():
            ...
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            background_errors = []
            
            async def worker_wrapper():
                try:
                    # Call the original function
                    await func(*args, **kwargs)
                except Exception as e:
                    # Capture any exception with full traceback
                    logging.error(f"Background task failed: {e}", exc_info=True)
                    background_errors.append(e)
                    raise
            
            try:
                async with anyio.create_task_group() as tg:
                    tg.start_soon(worker_wrapper)
                    
                    if shield_test:
                        # Shield the test from cancellation
                        with anyio.CancelScope(shield=True):
                            try:
                                yield background_errors
                            finally:
                                logging.info("Cleaning up background task")
                                tg.cancel_scope.cancel()
                    else:
                        try:
                            yield background_errors
                        finally:
                            logging.info("Cleaning up background task")
                            tg.cancel_scope.cancel()
                            
            except* Exception as eg:
                # Handle exception groups from anyio
                for exc in eg.exceptions:
                    if exc not in background_errors:
                        background_errors.append(exc)
                logging.error(f"Captured background task errors: {eg}")
            
            # Re-raise any background errors after cleanup
            if background_errors:
                logging.error("Background task failed during test execution")
                # Re-raise the first error with its original traceback
                raise background_errors[0]
        
        return wrapper
    
    # Handle both @background_task_handler and @background_task_handler()
    if worker_func is None:
        return decorator
    else:
        return decorator(worker_func)


class BackgroundTaskManager:
    """
    Context manager for running background tasks with proper error handling.
    
    Usage:
        @pytest.fixture
        async def my_fixture():
            async def worker():
                # your background logic
                ...
            
            async with BackgroundTaskManager(worker) as manager:
                yield manager.errors
    """
    
    def __init__(self, worker_func: Callable, shield_test: bool = True):
        self.worker_func = worker_func
        self.shield_test = shield_test
        self.errors = []
        self._task_group = None
    
    async def __aenter__(self):
        self._task_group = anyio.create_task_group()
        await self._task_group.__aenter__()
        self._task_group.start_soon(self._worker_wrapper)
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.shield_test:
            with anyio.CancelScope(shield=True):
                self._task_group.cancel_scope.cancel()
        else:
            self._task_group.cancel_scope.cancel()
        
        try:
            await self._task_group.__aexit__(exc_type, exc_val, exc_tb)
        except* Exception as eg:
            for exc in eg.exceptions:
                if exc not in self.errors:
                    self.errors.append(exc)
            logging.error(f"Captured background task errors: {eg}")
        
        if self.errors:
            logging.error("Background task failed during test execution")
            raise self.errors[0]
        
        return False
    
    async def _worker_wrapper(self):
        try:
            await self.worker_func()
        except Exception as e:
            logging.error(f"Background task failed: {e}", exc_info=True)
            self.errors.append(e)
            raise


# Simple helper for the most common case
def with_background_task(shield_test: bool = True):
    """
    Simple decorator that runs the decorated function as a background task.
    
    Usage:
        @pytest.fixture
        @with_background_task()
        async def my_fixture():
            while True:
                # Your background logic
                await anyio.sleep(0.1)
    """
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            async with BackgroundTaskManager(
                lambda: func(*args, **kwargs), 
                shield_test=shield_test
            ) as manager:
                yield manager.errors
        return wrapper
    return decorator


# ============= EXAMPLES =============

# Example 1: Using the decorator (simplest approach)
@pytest.fixture
@background_task_handler
async def example_background_task_decorator():
    """Example using the decorator approach"""
    start_time = anyio.current_time()
    while True:
        logging.info("Background task running")
        if anyio.current_time() - start_time > 1:
            raise RuntimeError("Background task failed after 1s")
        await anyio.sleep(0.1)


# Example 2: Using the context manager (more control)
@pytest.fixture
async def example_background_task_manager():
    """Example using the context manager approach"""
    async def worker():
        start_time = anyio.current_time()
        while True:
            logging.info("Background task running")
            if anyio.current_time() - start_time > 1:
                raise RuntimeError("Background task failed after 1s")
            await anyio.sleep(0.1)
    
    async with BackgroundTaskManager(worker) as manager:
        yield manager.errors


# Example 3: Converting your original fixture with minimal changes
@pytest.fixture
@with_background_task()
async def background_task():
    """Your original worker logic with minimal refactoring"""
    start_time = anyio.current_time()
    while True:
        logging.info("Background task running")
        if anyio.current_time() - start_time > ERROR_AFTER_SECONDS:
            raise RuntimeError(f"Background task failed after {ERROR_AFTER_SECONDS}s")
        await anyio.sleep(0.1)


# Test example
@pytest.mark.anyio
async def test_background_fail(example_background_task_decorator):
    logging.info("Test starting")
    await anyio.sleep(2)  # This will complete even if background task fails
    
    # Optionally check for background errors during test
    if background_task:  # background_task is the errors list
        logging.warning(f"Background errors detected: {background_task}")
    
    assert True