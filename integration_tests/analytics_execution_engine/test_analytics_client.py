'''Unit tests for the analytics client.'''

import logging
import pytest
from datacube.engine_common.rpc_celery import celery_app, app
from datacube.analytics.analytics_client import AnalyticsClient
from datacube.analytics.job_result import Job, Results


# Skip all tests if redis cannot be imported
redis = pytest.importorskip('redis')


@pytest.mark.usefixtures('default_metadata_type')
@pytest.mark.parametrize('datacube_env_name', ('datacube', 's3aio_env', ), indirect=True)
def test_invalid_item_id(local_config):
    '''Ensure invalid input raises exceptions.'''
    client = AnalyticsClient(local_config)
    print(local_config._env)
    # Invalid result ID
    with pytest.raises(ValueError):
        client.get_result('Invalid', paths=local_config.files_loaded, env=local_config._env)

    # Invalid status for Job
    job = Job(None, {'id': 'Invalid', 'request_id': 'Invalid'})
    with pytest.raises(ValueError):
        client.get_status(job, paths=local_config.files_loaded, env=local_config._env)

    # Invalid status for Results
    results = Results(None, {'id': 'Invalid', 'request_id': 'Invalid', 'results': {}})
    with pytest.raises(ValueError):
        client.get_status(results, paths=local_config.files_loaded, env=local_config._env)

    # Invalid status for unknown item type
    with pytest.raises(ValueError):
        client.get_status(None, paths=local_config.files_loaded, env=local_config._env)


@pytest.mark.usefixtures('default_metadata_type')
@pytest.mark.parametrize('datacube_env_name', ('datacube', 's3aio_env', ), indirect=True)
def test_inactive_workers(local_config):
    '''Test client with no celery workers.'''
    client = AnalyticsClient(local_config)
    assert client.__str__() == 'Analytics client: 0 active workers: []'
