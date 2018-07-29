import time

from textwrap import dedent
from datetime import datetime

import discord
from bson.json_util import loads
from pymongo.results import InsertOneResult, DeleteResult, UpdateResult

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
    'Usage: `{prefix}{usage}`{aliases}\n\n'
    '{detailed_info}'
)


ALLOWED_DB_OPS = (
    'insert_one', 'replace_one',
    'delete_one', 'delete_many',
    'update_one', 'update_many',
)


class Core(BasePlugin):
    @command()
    async def info(self, message):
        app_info = await self.mbot.application_info()
        local_time = datetime.now().strftime('%a, %d %b %Y %H:%M:%S')

        embed = discord.Embed(title='MarkoBot', colour=0x7289da)
        embed.set_thumbnail(url=app_info.icon_url)

        embed.add_field(name='Owner', value=f'{app_info.owner.name}#{app_info.owner.discriminator}')
        embed.add_field(name='Language / Library', value=f'Python / discord.py ({discord.__version__})')
        embed.add_field(
            name='# Plugins / Commands',
            value=f'{len(self.mbot.plugin_manager.plugins)} / {len(self.mbot.plugin_manager.commands)}'
        )
        embed.add_field(name='Help Commands', value='help, commands, plugin')
        embed.add_field(name='Local Time', value=local_time, inline=False)

        await self.mbot.send_message(message.channel, embed=embed)

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
            c = self.mbot.plugin_manager.command_from_string(cmd, False)

            if c and c.info['name'] in commands:
                detailed_info = dedent(
                    getattr(self.mbot.plugin_manager.commands[c.info['name']][2], 'detailed_info', '').format(
                        command=server_cfg['prefix'] + c.info['name']
                    )
                )

                await self.mbot.send_message(message.channel, CMD_HELP.format(
                    name=c.info['name'],
                    description=self.mbot.plugin_manager.commands[c.info['name']][0],
                    prefix=server_cfg['prefix'],
                    usage=self.mbot.plugin_manager.commands[c.info['name']][1],
                    detailed_info=detailed_info,
                    aliases=f'\nAliases: `{" | ".join(c.info["aliases"])}`' if c.info["aliases"] else ''
                ))
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

    @command(regex='^disabled-commands$', description='display all disabled plugins and commands',
             name='disabled-commands')
    async def disabled_commands(self, message):
        enabled_plugins = await self.mbot.plugin_manager.plugins_for_server(message.server.id)
        commands = await self.mbot.plugin_manager.commands_for_server(message.server.id)

        disabled_plugins = set([p.__class__.__name__ for p in self.mbot.plugin_manager.plugins]).difference(
            set([x for x in enabled_plugins])
        )

        disabled_commands = set([c for c in self.mbot.plugin_manager.commands]).difference(
            set([x for x in commands])
        )

        msg = ''

        if disabled_plugins:
            msg += f'\n**Disabled Plugins:**\n{" ".join(disabled_plugins)}\n'

        if disabled_commands:
            msg += f'\n**Disabled Commands:**\n{" ".join(disabled_commands)}'

        if msg:
            await self.mbot.send_message(message.channel, msg)
        else:
            await self.mbot.send_message(message.channel, '**Sweet! Everything seems to be enabled.** :ok_hand:')

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

    @command(su=True, regex='^reset-configs$', name='reset-configs')
    async def reset_configs(self, message):
        ret = await self.mbot.plugin_manager.refresh_configs()
        await self.mbot.send_message(message.channel, f':ok_hand: **Reset {ret.modified_count} configs.**')

    @command(su=True, regex='^db (\w+?)\.(\w+?) (\w+?) (.+)$', name='db')
    async def run_db_op(self, message, db, col, op, data):
        data = data.replace('$SERVER$', message.server.id).replace('$CHANNEL$', message.channel.id)

        if op not in ALLOWED_DB_OPS:
            return await self.mbot.send_message(message.channel, f'`{op}` Operation not allowed.')

        try:
            database = getattr(self.mbot.mongo, db)
            collection = getattr(database, col)
            operation = getattr(collection, op)
        except AttributeError:
            return await self.mbot.send_message(message.channel, 'Unknown database or operation.')

        # The data argument can either be a array of args which are star-unpacked,
        # or it can be a dict with two top level values "args" and "kwargs";
        # args must be an array and kwargs must be a dict.
        try:
            decoded_data = loads(data)
        except:
            return await self.mbot.send_message(message.channel, 'Incorrect argument data.')

        if isinstance(decoded_data, dict):
            ret = await operation(
                *decoded_data.get('args', []),
                **decoded_data.get('kwargs', {})
            )
        elif isinstance(decoded_data, list):
            ret = await operation(
                *decoded_data
            )
        else:
            ret = None

        if ret is not None:
            if isinstance(ret, UpdateResult):
                return await self.mbot.send_message(
                    message.channel,
                    f'**Done! Updated {ret.modified_count} document(s).**'
                )
            elif isinstance(ret, InsertOneResult):
                return await self.mbot.send_message(
                    message.channel,
                    f'**Done! Inserted document with `_id` `{ret.inserted_id}`.**'
                )
            elif isinstance(ret, DeleteResult):
                return await self.mbot.send_message(
                    message.channel,
                    f'**Done! Deleted {ret.deleted_count} document(s).**'
                )

        return await self.mbot.send_message(message.channel, 'An unknown error occurred.')

    @command(regex='^leave(?: (.*?))?$', su=True)
    async def leave(self, message, server_id=None):
        try:
            await self.mbot.leave_server(
                self.mbot.get_server(server_id) if server_id else message.server
            )
        except AttributeError:
            await self.mbot.send_message(
                message.channel, '*The specified server does not exist!*'
            )

    @command(regex='^global-blacklist (add|remove) (\d+)(?: (.*?))?$', name='global-blacklist', su=True)
    async def global_blacklist(self, message, op, user_id, reason=None):
        if op == 'add':
            ret = await self.mbot.mongo.bot_data.global_blacklist.update_one(
                {'user_id': user_id},
                {'$setOnInsert': {'timestamp': time.time()}, '$set': {'reason': reason}},
                upsert=True
            )

            if ret.upserted_id is not None:
                try:
                    user = await self.mbot.get_user_info(user_id)

                    await self.mbot.send_message(
                        user,
                        f'You have been added to my global blacklist by an admin.\n'
                    )
                except (discord.NotFound, discord.HTTPException):
                    return
        else:
            ret = await self.mbot.mongo.bot_data.global_blacklist.delete_one(
                {'user_id': user_id}
            )

            if ret.deleted_count == 1:
                try:
                    user = await self.mbot.get_user_info(user_id)

                    await self.mbot.send_message(
                        user,
                        f'You have been removed from my global blacklist.'
                    )
                except (discord.NotFound, discord.HTTPException):
                    return

        await self.mbot.send_message(message.channel, 'Done.')
