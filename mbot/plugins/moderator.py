from ..plugin import BasePlugin
from ..command import command


class Moderator(BasePlugin):
    @command(regex='^purge (\d*?)$', description='delete a number of messages', usage='purge <limit>', perms=0x2000)
    async def purge(self, message, limit):
        limit = int(limit)
        if limit > 100:
            limit = 100

        deleted = await self.mbot.purge_from(message.channel, limit=limit)
        await self.mbot.send_message(message.channel, f'*Deleted {len(deleted)} message(s).*')
