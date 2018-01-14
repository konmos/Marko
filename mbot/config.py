import sys
import logging
from collections import namedtuple

import yaml

log = logging.getLogger(__name__)


class Config(object):
    '''
    Simple config wrapper to allow easier access to the config values,
    instead of having to manuall read the yaml config every time.
    '''
    _Mbot = namedtuple('Mbot', ('key', 'cmd_prefix'))
    _Database = namedtuple('Database', ('type', 'database', 'user', 'password', 'host'))
    _Mongo = namedtuple('Mongo', ('host', 'port'))

    def __init__(self, pth):
        self._path = pth

        try:
            with open(self._path) as fd:
                self.yml = yaml.load(fd)
        except (IOError, WindowsError):
            sys.exit(0)

        self.mbot = self._Mbot(
            self.yml['mbot']['key'],
            self.yml['mbot']['cmd_prefix']
        )

        self.db = self._Database(
            self.yml['db']['type'],
            self.yml['db']['database'],
            self.yml['db']['user'],
            self.yml['db']['password'],
            self.yml['db']['host']
        )

        self.mongo = self._Mongo(
            self.yml['mongo']['host'],
            self.yml['mongo']['port']
        )

        self.superusers = [str(su) for su in self.yml['superusers']]

        self.plugins = self.yml.get('plugins', {})

        log.debug(f'loaded config from {self._path}')
