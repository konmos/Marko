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
        self.mbot = mbot

    def installed_plugins(self):
        return [plugin.__class__.__name__ for plugin in self.mbot.plugin_manager.plugins]

    def installed_commands(self):
        return list(self.mbot.plugin_manager.commands)

    def plugin_for_command(self, cmd):
        return self.mbot.plugin_manager._plugin_for_cmd(cmd)

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

    def reload_plugins(self):
        async def task():
            await self.mbot.plugin_manager.reload_plugins()

        self.mbot.loop.create_task(task())
