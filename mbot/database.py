import os
import sqlite3

import peewee as pe
from pymongo import MongoClient


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


class Mongo(object):
    '''
    Similar concept to the `Database` class, but it manages the mongo
    database instance, rather than an sql database. Currently the mongo database
    is used for per server settings and server statistics.
    '''
    def __init__(self, config):
        self.client = MongoClient(config.mongo.host, config.mongo.port)

        self._config_db = self.client.config
        self.config = self._config_db.collection

        self._stats_db = self.client.stats
        self.stats = self._stats_db.collection
