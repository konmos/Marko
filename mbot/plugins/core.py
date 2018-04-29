from ..plugin import BasePlugin
from ..command import command


DEFAULT_HELP = (
    'For help on individual commands use: `{prefix}help <command>`\n'
    'To find out more about a plugin use: `{prefix}plugin <plugin>`\n'
    '**To view all plugins and commands use:** `{prefix}commands`\n\n'
    '**__Understanding Command Usages__**\n\n'
    '`text without brackets/braces/parentheses` - items you must type as shown\n'
    '`<text inside angle brackets>` - placeholder for which you must supply a value\n'
    '`[text inside square brackets]` - optional items\n'
    '`(text inside parentheses)` - set of required items; choose one\n'
    '`vertical bar (|)` - separator for mutually exclusive items; choose one\n'
    '`ellipsis (…)` - items that can be repeated'
)


CMD_HELP = (
    '**{name}** - *{description}*\n\n'
    'Usage: `{prefix}{usage}`'
)


class Core(BasePlugin):
    @command(regex='^plugin (.*?)$', name='plugin', usage='plugin (<plugin>)',
             description='display more info on a certain plugin')
    async def plugin_help(self, message, plugin):
        plugins = await self.mbot.plugin_manager.plugins_for_server(message.server.id)

        if not plugins.get(plugin):
            return await self.mbot.send_message(message.channel, '**I could not find that plugin...** :cry:')

        plugin_obj = plugins.get(plugin)

        await self.mbot.send_message(
            message.channel,
            f'**{plugin}**\n\n{plugin_obj.info}'
        )

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

        disabled_plugins = set([p.__class__.__name__ for p in self.mbot.plugin_manager.plugins]).difference(
            set([x for x in enabled_plugins])
        )

        disabled_commands = set([c for c in self.mbot.plugin_manager.commands]).difference(
            set([x for x in commands])
        )

        if disabled_plugins:
            msg += f'\n**Disabled Plugins:**\n\n{" ".join(disabled_plugins)}'

        if disabled_commands:
            msg += f'\n**Disabled Commands:**\n{" ".join(disabled_commands)}'

        await self.mbot.send_message(message.channel, msg)

    @command(su=True, description='reload all plugins and commands globally', usage='reload')
    async def reload(self, message):
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

    @command(su=True, regex='^su-ayy+$', name='su-ayy')
    async def su_ayy(self, message):
        await self.mbot.send_message(message.channel, '*su-lmao*')

    @command(su=True, regex='^refresh-configs$', name='refresh-configs')
    async def refresh_configs(self, message):
        ret = await self.mbot.plugin_manager.refresh_configs()
        await self.mbot.send_message(message.channel, f':ok_hand: **Refreshed {ret.modified_count} configs.**')
