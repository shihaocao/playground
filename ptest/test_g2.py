import anyio
import functools
import pytest
import logging
from async_generator import aclosing



def background_task_handler(func):
    @functools.wraps(func)
    async def wrapped(*args, **kwargs):
        yielded = anyio.Event()
        state = {"value": None}

        async def driver():
            agen = func(*args, **kwargs)  # your original async-gen fixture
            # Ensure *we* own closing/finalization
            async with aclosing(agen):
                state["value"] = await agen.asend(None)  # run to first yield
                yielded.set()
                await anyio.sleep_forever()             # keep context alive

        try:
            async with anyio.create_task_group() as tg:
                tg.start_soon(driver)
                await yielded.wait()
                try:
                    # no shielding → fast-fail: test is cancelled immediately if worker errors
                    yield state["value"]
                except anyio.get_cancelled_exc_class():
                    # swallow; TaskGroup __aexit__ will raise the real worker error
                    pass
                finally:
                    tg.cancel_scope.cancel()
        except BaseException:
            # surface the worker's original traceback
            raise

    return wrapped



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
    await anyio.sleep(10)  # Give background task time to fail
    assert True


# Test examples
@pytest.mark.anyio
async def test_background_success(background_task_success):
    logging.info("Test starting")
    await anyio.sleep(2)  # Give background task time to fail
    assert True