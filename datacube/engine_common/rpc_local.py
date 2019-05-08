import logging
from concurrent.futures import ThreadPoolExecutor

from datacube.analytics.analytics_worker import AnalyticsWorker


class RPCThreadPool():
    """
    Implementation of a Threadpool RPC for testing.
    """
    def __init__(self, config):
        self.logger = logging.getLogger(self.__class__.__name__)
        self._config = config
        self.pool = ThreadPoolExecutor(3)

    def _run_python_function_base(self, url):
        def work(context):
            url = context
            worker = AnalyticsWorker()
            return worker.run_python_function_base(url)
        return self.pool.submit(work, url).result()

    def _get_update(self, action, item_id, paths=None, env=None):
        def work(context):
            action, item_id, paths, env = context
            worker = AnalyticsWorker()
            return worker.get_update(action, item_id, paths, env)
        return self.pool.submit(work, (action, item_id, paths, env)).result()

    # pylint: disable=protected-access
    def __repr__(self):
        '''Return some information about the currently active workers.'''
        return '{} active workers: {}'.format(self.pool._work_queue.qsize(), [])


class RPCSerial():
    """
    Implementation of a Serial/Direct-Call RPC for testing.
    """
    def __init__(self, config):
        self.logger = logging.getLogger(self.__class__.__name__)
        self._config = config
        self.active = 0

    def _run_python_function_base(self, url):
        self.active += 1
        worker = AnalyticsWorker()
        result = worker.run_python_function_base(url)
        self.active -= 1
        return result

    def _get_update(self, action, item_id, paths=None, env=None):
        self.active += 1
        worker = AnalyticsWorker()
        result = worker.get_update(action, item_id, paths, env)
        self.active -= 1
        return result

    def __repr__(self):
        '''Return some information about the currently active workers.'''
        return '{} active workers: {}'.format(self.active, [])


def make_rpc_serial(dc_config):
    '''Return a new instance of Test RPC.'''
    return RPCSerial(dc_config)


def make_rpc_thread(dc_config):
    '''Return a new instance of Test RPC.'''
    return RPCThreadPool(dc_config)
