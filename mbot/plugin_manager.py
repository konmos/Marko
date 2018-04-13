import sys
import logging
import importlib.util

import asyncio
from discord import User

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

        # Primitive lock for the plugin manager. This is not used directly....
        # However, all plugins that use the plugin manager to enabled, disable,
        # load, and unload plugins should use this.
        self.lock = asyncio.Lock()

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
        Reload all plugins and commands.
        Any new plugins and commands are enabled by default.
        Any plugins and commands that were removed are automatically disabled.
        '''
        log.debug('attempting to reload plugins')

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
                for server in self.mbot.servers:
                    await self.enable_plugin(server.id, plugin)
            # Plugin was deleted.
            elif plugin not in new_plugins:
                for server in self.mbot.servers:
                    await self.disable_plugin(server.id, plugin)

        log.debug('reloaded plugins')

        # Now, handle command creations / deletions.
        diff_c = set(old_commands) ^ set(new_commands)

        for cmd in diff_c:
            # Command was created.
            if cmd not in old_commands:
                for server in self.mbot.servers:
                    await self.enable_command(server.id, cmd)
            # Command was deleted.
            elif cmd not in new_commands:
                for server in self.mbot.servers:
                    await self.disable_command(server.id, cmd)

        log.debug('reloaded commands')

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
            ret = await self.mbot.mongo.config.update_one(
                {'server_id': server_id},
                {'$pull': {'plugins': {'name': plugin}}}
            )

            return bool(ret)

    async def enable_plugin(self, server_id, plugin):
        log.debug(f'enabling {plugin} plugin for server {server_id}')

        # Skip Core plugin.
        if plugin == 'Core':
            return False

        doc = await self.mbot.mongo.config.find_one(
            {'server_id': server_id, 'plugins': {'$elemMatch': {'name': plugin}}}
        )

        if doc:
            # Plugin is already enabled.
            return False

        if plugin in [p.__class__.__name__ for p in self.plugins]:
            ret = await self.mbot.mongo.config.update_one(
                {'server_id': server_id},
                {'$push': {'plugins': {'name': plugin, 'commands': []}}}
            )

            return bool(ret)

    def _plugin_for_cmd(self, command):
        plugin_name = None

        for plugin in self.plugins:
            if command in [cmd.info['name'] for cmd in plugin.commands]:
                plugin_name = plugin.__class__.__name__
                break

        return plugin_name

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

        doc = await self.mbot.mongo.config.find_one(
                {'server_id': server_id, 'plugins': {'$elemMatch': {'name': plugin_name}}}
            )

        commands = await self.commands_for_server(server_id)
        # Command is already enabled.
        if command in commands:
            return False

        if doc is not None:
            ret = await self.mbot.mongo.config.update_one(
                {'server_id': server_id, 'plugins': {'$elemMatch': {'name': plugin_name}}},
                {'$push': {'plugins.$.commands': command}}
            )

            return bool(ret)

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

        doc = await self.mbot.mongo.config.find_one(
                {'server_id': server_id, 'plugins': {'$elemMatch': {'name': plugin_name}}}
            )

        if doc is not None:
            ret = await self.mbot.mongo.config.update_one(
                {'server_id': server_id, 'plugins': {'$elemMatch': {'name': plugin_name}}},
                {'$pull': {'plugins.$.commands': command}}
            )

            return bool(ret)
