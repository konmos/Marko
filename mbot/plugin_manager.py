import sys
import logging
import importlib.util
from collections import defaultdict

from discord import User
from pymongo.errors import PyMongoError

from .plugins import plugins
from .plugin_registry import PluginRegistry

log = logging.getLogger(__name__)


class PluginManager(object):
    def __init__(self, mbot):
        self.mbot = mbot
        self.plugins = []  # List of global plugins.

        # Global store of commands. This should probably not be used directly.
        # Commands should be accessed either via the plugin or (better)
        # using the `commands_for_server` method.
        self.commands = {}

    @staticmethod
    def discover_plugins():
        for plugin in plugins():
            spec = importlib.util.find_spec(f'mbot.plugins.{plugin}')

            if spec is not None:
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                sys.modules[plugin] = module

        return PluginRegistry.plugins

    def load_plugins(self):
        '''Load all discovered plugins. This should always be the first method called.'''
        log.debug('loading plugins')

        for plugin in self.discover_plugins():
            p = plugin(self.mbot)
            self.plugins.append(p)

            log.debug(f'loaded {p.__class__.__name__} plugin')

    def load_commands(self):
        '''Load commands for all loaded plugins.'''
        log.debug('loading commands')

        for plugin in self.plugins:
            for command in plugin.commands:
                self.commands[command.info['name']] = (command.info['desc'], command.info['usage'], command)

            log.debug(f'loaded commands for {plugin.__class__.__name__} plugin')

    async def reload_plugins(self):
        '''
        Reload all plugins and commands dynamically on a live system.
        Returns dict of all plugins and commands that were either deleted or created.
        '''
        log.debug('attempting to reload plugins')

        ret = defaultdict(list)

        old_plugins = [plugin.__class__.__name__ for plugin in self.plugins]
        old_commands = list(self.commands.keys())

        # First, let's get rid of any existing plugins and commands
        self.plugins = []
        self.commands = {}

        for plugin in plugins():
            try:
                del sys.modules[plugin]
            except KeyError:
                pass

        del PluginRegistry.plugins[:]

        log.debug('cleared all plugins')

        # Reload all plugins and commands
        self.load_plugins()
        self.load_commands()

        # Now let's take care of server specific settings...
        new_plugins = [plugin.__class__.__name__ for plugin in self.plugins]
        new_commands = list(self.commands.keys())

        # We must also handle plugin creations and deletions.
        diff_p = set(old_plugins) ^ set(new_plugins)

        for plugin in diff_p:
            # Plugin was created.
            if plugin not in old_plugins:
                ret['new_plugins'].append(plugin)
            # Plugin was deleted.
            elif plugin not in new_plugins:
                ret['deleted_plugins'].append(plugin)

        # Now, handle command creations / deletions.
        diff_c = set(old_commands) ^ set(new_commands)

        for cmd in diff_c:
            # Command was created.
            if cmd not in old_commands:
                ret['new_commands'].append(cmd)
            # Command was deleted.
            elif cmd not in new_commands:
                ret['deleted_commands'].append(cmd)

        log.debug('done reloading plugins')
        return ret

    async def plugins_for_server(self, server_id):
        log.debug(f'fetching plugins for server {server_id}')

        ret = {}

        for plugin in self.plugins:
            doc = await self.mbot.mongo.config.find_one(
                {'server_id': server_id, 'plugins': {'$elemMatch': {'name': plugin.__class__.__name__}}}
            )

            if doc is not None:
                ret[plugin.__class__.__name__] = plugin

        return ret

    async def commands_for_server(self, server_id):
        log.debug(f'fetching commands for server {server_id}')

        ret = {}

        for plugin in self.plugins:
            doc = await self.mbot.mongo.config.find_one(
                {'server_id': server_id, 'plugins': {'$elemMatch': {'name': plugin.__class__.__name__}}}
            )

            if doc is not None:
                commands = []

                for p in doc['plugins']:
                    commands.extend(p['commands'])

                for command in plugin.commands:
                    if command.info['name'] in commands:
                        ret[command.info['name']] = command

        return ret

    async def disable_plugin(self, server_id, plugin):
        log.debug(f'disabling {plugin} plugin for server {server_id}')

        # Skip Core plugin.
        if plugin == 'Core':
            return False

        if plugin in [p.__class__.__name__ for p in self.plugins]:
            try:
                ret = await self.mbot.mongo.config.bot_data.config.update_one(
                    {'server_id': server_id},
                    {'$pull': {'plugins': {'name': plugin}}}
                )

                return ret.modified_count > 0
            except PyMongoError:
                return False

    async def global_disable_plugins(self, plugins_list):
        return await self.mbot.mongo.config.update_many(
            {},
            {'$pull': {'plugins': {'name': {'$in': plugins_list}}}}
        )

    async def enable_plugin(self, server_id, plugin):
        log.debug(f'enabling {plugin} plugin for server {server_id}')

        # Skip Core plugin.
        if plugin == 'Core':
            return False

        if plugin in [p.__class__.__name__ for p in self.plugins]:
            try:
                ret = await self.mbot.mongo.config.update_one(
                    {'server_id': server_id, 'plugins.name': {'$ne': plugin}},
                    {'$push': {'plugins': {'name': plugin, 'commands': []}}}
                )

                return ret.modified_count > 0
            except PyMongoError:
                return False

    async def global_enable_plugins(self, plugins_list):
        filtered = [i for i in filter((lambda x: x in [p.__class__.__name__ for p in self.plugins]), plugins_list)]

        if filtered:
            bulk = self.mbot.mongo.config.initialize_unordered_bulk_op()

            for plugin in filtered:
                bulk.find({'plugins.name': {'$ne': plugin}}).update(
                    {'$push': {'plugins': {'name': plugin, 'commands': []}}}
                )

            return await bulk.execute()

    def _plugin_for_cmd(self, command):
        if self.commands.get(command):
            return self.commands[command][2].info['plugin']

    async def enable_command(self, server_id, command, user_id=None):
        log.debug(f'enabling {command} command for server {server_id}')

        plugin_name = self._plugin_for_cmd(command)

        if not plugin_name:
            return False

        if not self.mbot.perms_check(User(id=user_id), su=True):
            # Skip Core plugin.
            if plugin_name == 'Core':
                return False

            # Skip 'su' commands if not superuser
            if self.commands[command][2].info['perms'][0]:
                return False

        try:
            ret = await self.mbot.mongo.config.update_one(
                {'server_id': server_id, 'plugins': {'$elemMatch': {'name': plugin_name}}},
                {'$addToSet': {'plugins.$.commands': command}}
            )

            return ret.modified_count > 0
        except PyMongoError:
            return False

    async def global_enable_commands(self, commands_list):
        cmd_list = defaultdict(list)

        for command in commands_list:
            plugin = self._plugin_for_cmd(command)

            if plugin:
                cmd_list[plugin].append(command)

        bulk = self.mbot.mongo.config.initialize_unordered_bulk_op()

        for pl in cmd_list:
            bulk.find({'plugins': {'$elemMatch': {'name': pl}}}).update(
                {'$addToSet': {'plugins.$.commands': {'$each': cmd_list[pl]}}}
            )

        return await bulk.execute()

    async def disable_command(self, server_id, command, user_id=None):
        log.debug(f'disabling {command} command for server {server_id}')

        plugin_name = self._plugin_for_cmd(command)

        if not plugin_name:
            return False

        if not self.mbot.perms_check(User(id=user_id), su=True):
            # Skip Core plugin.
            if plugin_name == 'Core':
                return False

            # Skip 'su' commands if not superuser
            if self.commands[command][2].info['perms'][0]:
                return False

        try:
            ret = await self.mbot.mongo.config.update_one(
                {'server_id': server_id, 'plugins': {'$elemMatch': {'name': plugin_name}}},
                {'$pull': {'plugins.$.commands': command}}
            )

            return ret.modified_count > 0
        except PyMongoError:
            return False

    async def global_disable_commands(self, commands_list):
        cmd_list = defaultdict(list)

        for command in commands_list:
            plugin = self._plugin_for_cmd(command)

            if plugin:
                cmd_list[plugin].append(command)

        bulk = self.mbot.mongo.config.initialize_unordered_bulk_op()

        for p in cmd_list:
            bulk.find({'plugins': {'$elemMatch': {'name': p}}}).update(
                {'$pull': {'plugins.$.commands': {'$in': cmd_list[p]}}}
            )

        return await bulk.execute()

    async def refresh_configs(self):
        plugin_data = []

        for plugin in self.plugins:
            plugin_data.append(
                {
                    'name': plugin.__class__.__name__,
                    'commands': [command.info['name'] for command in plugin.commands]
                }
            )

        return await self.mbot.mongo.config.update_many(
            {},
            {'$set': {'plugins': plugin_data}}
        )
