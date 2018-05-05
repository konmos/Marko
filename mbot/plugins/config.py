import asyncio

from ..plugin import BasePlugin
from ..command import command


class ConfigPlugin(BasePlugin):
    '''
    Plugin which manages server-specific configurations.
    '''
    async def _set_prefix(self, server_id, prefix):
        ret = await self.mbot.mongo.config.update_one(
            {'server_id': server_id},
            {'$set': {'prefix': prefix}}
        )

        return bool(ret)

    async def _get_prefix(self, server_id):
        ret = await self.mbot.mongo.config.find_one({'server_id': server_id})['prefix']
        return ret

    async def _set_nsfw(self, server_id, channel_id):
        doc = await self.mbot.mongo.config.find_one({'server_id': server_id})

        # Already NSFW.
        if channel_id in doc['nsfw_channels']:
            return False

        ret = await self.mbot.mongo.config.update_one(
            {'server_id': server_id},
            {'$push': {'nsfw_channels': channel_id}}
        )

        return bool(ret)

    async def _set_sfw(self, server_id, channel_id):
        doc = await self.mbot.mongo.config.find_one({'server_id': server_id})

        # Already SFW.
        if channel_id not in doc['nsfw_channels']:
            return False

        ret = await self.mbot.mongo.config.update_one(
            {'server_id': server_id},
            {'$pull': {'nsfw_channels': channel_id}}
        )

        return bool(ret)

    @command(description='set this channel to nsfw', usage='nsfw')
    async def nsfw(self, message):
        ret = await self._set_nsfw(message.server.id, message.channel.id)

        if ret:
            await self.mbot.send_message(
                message.channel, f':ok_hand: **`#{message.channel.name}` is now set to NSFW!**', force=True
            )
        else:
            await self.mbot.send_message(
                message.channel, ':cry: **Channel appears to already be NSFW**', force=True
            )

    @command(description='set this channel to sfw', usage='sfw')
    async def sfw(self, message):
        ret = await self._set_sfw(message.server.id, message.channel.id)

        if ret:
            await self.mbot.send_message(
                message.channel, f':ok_hand: **`#{message.channel.name}` is no longer NSFW!**', force=True
            )
        else:
            await self.mbot.send_message(
                message.channel, ':cry: **Channel appears to already be SFW!**', force=True
            )

    @command(regex='^prefix (.*?)$', usage='prefix <prefix>', description='set the bot prefix for this server',
             name='prefix', perms=0x8)
    async def set_prefix(self, message, prefix):
        if prefix:
            ret = await self._set_prefix(message.server.id, prefix)

            if ret:
                await self.mbot.send_message(
                    message.channel, f':ok_hand: **Successfully updated prefix to `{prefix}`!**'
                )
            else:
                await self.mbot.send_message(
                    message.channel, ':cry: **Could not update prefix...**'
                )

    async def _ignore_channel(self, server_id, channel_id):
        doc = await self.mbot.mongo.config.find_one({'server_id': server_id})

        # Already ignored.
        if channel_id in doc['ignored_channels']:
            return False

        ret = await self.mbot.mongo.config.update_one(
            {'server_id': server_id},
            {'$push': {'ignored_channels': channel_id}}
        )

        return bool(ret)

    async def _unignore_channel(self, server_id, channel_id):
        ret = await self.mbot.mongo.config.update_one(
            {'server_id': server_id},
            {'$pull': {'ignored_channels': channel_id}}
        )

        return bool(ret)

    @command(description='ignore the current channel', usage='ignore', perms=0x8)
    async def ignore(self, message):
        ret = await self._ignore_channel(message.server.id, message.channel.id)

        if ret:
            await self.mbot.send_message(
                message.channel, f':ok_hand: **Now ignoring `#{message.channel.name}`!**', force=True
            )
        else:
            await self.mbot.send_message(
                message.channel, ':cry: **Channel appears to already be ignored!**', force=True
            )

    @command(description='unignore the current channel', usage='unignore', perms=0x8)
    async def unignore(self, message):
        ret = await self._unignore_channel(message.server.id, message.channel.id)

        if ret:
            await self.mbot.send_message(
                message.channel, f':ok_hand: **Not ignoring `#{message.channel.name}` anymore!**', force=True
            )
        else:
            await self.mbot.send_message(
                message.channel, ':cry: **Channel appears to not be ignored!**', force=True
            )

    async def disable_plugin(self, message):
        plugin = await self.mbot.wait_for_input(
            message,
            '**Enter the name of the plugin(s) you want to disable (separated by a comma);**'
        )

        if plugin and plugin.content:
            for p in plugin.content.split(','):
                p = p.strip()

                ret = await self.mbot.plugin_manager.disable_plugin(message.server.id, p)

                if ret:
                    await self.mbot.send_message(
                        message.channel, f':ok_hand: **Successfully disabled the *{p}* plugin!**'
                    )
                else:
                    await self.mbot.send_message(
                        message.channel, f':cry: **Could not disable the *{p}* plugin!**'
                    )

                await asyncio.sleep(1)
        else:
            await self.mbot.send_message(message.channel, f'{message.author.mention} **Exiting config menu...** :cry:')

    async def enable_plugin(self, message):
        plugin = await self.mbot.wait_for_input(
            message,
            '**Enter the name of the plugin(s) you want to enable (separated by a comma);**'
        )

        if plugin and plugin.content:
            for p in plugin.content.split(','):
                p = p.strip()

                ret = await self.mbot.plugin_manager.enable_plugin(message.server.id, p)

                if ret:
                    await self.mbot.send_message(
                        message.channel, f':ok_hand: **Successfully enabled the *{p}* plugin!**'
                    )
                else:
                    await self.mbot.send_message(
                        message.channel, f':cry: **Could not enable the *{p}* plugin!**'
                    )

                await asyncio.sleep(1)
        else:
            await self.mbot.send_message(message.channel, f'{message.author.mention} **Exiting config menu...** :cry:')

    async def enable_cmd(self, message):
        cmd = await self.mbot.wait_for_input(
            message,
            '**Enter the name of the command(s) you want to enable (separated by a comma);**'
        )

        if cmd and cmd.content:
            for c in cmd.content.split(','):
                c = c.strip()

                ret = await self.mbot.plugin_manager.enable_command(message.server.id, c, user_id=message.author.id)

                if ret:
                    await self.mbot.send_message(
                        message.channel, f':ok_hand: **Successfully enabled the *{c}* command!**'
                    )
                else:
                    await self.mbot.send_message(
                        message.channel, f':cry: **Could not enable the *{c}* command!**'
                    )

                await asyncio.sleep(1)
        else:
            await self.mbot.send_message(message.channel, f'{message.author.mention} **Exiting config menu...** :cry:')

    async def disable_cmd(self, message):
        cmd = await self.mbot.wait_for_input(
            message,
            '**Enter the name of the command(s) you want to disable (separated by a comma);**'
        )

        if cmd and cmd.content:
            for c in cmd.content.split(','):
                c = c.strip()

                ret = await self.mbot.plugin_manager.disable_command(message.server.id, c, user_id=message.author.id)

                if ret:
                    await self.mbot.send_message(
                        message.channel, f':ok_hand: **Successfully disabled the *{c}* command!**'
                    )
                else:
                    await self.mbot.send_message(
                        message.channel, f':cry: **Could not disable the *{c}* command!**'
                    )

                await asyncio.sleep(1)
        else:
            await self.mbot.send_message(message.channel, f'{message.author.mention} **Exiting config menu...** :cry:')

    @command(regex='^enable$', name='enable', perms=0x8, description='enable a plugin or command', usage='enable <ext>')
    async def enable_ext(self, message):
        option = await self.mbot.option_selector(
            message,
            '**Please enter a number corresponding to the type of extension you want to enable;**',
            {'plugin': 'Plugin', 'cmd': 'Command'}
        )

        if option is not None:
            if option == 'plugin':
                await self.enable_plugin(message)
            else:
                await self.enable_cmd(message)
        else:
            await self.mbot.send_message(message.channel, f'{message.author.mention} **Exiting config menu...** :cry:')

    @command(regex='^disable$', name='disable', perms=0x8, description='disable a plugin or command',
             usage='disable <ext>')
    async def disable_ext(self, message):
        option = await self.mbot.option_selector(
            message,
            '**Please enter a number corresponding to the type of extension you want to disable;**',
            {'plugin': 'Plugin', 'cmd': 'Command'}
        )

        if option is not None:
            if option == 'plugin':
                await self.disable_plugin(message)
            else:
                await self.disable_cmd(message)
        else:
            await self.mbot.send_message(message.channel, f'{message.author.mention} **Exiting config menu...** :cry:')
