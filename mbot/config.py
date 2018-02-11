import sys
import logging
from collections import namedtuple

import yaml

log = logging.getLogger(__name__)


class Config(object):
    '''
    Simple config wrapper to allow easier access to the config values,
    instead of having to manually read the yaml config every time.
    '''
    _Mbot = namedtuple('Mbot', ('key', 'cmd_prefix'))
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

        self.mongo = self._Mongo(
            self.yml['mongo']['host'],
            self.yml['mongo']['port']
        )

        self.superusers = [str(su) for su in self.yml['superusers']]
        self.plugin_data = self.yml.get('plugin_data', {})

        log.debug(f'loaded config from {self._path}')
