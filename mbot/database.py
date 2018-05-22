import logging
from motor.motor_asyncio import AsyncIOMotorClient as MongoClient

log = logging.getLogger(__name__)


class Mongo(object):
    '''
    Base class which manages the global database used by the bot.
    Plugins should not use this class, instead all plugins should
    access the database through the `mongo` attribute of the `mbot` class.
    '''
    def __init__(self, config):
        self.client = MongoClient(
            config.mongo.host, config.mongo.port,
            username=config.mongo.username, password=config.mongo.password
        )

        self.bot_data = self.client.bot_data

        self.config = self.bot_data.config
        self.cmd_history = self.bot_data.cmd_history
        self.stats = self.bot_data.stats
        self.bot_guilds = self.bot_data.bot_guilds

        self.plugin_data = self.client.plugin_data

        log.debug(f'connected to mongo instance at {config.mongo.host}:{config.mongo.port}')
