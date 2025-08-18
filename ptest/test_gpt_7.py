import anyio
import pytest
import logging


ERROR_AFTER_SECONDS = 1  # Set this constant to control after how many seconds to raise the error

# conftest.py
import anyio
import pytest
import functools
import traceback

def capture_task_exceptions(fixture_fn):
    """
    Wrap an async‐generator fixture so that any exceptions in anyio TaskGroup
    children are logged immediately and then re-raised at teardown.
    """
    @pytest.fixture
    @functools.wraps(fixture_fn)
    async def wrapper(*args, **kwargs):
        # 1) patch create_task_group
        orig_ctg = anyio.create_task_group
        exceptions: list[BaseException] = []

        def patched_create_task_group(*tg_args, **tg_kwargs):
            # get the real context manager
            cm = orig_ctg(*tg_args, **tg_kwargs)

            class PatchedCM:
                def __init__(self):
                    self._cm = cm
                    self._tg = None

                async def __aenter__(self):
                    self._tg = await self._cm.__aenter__()
                    orig_start = self._tg.start_soon

                    def start_soon_wrapped(fn, *f_args, **f_kwargs):
                        async def run_and_capture():
                            try:
                                await fn(*f_args, **f_kwargs)
                            except BaseException as e:
                                # log right away
                                traceback.print_exc()
                                exceptions.append(e)
                                # re-raise so the TaskGroup cancels siblings
                                raise
                        return orig_start(run_and_capture)

                    self._tg.start_soon = start_soon_wrapped
                    return self._tg

                async def __aexit__(self, exc_type, exc, tb):
                    return await self._cm.__aexit__(exc_type, exc, tb)

            return PatchedCM()

        anyio.create_task_group = patched_create_task_group

        try:
            # 2) drive the async‐generator fixture
            agen = fixture_fn(*args, **kwargs)
            value = await agen.asend(None)   # run up to its first yield
            try:
                yield value               # hand control to the test
            finally:
                # finish the generator (teardown)
                try:
                    await agen.asend(None)
                except StopAsyncIteration:
                    pass

                # 3) if any child blew up, re-raise the first one now
                if exceptions:
                    raise exceptions[0]
        finally:
            # restore
            anyio.create_task_group = orig_ctg

    return wrapper


@capture_task_exceptions
@pytest.fixture
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
        tg.cancel_scope.cancel()  # Cancel the task group
        # Task group will be cancelled on fixture exit


@pytest.mark.anyio
async def test_background_fail(background_task):
    logging.info("hello")
    await anyio.sleep(2)  # Give background task time to run
    assert True