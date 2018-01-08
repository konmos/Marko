from ..plugin import BasePlugin
from ..command import command


class ConfigPlugin(BasePlugin):
    '''
    Plugin which manages server-specific configurations.
    '''
    def _set_prefix(self, server_id, prefix):
        ret = self.mbot.mongo.config.update_one(
            {'server_id': server_id},
            {'$set': {'prefix': prefix}}
        )

        return bool(ret)

    def _get_prefix(self, server_id):
        return self.mbot.mongo.config.find_one({'server_id': server_id})['prefix']

    @command(regex='^prefix (.*?)$', usage='prefix <prefix>', description='set the bot prefix for this server',
             name='prefix', perms=0x8)
    async def set_prefix(self, message, prefix):
        if prefix:
            if self._set_prefix(message.server.id, prefix):
                await self.mbot.send_message(
                    message.channel, f':ok_hand: **Successfully updated prefix to `{prefix}`!**'
                )
            else:
                await self.mbot.send_message(
                    message.channel, ':cry: **Could not update prefix...**'
                )

    def _ignore_channel(self, server_id, channel_id):
        doc = self.mbot.mongo.config.find_one({'server_id': server_id})

        # Already ignored.
        if channel_id in doc['ignored_channels']:
            return False

        ret = self.mbot.mongo.config.update_one(
            {'server_id': server_id},
            {'$push': {'ignored_channels': channel_id}}
        )

        return bool(ret)

    def _unignore_channel(self, server_id, channel_id):
        ret = self.mbot.mongo.config.update_one(
            {'server_id': server_id},
            {'$pull': {'ignored_channels': channel_id}}
        )

        return bool(ret)

    @command(description='ignore the current channel', usage='ignore', perms=0x8)
    async def ignore(self, message):
        if self._ignore_channel(message.server.id, message.channel.id):
            await self.mbot.send_message(
                message.channel, f':ok_hand: **Now ignoring `#{message.channel.name}`!**', force=True
            )
        else:
            await self.mbot.send_message(
                message.channel, ':cry: **Channel appears to already be ignored!**', force=True
            )

    @command(description='unignore the current channel', usage='unignore', perms=0x8)
    async def unignore(self, message):
        if self._unignore_channel(message.server.id, message.channel.id):
            await self.mbot.send_message(
                message.channel, f':ok_hand: **Not ignoring `#{message.channel.name}` anymore!**', force=True
            )
        else:
            await self.mbot.send_message(
                message.channel, ':cry: **Channel appears to not be ignored!**', force=True
            )

    @command(su=True, description='reload all plugins and commands globally', usage='reload')
    async def reload(self, message):
        with await self.mbot.plugin_manager.lock:
            await self.mbot.plugin_manager.reload_plugins()
            await self.mbot.send_message(
                message.channel, f':ok_hand: **Successfully reloaded all plugins!**'
            )

    async def disable_plugin(self, message):
        m = await self.mbot.send_message(message.channel, '*Enter the name of the plugin you want to disable...*')

        plugin = await self.mbot.wait_for_message(
            author=message.author, channel=message.channel, timeout=30
        )

        if plugin.content:
            ret = await self.mbot.plugin_manager.disable_plugin(message.server.id, plugin.content)

            if ret:
                await self.mbot.send_message(
                    message.channel, f':ok_hand: **Successfully disabled the *{plugin.content}* plugin!**'
                )
            else:
                await self.mbot.send_message(
                    message.channel, f':cry: **Could not disable the *{plugin.content}* plugin!**'
                )

            await self.mbot.delete_message(m)

    async def enable_plugin(self, message):
        m = await self.mbot.send_message(message.channel, '*Enter the name of the plugin you want to enable...*')

        plugin = await self.mbot.wait_for_message(
            author=message.author, channel=message.channel, timeout=30
        )

        if plugin.content:
            ret = await self.mbot.plugin_manager.enable_plugin(message.server.id, plugin.content)

            if ret:
                await self.mbot.send_message(
                    message.channel, f':ok_hand: **Successfully enabled the *{plugin.content}* plugin!**'
                )
            else:
                await self.mbot.send_message(
                    message.channel, f':cry: **Could not enable the *{plugin.content}* plugin!**'
                )

            await self.mbot.delete_message(m)

    async def enable_cmd(self, message):
        m = await self.mbot.send_message(message.channel, '*Enter the name of the command you want to enable...*')

        cmd = await self.mbot.wait_for_message(
            author=message.author, channel=message.channel, timeout=30
        )

        if cmd.content:
            ret = await self.mbot.plugin_manager.enable_command(message.server.id, cmd.content)

            if ret:
                await self.mbot.send_message(
                    message.channel, f':ok_hand: **Successfully enabled the *{cmd.content}* command!**'
                )
            else:
                await self.mbot.send_message(
                    message.channel, f':cry: **Could not enable the *{cmd.content}* command!**'
                )

            await self.mbot.delete_message(m)

    async def disable_cmd(self, message):
        m = await self.mbot.send_message(message.channel, '*Enter the name of the command you want to disable...*')

        cmd = await self.mbot.wait_for_message(
            author=message.author, channel=message.channel, timeout=30
        )

        if cmd.content:
            ret = await self.mbot.plugin_manager.disable_command(message.server.id, cmd.content)

            if ret:
                await self.mbot.send_message(
                    message.channel, f':ok_hand: **Successfully disabled the *{cmd.content}* command!**'
                )
            else:
                await self.mbot.send_message(
                    message.channel, f':cry: **Could not disable the *{cmd.content}* command!**'
                )

            await self.mbot.delete_message(m)

    @command(regex='^enable$', name='enable', perms=0x8, description='enable a plugin or command', usage='enable <ext>')
    async def enable_ext(self, message):
        with await self.mbot.plugin_manager.lock:
            resp = '''*Please enter a number corresponding to the type of extension you want to enable...*
            ```
            [1] Plugin
            [2] Command```'''.strip('\t')

            await self.mbot.send_message(message.channel, resp)

            choice = await self.mbot.wait_for_message(
                author=message.author, channel=message.channel,
                timeout=30, check=lambda msg: msg.content.isdigit()
            )

            if choice.content in ['1', '2']:
                if choice.content == '1':
                    await self.enable_plugin(message)
                else:
                    await self.enable_cmd(message)
            else:
                await self.mbot.send_message(message.channel, f'{message.author.mention} *Try again...* :cry:')

    @command(regex='^disable', name='disable', perms=0x8, description='disable a plugin or command',
             usage='disable <ext>')
    async def disable_ext(self, message):
        with await self.mbot.plugin_manager.lock:
            resp = '''*Please enter a number corresponding to the type of extension you want to disable...*
                ```
                [1] Plugin
                [2] Command```'''.strip('\t')

            await self.mbot.send_message(message.channel, resp)

            choice = await self.mbot.wait_for_message(
                author=message.author, channel=message.channel,
                timeout=30, check=lambda msg: msg.content.isdigit()
            )

            if choice.content in ['1', '2']:
                if choice.content == '1':
                    await self.disable_plugin(message)
                else:
                    await self.disable_cmd(message)
            else:
                await self.mbot.send_message(message.channel, f'{message.author.mention} *Try again...* :cry:')
