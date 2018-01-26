import zerorpc
from threading import Thread


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
        self._mbot = mbot

    def plugins_for_server(self, server_id):
        commands = self._mbot.plugin_manager._commands_for_server(server_id)
        all_plugins, plugins = self._mbot.plugin_manager._plugins_for_server(server_id), {}

        for plugin in all_plugins:
            plugins[plugin] = {}

            for command in all_plugins[plugin].commands:
                if command.info['name'] in commands:
                    plugins[plugin][command.info['name']] = {
                        'usage': command.info['usage'],
                        'description': command.info['desc'],
                        'regex': command._pattern.pattern
                    }

        return plugins

    def all_plugins(self):
        all_plugins, plugins = self._mbot.plugin_manager.plugins, {}

        for plugin in all_plugins:
            plugin_name = plugin.__class__.__name__
            plugins[plugin_name] = {}

            for command in plugin.commands:
                plugins[plugin_name][command.info['name']] = {
                    'usage': command.info['usage'],
                    'description': command.info['desc'],
                    'regex': command._pattern.pattern
                }

        return plugins

    def enable_commands(self, server_id, commands):
        return_vals = []

        for command in commands:
            return_vals.append(self._mbot.plugin_manager._enable_command(server_id, command))

        return return_vals

    def disable_commands(self, server_id, commands):
        return_vals = []

        for command in commands:
            return_vals.append(self._mbot.plugin_manager._disable_command(server_id, command))

        return return_vals
