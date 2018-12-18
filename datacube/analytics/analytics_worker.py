"""Analytics Engine worker.
This worker will be cloned in the AE cluster.
Currently JRO service calls e.g. updates are handled by this worker.
If performance is not as responsive as requried, a new cluster for
JRO service calls will be created.
"""

from __future__ import absolute_import, print_function

from .analytics_engine2 import AnalyticsEngineV2
from .update_engine2 import UpdateEngineV2
from .base_job_monitor import BaseJobMonitor
from datacube.execution.execution_engine2 import ExecutionEngineV2
from datacube.engine_common.file_transfer import FileTransfer


class AnalyticsWorker():
    '''The analytics worker organises the message flows between
    workers. It can be subclassed to use specific RPC calls.'''

    def run_python_function_base(self, params_url):
        '''Process the function and data submitted by the user.'''
        analytics_engine = AnalyticsEngineV2('Analytics Engine', params_url)
        if not analytics_engine:
            raise RuntimeError('Analytics engine must be initialised by calling `initialise_engines`')
        jro_url, urls, decomposed = analytics_engine.analyse()

        subjob_tasks = []
        for url in urls:
            subjob_tasks.append(self.run_python_function_subjob(url))

        monitor_params = {
            'decomposed': decomposed,
            'subjob_tasks': subjob_tasks,
        }
        payload = {
            'params_url': 'URL:{}'.format(params_url),
            'job': monitor_params,
            'type': 'monitor_job'
        }

        # TODO: could we avoid creating a new file transfer here?
        file_transfer = FileTransfer(url=jro_url.replace('/result/', '/monitor/'))
        monitor_url = file_transfer.store_payload(payload)
        self.monitor_jobs(monitor_url)

        return jro_url

    def run_python_function_subjob(self, url):
        '''Process a subjob, created by the base job.'''
        execution_engine = ExecutionEngineV2('Execution Engine', url)
        if not execution_engine:
            raise RuntimeError('Execution engine must be initialised by calling `initialise_engines`')
        return execution_engine.execute()

    def monitor_jobs(self, monitor_url, kill_subjobs=None):
        '''Monitors the subjobs.

        An RPC-dependent implementation of the `kill_subjobs()` must
        be passed as a callback function, to allow to forcibly kill
        all subjobs.
        '''
        base_job_monitor = BaseJobMonitor('Base Job Monitor', monitor_url, kill_subjobs)
        base_job_monitor.monitor_completion()

    def get_update(self, action, item_id, paths=None, env=None):
        '''Return an update on a job or result.'''
        last_error = None
        for attempt in range(10):
            try:
                update_engine = UpdateEngineV2(paths, env)
                if not update_engine:
                    raise RuntimeError('Update engine must be initialised by calling `initialise_engines`')
                result = update_engine.execute(action, item_id)
                return result
            except TimeoutError as e:
                last_error = str(e)
                print("error - AnalyticsWorker.get_update()", str(type(e)), last_error)
                continue
            except Exception as e:
                last_error = str(e)
                print("error u - AnalyticsWorker.get_update()", str(type(e)), last_error)
                continue
        # Exceeded max retries
        raise RuntimeError('AnalyticsWorker.get_update', 'exceeded max retries', last_error)
