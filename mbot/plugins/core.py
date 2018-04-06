from ..plugin import BasePlugin
from ..command import command
from ..premium_manager import KeyUnauthorised

from discord import Forbidden


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
            await self.mbot.plugin_manager.reload_plugins()
            await self.mbot.send_message(
                message.channel, f':ok_hand: **Successfully reloaded all plugins!**'
            )

    @command(regex='^upgrade (.*?)$', usage='upgrade <key>',
             description='upgrade this guild to premium status with a key')
    async def upgrade(self, message, key):
        if not await self.mbot.premium_manager.is_key_valid(key):
            return await self.mbot.send_message(
                message.channel,
                '**That key appears to be invalid!** :cry:'
            )

        key_obj = await self.mbot.premium_manager.get_key(key)

        await self.mbot.send_message(
            message.channel,
            f'**Are you sure you want to upgrade *"{message.server.name}"* with this key?**\n'
            f'```Key: {key_obj.key}\nNote: {key_obj.key_note}\nUses remaining: {key_obj.uses_remaining}\n'
            f'Upgrade type: {key_obj.readable_type}```'
        )

        confirm_action = False

        if message.server.me.permissions_in(message.channel).add_reactions:
            m = await self.mbot.send_message(
                message.channel, '*React to this message to let me know what to do...*'
            )

            await self.mbot.add_reaction(m, '\u2705')
            await self.mbot.add_reaction(m, '\u274C')

            ret = await self.mbot.wait_for_reaction(['\u2705', '\u274C'], message=m, user=message.author, timeout=60)

            if ret is not None and str(ret[0].emoji) == '\u2705':
                confirm_action = True
        else:
            await self.mbot.send_message(
                message.channel, '*Please reply either "[y]es" or "[n]o" to let me know what to do...*'
            )

            ret = await self.mbot.wait_for_message(
                author=message.author, timeout=60, check=lambda x: x.content[0] in ('n', 'y'), channel=message.channel
            )

            if ret is not None and ret.content.startswith('y'):
                confirm_action = True

        if confirm_action:
            try:
                await self.mbot.premium_manager.upgrade_guild(message.server.id, message.author.id, key)

                try:
                    await self.mbot.change_nickname(message.server.me, 'Marko Premium')
                except Forbidden:
                    pass

                return await self.mbot.send_message(
                    message.channel, f'{message.author.mention} **Guild upgraded!** :ok_hand:'
                )
            except KeyUnauthorised:
                return await self.mbot.send_message(
                    message.channel, f'{message.author.mention} **You cannot use that key!**'
                )

        return await self.mbot.send_message(
            message.channel, f'{message.author.mention} **Guild could not be upgraded!** :cry:'
        )

    @command(su=True, regex='^keygen(?: (.*?))?$', description='generate an upgrade key')
    async def keygen(self, message, args=None):
        if args:
            key_data = dict(x.strip().split('=') for x in args.split(','))
        else:
            key_data = {}

        if key_data.get('authorised_users'):
            key_data['authorised_users'] = key_data.get('authorised_users').split(';')

        key = await self.mbot.premium_manager.generate_key(**key_data)

        await self.mbot.send_message(
            message.channel,
            f'```Key: {key.key}\nType: {key.key_type}\nTTL: {key.ttl}\nMax uses: {key.max_uses}'
            f'\nNote: {key.key_note}```'
        )
