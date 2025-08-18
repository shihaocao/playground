# pip install async-generator
import anyio, functools
from async_generator import aclosing

# background_fixture.py
import anyio
import inspect

def background_fixture(_fn=None, *, fastfail: bool = False):
    """
    Decorate a plain async function `fn(tg) -> value` into a pytest fixture.
    The function receives a TaskGroup to start workers. No async-generator in user code.

    Works as either:
      @background_fixture
      async def myfx(tg): ...

      @background_fixture(fastfail=True)
      async def myfx(tg): ...
    """
    def deco(fn):
        async def _fixture():
            async with anyio.create_task_group() as tg:
                value = await fn(tg)  # user starts workers: tg.start_soon(worker)
                try:
                    if fastfail:
                        try:
                            # No shielding: background error cancels the test now
                            yield value
                        except anyio.get_cancelled_exc_class():
                            # Let TaskGroup __aexit__ surface the real worker error
                            pass
                    else:
                        # Shield: run test fully; raise worker error at teardown
                        with anyio.CancelScope(shield=True):
                            yield value
                finally:
                    tg.cancel_scope.cancel()

        # Hide the original signature so pytest doesn't look for a "tg" fixture
        _fixture.__name__ = getattr(fn, "__name__", "_fixture")
        try:
            _fixture.__signature__ = inspect.Signature()
        except Exception:
            pass
        return _fixture

    return deco if _fn is None else deco(_fn)


import pytest, anyio, logging
@pytest.fixture
@background_fixture(fastfail=True)
async def background_task_fail(tg):
    async def worker():
        start = anyio.current_time()
        while True:
            logging.info("Background task running (fastfail)")
            if anyio.current_time() - start > 1:
                raise RuntimeError("boom (fastfail)")
            await anyio.sleep(0.1)
    tg.start_soon(worker)
    return None  # value yielded to the test

# Deferred-fail: test runs full duration, error raised at teardown
@pytest.fixture
@background_fixture(fastfail=False)
async def background_task_deferred(tg):
    async def worker():
        start = anyio.current_time()
        while True:
            logging.info("Background task running (deferred)")
            if anyio.current_time() - start > 1:
                raise RuntimeError("boom (deferred)")
            await anyio.sleep(0.1)
    tg.start_soon(worker)
    return None


@pytest.mark.anyio
async def test_fastfail(background_task_fail):
    logging.info("Test starting (fastfail)")
    # This should be interrupted around t=1s with the RuntimeError
    await anyio.sleep(5)
    assert False, "We should never get here in fastfail mode"


@pytest.mark.anyio
async def test_deferred(background_task_deferred):
    logging.info("Test starting (deferred)")
    # This should run ~5s, then fail *after* this sleep completes
    await anyio.sleep(5)
    assert True