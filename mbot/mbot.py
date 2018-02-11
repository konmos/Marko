import os
import io
import re
import sys
import struct
import logging
from difflib import SequenceMatcher as SM

import aiohttp
import discord

from .plugin_manager import PluginManager
from .database import Mongo

log = logging.getLogger(__name__)

opus_lib = {
    '32': os.path.join('bin', 'libopus-0.x86.dll'),
    '64': os.path.join('bin', 'libopus-0.x64.dll')
}


class mBot(discord.Client):
    def __init__(self, config, **kwargs):
        super().__init__(**kwargs)

        # Default global config.
        self.config = config
        self.key = config.mbot.key

        self.mongo = Mongo(config)
        self.loop.create_task(self.mongo.init_stats())

        # Load opus on Windows. On linux it should be already loaded.
        if os.name in ['nt', 'ce']:
            discord.opus.load_opus(name=opus_lib[str(struct.calcsize('P') * 8)])

        self.plugin_manager = PluginManager(self)
        self.plugin_manager.load_plugins()
        self.plugin_manager.load_commands()

    def run(self, *args, **kwargs):
        '''Blocking call which runs the client using `self.key`.'''
        return super(mBot, self).run(self.key, *args, **kwargs)

    async def send_file(self, destination, fp, *, filename=None, content=None, tts=False, force=False):
        '''Sends a message to the destination given with the file given.'''

        # Update global statistics
        await self.mongo.stats.update_one(
            {'scope': 'global'},
            {'$inc': {'files_sent': 1}}
        )

        if not force:
            # Check if we are in an ignored channel.
            if isinstance(destination, discord.Server):
                cfg = await self.mongo.config.find_one({'server_id': destination.id})

                if destination.default_channel.id in cfg['ignored_channels']:
                    return

            elif isinstance(destination, (discord.Channel, discord.PrivateChannel)):
                cfg = await self.mongo.config.find_one({'server_id': destination.server.id})

                if destination.id in cfg['ignored_channels']:
                    return

        # Simple patch to the `send_file` method which adds support for the http protocol
        # and automatically downloads files before uploading them.
        # This is just a convenience function and should generally only be used
        # for one-off, small downloads.
        try:
            if fp.startswith('http://') or fp.startswith('https://'):
                with aiohttp.ClientSession() as client:
                    async with client.get(fp) as r:
                        buffer = io.BytesIO(bytes(await r.read()))

                        ret = await super(mBot, self).send_file(
                            destination, buffer, filename=fp.split('/')[-1], content=content, tts=tts
                        )

                        buffer.close()

                        return ret
            else:
                ret = await super(mBot, self).send_file(destination, fp, filename=filename, content=content, tts=tts)
                return ret
        except AttributeError:
            ret = await super(mBot, self).send_file(destination, fp, filename=filename, content=content, tts=tts)
            return ret

    async def send_message(self, destination, content=None, *, tts=False, embed=None, force=False):
        '''Sends a message to the destination given with the content given.'''

        # Update global statistics
        await self.mongo.stats.update_one(
            {'scope': 'global'},
            {'$inc': {'messages_sent': 1}}
        )

        # The force argument should generally not be used. Ignored channels must be respected.
        # This argument is currently only used when an admin is managing ignored channels
        # via the enable/disable commands.
        if not force:
            # Check if we are in an ignored channel.
            if isinstance(destination, discord.Server):
                cfg = await self.mongo.config.find_one({'server_id': destination.id})

                if destination.default_channel.id in cfg['ignored_channels']:
                    return

            elif isinstance(destination, (discord.Channel, discord.PrivateChannel)):
                cfg = await self.mongo.config.find_one({'server_id': destination.server.id})

                if destination.id in cfg['ignored_channels']:
                    return

        # Patch which prefixes all messages with a zero-length space.
        # This helps prevent our sent messages from triggering other bots.
        if content is not None:
            content = f'\u200B{content}'

        ret = await super(mBot, self).send_message(destination, content, tts=tts, embed=embed)
        return ret

    async def _create_config(self, server_id):
        '''Create a default configuration for a new server.'''
        cfg = await self.mongo.config.find_one({'server_id': server_id})

        if cfg is None:
            plugins = []

            for plugin in self.plugin_manager.plugins:
                plugins.append(
                    {
                        'name': plugin.__class__.__name__,
                        'commands': [command.info['name'] for command in plugin.commands]
                    }
                )

            cfg = {
                'server_id': server_id,
                'prefix': self.config.mbot.cmd_prefix,  # Default command prefix.
                'plugins': plugins,  # List of enabled plugins and their commands.

                # Ignored channels are channels in which the bot cannot talk.
                # The `on_message` event is ignored in these channels. The only exception to
                # this is when an admin runs either the `ignore` or `unignore` command. In this case
                # the event is still triggered and the command goes through - this is done for convenience.
                # All other events still trigger normally.
                'ignored_channels': []
            }

            await self.mongo.config.insert_one(cfg)

    async def on_ready(self):
        '''Called when the client is done preparing the data received from Discord.'''
        log.debug(f'{sys._getframe().f_code.co_name} event triggered')

        # Check if server settings exist and create them if not.
        for server in self.servers:
            await self._create_config(server.id)

        # Update global statistics
        await self.mongo.stats.update_one(
            {'scope': 'global'},
            {'$set': {'num_guilds': len(self.servers)}}
        )

        await self.change_presence(game=discord.Game(name=f'in {len(self.servers)} servers'))

        for plugin in self.plugin_manager.plugins:
            self.loop.create_task(plugin.on_ready())

    async def on_resumed(self):
        '''Called when the client has resumed a session.'''
        log.debug(f'{sys._getframe().f_code.co_name} event triggered')

        for plugin in self.plugin_manager.plugins:
            self.loop.create_task(plugin.on_resumed())

    # async def on_error(self, event, *args, **kwargs):
    #    '''Suppress the default action of printing the traceback.'''
    #    for plugin in self.plugin_manager.plugins:
    #        self.loop.create_task(plugin.on_error(event, *args, **kwargs))

    async def on_message(self, message):
        '''Called when a message is created and sent to a server.'''
        log.debug(f'{sys._getframe().f_code.co_name} event triggered')

        # Update global statistics
        await self.mongo.stats.update_one(
            {'scope': 'global'},
            {'$inc': {'messages_received': 1}}
        )

        if message.channel.is_private:
            return

        if message.author.bot:
            return

        cfg = await self.mongo.config.find_one({'server_id': message.server.id})

        # If we get mentioned, reply with a default help command.
        if re.match(f'^<@{self.user.id}>.*?$', message.content):
            prefix = cfg["prefix"]

            await self.send_message(
                message.channel,
                f':wave: **Hi there {message.author.mention}. The default prefix in this server is '
                f'`{prefix}`. For help try running `{prefix}help`. For help on a specific command try '
                f'`{prefix}help <command>`. To view a list of all commands run `{prefix}commands`. '
                'Have fun!** :ok_hand:'
            )

            return

        # This event is skipped in ignored channels...
        if message.channel.id in cfg['ignored_channels']:
            # ...Unless the user is an admin and runs either the `ignore` or `unignore` command.
            if message.author.permissions_in(message.channel).administrator:
                pattern = f'^(?:{re.escape(cfg["prefix"])}|{re.escape("!!?")})(?:ignore|unignore)$'

                if not re.match(pattern, message.content):
                    return
            else:
                return

        cmd, matched_cmd = False, None
        # An admin cmd is one that starts with `!!?`
        # it allows the admin user to bypass server configurations for the prefix,
        # and for enabled / disabled plugins.
        admin_cmd = False

        if message.content.startswith(cfg['prefix']):
            message.content, cmd = message.content[len(cfg['prefix']):], True
        elif message.author.permissions_in(message.channel).administrator and message.content.startswith('!!?'):
            # Anything prefixed with the hardcoded prefix `!!?` will be treated as a command,
            # but only if the user is an admin. This is here just in case the users mess something up, ie.
            # forgetting the prefix, or disabling some key plugins.
            await self.send_message(
                message.channel,
                f'{message.author.mention} *Has disaster struck?\nAnything prefixed with `!!?` will be treated '
                'as a command.\nIn this mode, you can run commands even if they are disabled on the server.\n'
                'Use this in case of emergencies such as forgetting the prefix or disabling key plugins.*',
                force=True
            )

            message.content, cmd, admin_cmd = message.content[3:], True, True

        if admin_cmd:
            commands = dict([(cmd, self.plugin_manager.commands[cmd][-1]) for cmd in self.plugin_manager.commands])
        else:
            commands = await self.plugin_manager.commands_for_server(message.server.id)

        if cmd:
            for command in commands.values():
                if command._pattern.match(message.content):
                    self.loop.create_task(command(message))

                    matched_cmd = command
                    break  # Ignore possible name conflicts... Commands should have unique names!

        plugins = await self.plugin_manager.plugins_for_server(message.server.id)

        for plugin in plugins.values():
            # If a command was called for a plugin, we ignore that plugin's `on_message` event.
            # If it needs to be called, the `call_on_message` argument of the `command` decorator
            # should be set to `True`.
            if matched_cmd is None or matched_cmd.info['plugin'] != plugin.__class__.__name__:
                self.loop.create_task(plugin.on_message(message))

        # No command was found... Suggest possible fixes.
        if not matched_cmd and cmd:
            fixes = [
                (SM(None, message.content, x).ratio(), x) for x in commands.keys()
            ]

            best_candidate = max(fixes, key=lambda x: x[0])[1]

            await self.send_message(
                message.channel, f'*I couldn\'t understand that... How about running **{best_candidate}***?'
            )

    async def on_socket_raw_receive(self, msg):
        '''Called whenever a message is received from the websocket.'''
        log.debug(f'{sys._getframe().f_code.co_name} event triggered')

        for plugin in self.plugin_manager.plugins:
            self.loop.create_task(plugin.on_socket_raw_receive(msg))

    async def on_socket_raw_send(self, payload):
        '''Called whenever a send operation is done on the websocket.'''
        log.debug(f'{sys._getframe().f_code.co_name} event triggered')

        for plugin in self.plugin_manager.plugins:
            self.loop.create_task(plugin.on_socket_raw_send(payload))

    async def on_message_delete(self, message):
        '''Called when a message is deleted.'''
        log.debug(f'{sys._getframe().f_code.co_name} event triggered')
        plugins = await self.plugin_manager.plugins_for_server(message.server.id)

        for plugin in plugins.values():
            self.loop.create_task(plugin.on_message_delete(message))

    async def on_message_edit(self, before, after):
        '''Called when a message receives an update event.'''
        log.debug(f'{sys._getframe().f_code.co_name} event triggered')
        plugins = await self.plugin_manager.plugins_for_server(before.server.id)

        for plugin in plugins.values():
            self.loop.create_task(plugin.on_message_edit(before, after))

    async def on_reaction_add(self, reaction, user):
        '''Called when a message has a reaction added to it.'''
        log.debug(f'{sys._getframe().f_code.co_name} event triggered')
        plugins = await self.plugin_manager.plugins_for_server(reaction.message.server.id)

        for plugin in plugins.values():
            self.loop.create_task(plugin.on_reaction_add(reaction, user))

    async def on_reaction_remove(self, reaction, user):
        '''Called when a message has a reaction removed from it.'''
        log.debug(f'{sys._getframe().f_code.co_name} event triggered')
        plugins = await self.plugin_manager.plugins_for_server(reaction.message.server.id)

        for plugin in plugins.values():
            self.loop.create_task(plugin.on_reaction_remove(reaction, user))

    async def on_reaction_clear(self, message, reactions):
        '''Called when a message has all its reactions removed from it.'''
        log.debug(f'{sys._getframe().f_code.co_name} event triggered')
        plugins = await self.plugin_manager.plugins_for_server(message.server.id)

        for plugin in plugins.values():
            self.loop.create_task(plugin.on_rection_clear(message, reactions))

    async def on_channel_delete(self, channel):
        '''Called whenever a channel is removed from a server.'''
        log.debug(f'{sys._getframe().f_code.co_name} event triggered')
        plugins = await self.plugin_manager.plugins_for_server(channel.server.id)

        for plugin in  plugins:
            self.loop.create_task(plugin.on_channel_delete(channel))

    async def on_channel_create(self, channel):
        '''Called whenever a channel is added to a server.'''
        log.debug(f'{sys._getframe().f_code.co_name} event triggered')

        try:
            plugins = await self.plugin_manager.plugins_for_server(channel.server.id)
        except AttributeError:
            return

        for plugin in plugins.values():
            self.loop.create_task(plugin.on_channel_create(channel))

    async def on_channel_update(self, before, after):
        '''Called whenever a channel is updated.'''
        log.debug(f'{sys._getframe().f_code.co_name} event triggered')

        try:
            plugins = await self.plugin_manager.plugins_for_server(before.server.id)
        except AttributeError:
            return

        for plugin in plugins.values():
            self.loop.create_task(plugin.on_channel_update(before, after))

    async def on_member_join(self, member):
        '''Called when a member joins a server.'''
        log.debug(f'{sys._getframe().f_code.co_name} event triggered')
        plugins = await self.plugin_manager.plugins_for_server(member.server.id)

        for plugin in plugins.values():
            self.loop.create_task(plugin.on_member_join(member))

    async def on_member_remove(self, member):
        '''Called when a member leaves a server.'''
        log.debug(f'{sys._getframe().f_code.co_name} event triggered')
        plugins = await self.plugin_manager.plugins_for_server(member.server.id)

        for plugin in plugins.values():
            self.loop.create_task(plugin.on_member_remove(member))

    async def on_member_update(self, before, after):
        '''Called when a member updates their profile.'''
        log.debug(f'{sys._getframe().f_code.co_name} event triggered')
        plugins = await self.plugin_manager.plugins_for_server(before.server.id)

        for plugin in plugins.values():
            self.loop.create_task(plugin.on_member_update(before, after))

    async def on_server_join(self, server):
        '''Called when a server is either created by the client or when the client joins a server.'''
        log.debug(f'{sys._getframe().f_code.co_name} event triggered')

        await self._create_config(server.id)

        # Update global statistics
        await self.mongo.stats.update_one(
            {'scope': 'global'},
            {'$inc': {'num_guilds': 1}}
        )

        plugins = await self.plugin_manager.plugins_for_server(server.id)

        for plugin in plugins.values():
            self.loop.create_task(plugin.on_server_join(server))

    async def on_server_remove(self, server):
        '''Called when a server is removed from the client.'''
        log.debug(f'{sys._getframe().f_code.co_name} event triggered')
        plugins = await self.plugin_manager.plugins_for_server(server.id)

        for plugin in plugins.values():
            self.loop.create_task(plugin.on_server_remove(server))

    async def on_server_update(self, before, after):
        '''Called when a server updates.'''
        log.debug(f'{sys._getframe().f_code.co_name} event triggered')
        plugins = await self.plugin_manager.plugins_for_server(before.id)

        for plugin in plugins.values():
            self.loop.create_task(plugin.on_server_update(before, after))

    async def on_server_role_create(self, role):
        '''Called when a server creates a new role.'''
        log.debug(f'{sys._getframe().f_code.co_name} event triggered')
        plugins = await self.plugin_manager.plugins_for_server(role.server.id)

        for plugin in plugins.values():
            self.loop.create_task(plugin.on_server_role_create(role))

    async def on_server_role_delete(self, role):
        '''Called when a server deletes a role.'''
        log.debug(f'{sys._getframe().f_code.co_name} event triggered')
        plugins = await self.plugin_manager.plugins_for_server(role.server.id)

        for plugin in plugins.values():
            self.loop.create_task(plugin.on_server_role_delete(role))

    async def on_server_role_update(self, before, after):
        '''Called when a role is changed server-wide.'''
        log.debug(f'{sys._getframe().f_code.co_name} event triggered')
        plugins = await self.plugin_manager.plugins_for_server(before.server.id)

        for plugin in plugins.values():
            self.loop.create_task(plugin.on_server_role_update(before, after))

    async def on_server_emojis_update(self, before, after):
        '''Called when a server adds or removes Emoji.'''
        log.debug(f'{sys._getframe().f_code.co_name} event triggered')
        plugins = await self.plugin_manager.plugins_for_server(before.server.id)

        for plugin in plugins.values():
            self.loop.create_task(plugin.on_server_emojis_update(before, after))

    async def on_server_available(self, server):
        '''Called when a server becomes available.'''
        log.debug(f'{sys._getframe().f_code.co_name} event triggered')
        plugins = await self.plugin_manager.plugins_for_server(server.id)

        for plugin in plugins.values():
            self.loop.create_task(plugin.on_server_available(server))

    async def on_server_unavailable(self, server):
        '''Called when a server becomes unavailable.'''
        log.debug(f'{sys._getframe().f_code.co_name} event triggered')
        plugins = await self.plugin_manager.plugins_for_server(server.id)

        for plugin in plugins.values():
            self.loop.create_task(plugin.on_server_unavailable(server))

    async def on_voice_state_update(self, before, after):
        '''Called when a member changes their voice state.'''
        log.debug(f'{sys._getframe().f_code.co_name} event triggered')
        plugins = await self.plugin_manager.plugins_for_server(before.server.id)

        for plugin in plugins.values():
            self.loop.create_task(plugin.on_voice_state_update(before, after))

    async def on_member_ban(self, member):
        '''Called when a member gets banned from a server.'''
        log.debug(f'{sys._getframe().f_code.co_name} event triggered')
        plugins = await self.plugin_manager.plugins_for_server(member.server.id)

        for plugin in plugins.values():
            self.loop.create_task(plugin.on_member_ban(member))

    async def on_member_unban(self, server, user):
        '''Called when a user gets unbanned from a server.'''
        log.debug(f'{sys._getframe().f_code.co_name} event triggered')
        plugins = await self.plugin_manager.plugins_for_server(server.id)

        for plugin in plugins.values():
            self.loop.create_task(plugin.on_member_unban(server, user))

    async def on_typing(self, channel, user, when):
        '''Called when someone begins typing a message.'''
        log.debug(f'{sys._getframe().f_code.co_name} event triggered')
        plugins = await self.plugin_manager.plugins_for_server(channel.server.id)

        for plugin in plugins.values():
            self.loop.create_task(plugin.on_typing(channel, user, when))

    async def on_group_join(self, channel, user):
        '''Called when someone joins a group.'''
        log.debug(f'{sys._getframe().f_code.co_name} event triggered')
        plugins = await self.plugin_manager.plugins_for_server(channel.server.id)

        for plugin in plugins.values():
            self.loop.create_task(plugin.on_group_join(channel, user))

    async def on_group_remove(self, channel, user):
        '''Called when someone leaves a group.'''
        log.debug(f'{sys._getframe().f_code.co_name} event triggered')
        plugins = await self.plugin_manager.plugins_for_server(channel.server.id)

        for plugin in plugins.values():
            self.loop.create_task(plugin.on_group_remove(channel, user))
