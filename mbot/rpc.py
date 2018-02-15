from threading import Thread

import gevent
import zerorpc
from gevent import Timeout
from pymongo import MongoClient
from gevent.event import AsyncResult


class RPCServer(Thread):
    def __init__(self, obj, *args, host='tcp://127.0.0.1', port=4242, **kwargs):
        super().__init__(*args, **kwargs)

        self.obj = obj
        self.host = host
        self.port = port
        self.server = None

        self.daemon = True

    def run(self):
        self.server = zerorpc.Server(self.obj)
        self.server.bind(f'{self.host}:{self.port}')
        self.server.run()


class RPC(object):
    def __init__(self, mbot):
        self.mbot = mbot
        self.db = MongoClient(mbot.config.mongo.host, mbot.config.mongo.port)

    def installed_plugins(self):
        return [plugin.__class__.__name__ for plugin in self.mbot.plugin_manager.plugins]

    def plugins_for_server(self, server_id):
        doc = self.db.bot_data.config.find_one({'server_id': server_id})

        if doc:
            return {plugin['name']: plugin['commands'] for plugin in doc['plugins']}

    def commands_for_plugin(self, plugin_name):
        commands = {}

        for cmd in self.mbot.plugin_manager.commands.values():
            command = cmd[2]

            if command.info['plugin'] == plugin_name:
                commands[command.info['name']] = {
                    'usage': command.info['usage'],
                    'description': command.info['desc'],
                    'regex': command._pattern.pattern
                }

        return commands

    def enable_commands(self, server_id, commands):
        result = AsyncResult()

        def task():
            success = []

            for command in commands:
                plugin = self.mbot.plugin_manager._plugin_for_cmd(command)

                # Skip Help plugin.
                if plugin == 'Help' or not plugin:
                    success.append(False)
                    continue

                doc = self.db.bot_data.config.find_one(
                    {'server_id': server_id, 'plugins': {'$elemMatch': {'name': plugin}}}
                )

                if doc:
                    ret = self.db.bot_data.config.update_one(
                        {'server_id': server_id, 'plugins': {'$elemMatch': {'name': plugin}}},
                        {'$addToSet': {'plugins.$.commands': command}}
                    )

                    success.append(bool(ret))
                    continue

                success.append(False)

            result.set(all(success))

        gevent.spawn(task)

        try:
            return result.get(timeout=30)
        except Timeout:
            return None

    def disable_commands(self, server_id, commands):
        result = AsyncResult()

        def task():
            success = []

            for command in commands:
                plugin = self.mbot.plugin_manager._plugin_for_cmd(command)

                # Skip Help plugin.
                if plugin == 'Help' or not plugin:
                    success.append(False)
                    continue

                doc = self.db.bot_data.config.find_one(
                    {'server_id': server_id, 'plugins': {'$elemMatch': {'name': plugin}}}
                )

                if doc:
                    ret = self.db.bot_data.config.update_one(
                        {'server_id': server_id, 'plugins': {'$elemMatch': {'name': plugin}}},
                        {'$pull': {'plugins.$.commands': command}}
                    )

                    success.append(bool(ret))
                    continue

                success.append(False)

            result.set(all(success))

        gevent.spawn(task)

        try:
            return result.get(timeout=30)
        except Timeout:
            return None

    def reload_plugins(self):
        async def task():
            await self.mbot.plugin_manager.reload_plugins()

        self.mbot.loop.create_task(task())
