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
        self.client = MongoClient(config.mongo.host, config.mongo.port)

        self.bot_data = self.client.bot_data

        self.config = self.bot_data.config
        self.cmd_history = self.bot_data.cmd_history
        self.stats = self.bot_data.stats

        self.plugin_data = self.client.plugin_data

        log.debug(f'connected to mongo instance at {config.mongo.host}:{config.mongo.port}')

    async def init_stats(self):
        # Initialise global stats document
        _doc = await self.stats.find_one({'scope': 'global'})

        if not _doc:
            await self.stats.insert_one({'scope': 'global'})
