import sys
import importlib.util

import asyncio

from .plugins import plugins
from .utils import long_running_task
from .plugin_registry import PluginRegistry


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
        for plugin in self.discover_plugins():
            self.plugins.append(plugin(self.mbot))

    def load_commands(self):
        '''Load commands for all loaded plugins.'''
        for plugin in self.plugins:
            for command in plugin.commands:
                self.commands[command.info['name']] = (command.info['desc'], command.info['usage'], command)

    async def reload_plugins(self):
        '''
        Reload all plugins and commands.
        Any new plugins and commands are enabled by default.
        Any plugins and commands that were removed are automatically disabled.
        '''
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

    def _plugins_for_server(self, server_id):
        ret = {}

        for plugin in self.plugins:
            doc = self.mbot.mongo.config.find_one(
                {'server_id': server_id, 'plugins': {'$elemMatch': {'name': plugin.__class__.__name__}}}
            )

            if doc is not None:
                ret[plugin.__class__.__name__] = plugin

        return ret

    @long_running_task()
    def plugins_for_server(self, server_id):
        return self._plugins_for_server(server_id)

    def _commands_for_server(self, server_id):
        ret = {}

        for plugin in self.plugins:
            doc = self.mbot.mongo.config.find_one(
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

    @long_running_task()
    def commands_for_server(self, server_id):
        return self._commands_for_server(server_id)

    @long_running_task()
    def disable_plugin(self, server_id, plugin):
        # Skip config plugin.
        if plugin == 'ConfigPlugin':
            return False

        if plugin in [p.__class__.__name__ for p in self.plugins]:
            ret = self.mbot.mongo.config.update_one(
                {'server_id': server_id},
                {'$pull': {'plugins': {'name': plugin}}}
            )

            return bool(ret)

    @long_running_task()
    def enable_plugin(self, server_id, plugin):
        # Skip config plugin.
        if plugin == 'ConfigPlugin':
            return False

        doc = self.mbot.mongo.config.find_one(
            {'server_id': server_id, 'plugins': {'$elemMatch': {'name': plugin}}}
        )

        if doc:
            # Plugin is already enabled.
            return False

        if plugin in [p.__class__.__name__ for p in self.plugins]:
            ret = self.mbot.mongo.config.update_one(
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

    @long_running_task()
    def enable_command(self, server_id, command):
        plugin_name = self._plugin_for_cmd(command)

        # Skip config plugin.
        if plugin_name == 'ConfigPlugin' or not plugin_name:
            return False

        doc = self.mbot.mongo.config.find_one(
                {'server_id': server_id, 'plugins': {'$elemMatch': {'name': plugin_name}}}
            )

        # Command is already enabled.
        if command in self._commands_for_server(server_id):
            return False

        if doc is not None:
            ret = self.mbot.mongo.config.update_one(
                {'server_id': server_id, 'plugins': {'$elemMatch': {'name': plugin_name}}},
                {'$push': {'plugins.$.commands': command}}
            )

            return bool(ret)

    @long_running_task()
    def disable_command(self, server_id, command):
        plugin_name = self._plugin_for_cmd(command)

        # Skip config plugin.
        if plugin_name == 'ConfigPlugin' or not plugin_name:
            return False

        doc = self.mbot.mongo.config.find_one(
                {'server_id': server_id, 'plugins': {'$elemMatch': {'name': plugin_name}}}
            )

        if doc is not None:
            ret = self.mbot.mongo.config.update_one(
                {'server_id': server_id, 'plugins': {'$elemMatch': {'name': plugin_name}}},
                {'$pull': {'plugins.$.commands': command}}
            )

            return bool(ret)
