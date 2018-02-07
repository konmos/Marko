import os
import sqlite3
import logging

import peewee as pe
from pymongo import MongoClient

log = logging.getLogger(__name__)

database_proxy = pe.Proxy()


class BaseModel(pe.Model):
    '''
    Base model for the sql based database. Plugins which need the sql database
    should all use this model.
    '''
    class Meta:
        database = database_proxy


class Database(object):
    '''
    Base class which manages the global database used by the bot.
    Plugins should not use this class, instead all plugins should
    access the database through the `db` attribute of the `mbot` class.
    '''
    def __init__(self, config):
        self.sqlite, self.mysql = False, False

        if config.db.type == 'sqlite':
            self.sqlite = True

            if not os.path.exists(config.db.database):
                _ = sqlite3.connect(config.db.database)
                _.close()

            self.db = pe.SqliteDatabase(
                config.db.database
            )

        elif config.db.type == 'mysql':
            self.mysql = True

            self.db = pe.MySQLDatabase(
                config.db.database,
                user=config.db.user,
                password=config.db.password,
                host=config.db.host
            )

        global database_proxy
        database_proxy.initialize(self.db)

        self.db.connect()

        log.debug(f'connected to {config.db.type} database {config.db.database}')


class Mongo(object):
    '''
    Similar concept to the `Database` class, but it manages the mongo
    database instance, rather than an sql database. The two options are provided
    to allow a choice for each use case. The mongodb, however, is what is used primarily.
    '''
    def __init__(self, config):
        self.client = MongoClient(config.mongo.host, config.mongo.port)

        self.bot_data = self.client.bot_data

        self.config = self.bot_data.config
        self.cmd_history = self.bot_data.cmd_history
        self.stats = self.bot_data.stats

        self.plugin_data = self.client.plugin_data

        # Create global stats document
        _doc = self.stats.find_one({'scope': 'global'})

        if not _doc:
            self.stats.insert_one({'scope': 'global'})

        log.debug(f'connected to mongo instance at {config.mongo.host}:{config.mongo.port}')
