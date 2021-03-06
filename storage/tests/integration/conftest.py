import os

import pytest


@pytest.fixture(scope='module')
def bucket_name() -> str:
    return 'dialpad-oss-public-test'


@pytest.fixture(scope='module')
def creds() -> str:
    # TODO: bundle public creds into this repo
    return os.environ['GOOGLE_APPLICATION_CREDENTIALS']
