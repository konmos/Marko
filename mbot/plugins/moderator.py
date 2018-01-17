from ..plugin import BasePlugin
from ..command import command


class Moderator(BasePlugin):
    async def _purge(self, message, limit=100, check=None):
        if limit is not None:
            limit = int(limit)

            if limit > 100:
                limit = 100
        else:
            limit = 100

        deleted = await self.mbot.purge_from(message.channel, limit=limit, check=check)
        await self.mbot.send_message(
            message.channel, f'**{message.author.mention} Deleted {len(deleted)} message(s).**'
        )

    @command(regex='^purge(?: (\d*?))?$', description='purge the channel', usage='purge [limit]',
             perms=8192, cooldown=5)
    async def purge(self, message, limit=100):
        await self._purge(message, limit)

    @command(regex='^purge users .*?(?: (\d*?))?$', description='purge messages created by certain users',
             usage='purge users <user mentions...> [limit]', perms=8192, cooldown=5, name='purge users')
    async def purge_users(self, message, limit=100):
        await self._purge(message, limit, check=lambda msg: msg.author in message.mentions)

    @command(regex='^purge bots(?: (\d*?))?$', description='purge bot messages', usage='purge bots [limit]',
             perms=8192, cooldown=5, name='purge bots')
    async def purge_bot(self, message, limit=None):
        await self._purge(message, limit, check=lambda m: m.author.bot)

    @command(regex='^purge match (.*?)(?: (\d*?))?$', description='purge messages that match a string exactly',
             usage='purge match <string> [limit]', perms=8192, cooldown=5, name='purge match')
    async def purge_match(self, message, string, limit=None):
        await self._purge(message, limit, check=lambda m: m.content == string)

    @command(regex='^purge contains (.*?)(?: (\d*?))?$', description='purge messages that contain a string',
             usage='purge contains <string> [limit]', perms=8192, cooldown=5, name='purge contains')
    async def purge_contains(self, message, string, limit=None):
        await self._purge(message, limit, check=lambda m: string in m.content)

    @command(regex='^purge not (.*?)(?: (\d*?))?$', description='purge messages that do not contain a string',
             usage='purge not <string> [limit]', perms=8192, cooldown=5, name='purge not')
    async def purge_not(self, message, string, limit=None):
        await self._purge(message, limit, check=lambda m: string not in m.content)

    @command(regex='^purge starts (.*?)(?: (\d*?))?$', description='purge messages that start with a string',
             usage='purge starts <string> [limit]', perms=8192, cooldown=5, name='purge starts')
    async def purge_starts(self, message, string, limit=None):
        await self._purge(message, limit, check=lambda m: m.content.startswith(string))

    @command(regex='^purge ends (.*?)(?: (\d*?))?$', description='purge messages that end with a string',
             usage='purge ends <string> [limit]', perms=8192, cooldown=5, name='purge ends')
    async def purge_ends(self, message, string, limit=None):
        await self._purge(message, limit, check=lambda m: m.content.endswith(string))

    @command(regex='^purge embeds(?: (\d*?))?$', description='purge messages that contain embeds',
             usage='purge embeds [limit]', perms=8192, cooldown=5, name='purge embeds')
    async def purge_embeds(self, message, limit=None):
        await self._purge(message, limit, check=lambda m: m.embeds)

    @command(regex='^purge mentions(?: (\d*?))?$', description='purge messages that contain mentions',
             usage='purge mentions [limit]', perms=8192, cooldown=5, name='purge mentions')
    async def purge_mentions(self, message, limit=None):
        await self._purge(message, limit, check=lambda m: m.mentions)
