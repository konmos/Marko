from ..plugin import BasePlugin
from ..command import command


class AyyBot(BasePlugin):
    '''ayy'''
    @command(regex='^ayy+$', description='ayy', usage='ayy')
    async def ayy(self, message):
        await self.mbot.send_message(message.channel, '*lmao*')
