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
        author, channel = message.author, message.channel

        msg = '**List of enabled plugins/commands:**\n*Commands like __`this`__ require elevated permissions.*\n\n'
        enabled_plugins = await self.mbot.plugin_manager.plugins_for_server(message.server.id)
        commands = await self.mbot.plugin_manager.commands_for_server(message.server.id)

        for x, plugin in enumerate(enabled_plugins):
            msg += f'**{x+1}. {plugin}:** '

            # Hide 'su' commands if not superuser
            filtered_commands = [
                (c.info['name'], c.info['perms']) for c in enabled_plugins[plugin].commands if not
                (c.info['perms'][0] and not self.mbot.perms_check(author, channel, c.info['perms'][1], True))
                and c.info['name'] in commands
            ]

            for i, cmd in enumerate(filtered_commands):
                if cmd[1][0] or cmd[1][1] is not None:
                    msg += f'*__`{cmd[0]}`__*'
                else:
                    msg += f'`{cmd[0]}`'

                if not i + 1 >= len(filtered_commands):
                    msg += ' '

            msg += '\n'

        await self.mbot.send_message(message.channel, msg)

    @command(su=True, description='reload all plugins and commands globally', usage='reload')
    async def reload(self, message):
        with await self.mbot.plugin_manager.lock:
            ret = await self.mbot.plugin_manager.reload_plugins()

            await self.mbot.send_message(
                message.channel,
                f':ok_hand: **Successfully reloaded all plugins!**\n\n'
                f'**New Plugins**\n```{ret["new_plugins"]}```\n'
                f'**Deleted Plugins**\n```{ret["deleted_plugins"]}```\n'
                f'**New Commands**\n```{ret["new_commands"]}```\n'
                f'**Deleted Commands**\n```{ret["deleted_commands"]}```\n'
            )

    @command(su=True, regex='^gec (.*?)$')
    async def gec(self, message, commands):
        await self.mbot.plugin_manager.global_enable_commands(commands.split(','))
        await self.mbot.send_message(message.channel, 'Done')

    @command(su=True, regex='^gdc (.*?)$')
    async def gdc(self, message, commands):
        await self.mbot.plugin_manager.global_disable_commands(commands.split(','))
        await self.mbot.send_message(message.channel, 'Done')

    @command(su=True, regex='^gep (.*?)$')
    async def gep(self, message, plugins):
        await self.mbot.plugin_manager.global_enable_plugins(plugins.split(','))
        await self.mbot.send_message(message.channel, 'Done')

    @command(su=True, regex='^gdp (.*?)$')
    async def gdp(self, message, plugins):
        await self.mbot.plugin_manager.global_disable_plugins(plugins.split(','))
        await self.mbot.send_message(message.channel, 'Done')
