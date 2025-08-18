import anyio
import pytest
import logging

def pytest_configure(config):
    # root logger, INFO and up
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%H:%M:%S"
    )

@pytest.fixture(scope="session")
def anyio_backend():
    return 'trio'