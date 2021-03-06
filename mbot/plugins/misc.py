from ..plugin import BasePlugin
from ..command import command


class Miscellaneous(BasePlugin):
    @command(regex='^ayy+$', description='ayy', usage='ayy')
    async def ayy(self, message):
        await self.mbot.send_message(message.channel, '*lmao*')

    @command(regex='^cmd-plugin (.*?)$', name='cmd-plugin')
    async def plugin_for_cmd(self, message, cmd):
        plugin = self.mbot.plugin_manager.plugin_for_cmd(cmd, False)

        if plugin:
            return await self.mbot.send_message(
                message.channel,
                f'**The plugin for `{cmd}` is `{plugin}`.**'
            )

        return await self.mbot.send_message(
                message.channel,
                f'**I could not find that command...**'
            )

    @command(regex='^regex (.*?)$')
    async def regex(self, message, string):
        cmd = self.mbot.plugin_manager.command_from_string(string, False)

        if cmd:
            return await self.mbot.send_message(
                message.channel,
                f'`{cmd._pattern.pattern}`'
            )

        return await self.mbot.send_message(
            message.channel,
            f'**I could not find that command...**'
        )
