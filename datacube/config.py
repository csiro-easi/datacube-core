# coding=utf-8
"""
User configuration.
"""

import os

ENVIRONMENT_VARNAME = 'DATACUBE_CONFIG_PATH'
#: Config locations in order. Properties found in latter locations override
#: earlier ones.
#:
#: - `/etc/datacube.conf`
#: - file at `$DATACUBE_CONFIG_PATH` environment variable
#: - `~/.datacube.conf`
#: - `datacube.conf`
DEFAULT_CONF_PATHS = (
    '/etc/datacube.conf',
    os.environ.get(ENVIRONMENT_VARNAME),
    os.path.expanduser("~/.datacube.conf"),
    'datacube.conf'
)

DEFAULT_ENV = 'default'

# Default configuration options.
_DEFAULT_CONF = u"""
[DEFAULT]
# Blank implies localhost
db_hostname:
db_database: datacube
index_driver: default
# If a connection is unused for this length of time, expect it to be invalidated.
db_connection_timeout: 60

redis.host: 127.0.0.1
redis.port: 6379
redis.db: 0
redis.ssl: False

redis_celery.host: 127.0.0.1
redis_celery.port: 6379
redis_celery.db: 1
redis_celery.ssl: False

execution_engine.user_bucket: eetest2-user
execution_engine.result_bucket: eetest2-system
execution_engine.use_s3: False
execution_engine.rpc: thread

[user]
# Which environment to use when none is specified explicitly.
#   note: will fail if default_environment points to non-existent section
# default_environment: datacube
"""

#: Used in place of None as a default, when None is a valid but not default parameter to a function
_UNSET = object()


def read_config(default_text=None):
    import configparser
    config = configparser.ConfigParser()
    if default_text:
        config.read_string(default_text)
    return config


class LocalConfig(object):
    """
    System configuration for the user.

    This loads from a set of possible configuration files which define the available environments.
    An environment contains connection details for a Data Cube Index, which provides access to
    available data.

    """

    def __init__(self, config, files_loaded=None, env=None):
        """
        Datacube environment resolution precedence is:
          1. Supplied as a function argument `env`
          2. DATACUBE_ENVIRONMENT environment variable
          3. user.default_environment option in the config
          4. 'default' or 'datacube' whichever is present

        If environment is supplied by any of the first 3 methods is not present
        in the config, then throw an exception.
        """
        self._config = config  # type: configparser.ConfigParser
        self.files_loaded = []
        if files_loaded:
            self.files_loaded = files_loaded  # type: list[str]

        if env is None:
            env = os.environ.get('DATACUBE_ENVIRONMENT',
                                 (config.get('user', 'default_environment')
                                  if config.has_option('user', 'default_environment') else None))

        # If the user specifies a particular env, we either want to use it or Fail
        if env:
            if config.has_section(env):
                self._env = env
                # All is good
                return
            else:
                raise ValueError('No config section found for environment %r' % (env,))
        else:
            # If an env hasn't been specifically selected, we can fall back defaults
            fallbacks = [DEFAULT_ENV, 'datacube']
            for fallback_env in fallbacks:
                if config.has_section(fallback_env):
                    self._env = fallback_env
                    return
            raise ValueError('No ODC environment, checked configurations for %s' % fallbacks)

    @classmethod
    def find(cls, paths=DEFAULT_CONF_PATHS, env=None):
        """
        Find config from possible filesystem locations.

        'env' is which environment to use from the config: it corresponds to the name of a
        config section

        :type paths: str|list[str]
        :type env: str
        :rtype: LocalConfig
        """
        if isinstance(paths, str) or hasattr(paths, '__fspath__'):  # Use os.PathLike in 3.6+
            paths = [paths]
        config = read_config(_DEFAULT_CONF)
        files_loaded = config.read(str(p) for p in paths if p)

        return LocalConfig(
            config,
            files_loaded=files_loaded,
            env=env,
        )

    @property
    def datacube_config(self):
        return {
            'db_hostname': self.db_hostname,
            'db_database': self.db_database,
            'db_username': self.db_username,
            'db_password': self.db_password,
            'db_port': self.db_port,
            'db_connection_timeout': self.db_connection_timeout,
            'default_driver': self.default_driver
        }

    @property
    def redis_config(self):
        return {
            'host': self.get('redis.host', None),
            'port': int(self.get('redis.port', None)),
            'db': int(self.get('redis.db', None)),
            'password': self.get('redis.password', None),
            'ssl': self.get('redis.ssl') == 'True'
        }

    @property
    def redis_celery_config(self):
        host = self.get('redis_celery.host', None)
        port = int(self.get('redis_celery.port', None))
        db = int(self.get('redis_celery.db', None))
        password = self.get('redis_celery.password', None)
        ssl = self.get('redis_celery.ssl') == 'True'
        url = 'redis://{}{}:{}/{}'.format(
            ':{}@'.format(password) if password else '',
            host, port, db)
        return {
            'host': host,
            'port': port,
            'db': db,
            'password': password,
            'url': url,
            'ssl': ssl
        }

    @property
    def execution_engine_config(self):
        return {
            'user_bucket': self.get('execution_engine.user_bucket'),
            'result_bucket': self.get('execution_engine.result_bucket'),
            'use_s3': self.get('execution_engine.use_s3') == 'True',
            'rpc': self.get('execution_engine.rpc')
        }

    @property
    def db_password(self):
        return self.get('db_password')

    def get(self, item, fallback=_UNSET):
        if fallback == _UNSET:
            return self._config.get(self._env, item)
        else:
            if self._config.has_option(self._env, item):
                # TODO: simplify when dropping python 2 support
                return self._config.get(self._env, item)
            else:
                return fallback

    def __getitem__(self, item):
        return self.get(item, fallback=None)

    def __str__(self):
        return "LocalConfig<loaded_from={}, environment={!r}, config={}>".format(
            self.files_loaded or 'defaults',
            self._env,
            dict(self._config[self._env]),
        )

    def __repr__(self):
        return str(self)


OPTIONS = {'reproject_threads': 4}


#: pylint: disable=invalid-name
class set_options(object):
    """Set global state within a controlled context

    Currently, the only supported options are:
    * reproject_threads: The number of threads to use when reprojecting

    You can use ``set_options`` either as a context manager::

        with datacube.set_options(reproject_threads=16):
            ...

    Or to set global options::

        datacube.set_options(reproject_threads=16)
    """

    def __init__(self, **kwargs):
        self.old = OPTIONS.copy()
        OPTIONS.update(kwargs)

    def __enter__(self):
        return

    def __exit__(self, exc_type, value, traceback):
        OPTIONS.clear()
        OPTIONS.update(self.old)
