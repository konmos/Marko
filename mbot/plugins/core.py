from ..plugin import BasePlugin
from ..command import command


DEFAULT_HELP = (
    'For help on individual commands use: `{prefix}help <command>`\n'
    '**To view a list of the currently enabled commands use:** `{prefix}commands`'
)


CMD_HELP = (
    '**{name}** - *{description}*\n\n'
    'Usage: `{prefix}{usage}`'
)


class Core(BasePlugin):
    @command(regex='^help(?: (.*?))?$', usage='help <command>', description='displays the help page')
    async def help(self, message, cmd=None):
        server_cfg = await self.mbot.mongo.config.find_one({'server_id': message.server.id})
        commands = await self.mbot.plugin_manager.commands_for_server(message.server.id)

        if not cmd:
            await self.mbot.send_message(message.channel, DEFAULT_HELP.format(
                prefix=server_cfg['prefix']
            ))
        else:
            if cmd in commands:
                await self.mbot.send_message(message.channel, CMD_HELP.format(
                    name = cmd,
                    description = self.mbot.plugin_manager.commands[cmd][0],
                    prefix = server_cfg['prefix'],
                    usage = self.mbot.plugin_manager.commands[cmd][1]))
            else:
                await self.mbot.send_message(message.channel, '*I did not recognize that command...*')

    @command(regex='^commands$', description='displays a list of the currently enabled commands',
             usage='commands', name='commands')
    async def list_commands(self, message):
        msg = '**List of enabled plugins:**\n\n'
        enabled_plugins = await self.mbot.plugin_manager.plugins_for_server(message.server.id)
        commands = await self.mbot.plugin_manager.commands_for_server(message.server.id)

        for x, plugin in enumerate(enabled_plugins):
            msg += f'**{x+1}. {plugin}:** '

            for i, cmd in enumerate([c.info['name'] for c in enabled_plugins[plugin].commands]):
                if cmd in commands:
                    if i + 1 == len(enabled_plugins[plugin].commands):
                        msg += f'`{cmd}`'
                    else:
                        msg += f'`{cmd}`, '

            msg += '\n'

        await self.mbot.send_message(message.channel, msg)

    @command(su=True, description='reload all plugins and commands globally', usage='reload')
    async def reload(self, message):
        with await self.mbot.plugin_manager.lock:
            await self.mbot.plugin_manager.reload_plugins()
            await self.mbot.send_message(
                message.channel, f':ok_hand: **Successfully reloaded all plugins!**'
            )
