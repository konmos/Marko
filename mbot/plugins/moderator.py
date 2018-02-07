from discord import Forbidden

from ..plugin import BasePlugin
from ..command import command
from ..utils import long_running_task


class Moderator(BasePlugin):
    def __init__(self, mbot):
        super().__init__(mbot)

        self.blacklist_db = None

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

    async def on_ready(self):
        self.blacklist_db = self.mbot.mongo.plugin_data.blacklist

    async def _create_blacklist(self, server_id, strings=None):
        doc = await self.blacklist_db.find_one({'server_id': server_id})

        if not doc:
            ret = await self.blacklist_db.insert_one(
                {
                    'server_id': server_id,
                    'blacklist': strings or []
                }
            )

            return ret

    async def get_blacklist(self, server_id):
        doc = await self.blacklist_db.find_one({'server_id': server_id})

        if doc:
            return doc['blacklist']
        else:
            return []

    async def add_to_blacklist(self, server_id, string):
        doc = await self.blacklist_db.find_one({'server_id': server_id})

        if not doc:
            ret = await self._create_blacklist(server_id, [string])
        else:
            ret = await self.blacklist_db.update_one(
                {'server_id': server_id},
                {'$push': {'blacklist': string}}
            )

        return bool(ret)

    async def remove_from_blacklist(self, server_id, string):
        doc = await self.blacklist_db.find_one({'server_id': server_id})

        if not doc:
            ret = await self._create_blacklist(server_id, [string])
        else:
            ret = await self.blacklist_db.update_one(
                {'server_id': server_id},
                {'$pull': {'blacklist': string}}
            )

        return bool(ret)

    async def on_message(self, message):
        blist = await self.get_blacklist(message.server.id)

        if blist and any([s and s in message.content for s in blist]):
            await self.mbot.send_message(
                message.channel,
                f'{message.author.mention} :scream: **You cannot say that!**'
            )

            try:
                await self.mbot.delete_message(message)
            except Forbidden:
                pass

    @command(regex='^blacklist (.*?)$', usage='blacklist <string2;string1...>',
             description='blacklist string(s) or url(s)', perms=8)
    async def blacklist(self, message, string):
        ret = await self.add_to_blacklist(message.server.id, string)

        if ret:
            await self.mbot.send_message(
                message.channel,
                f':ok_hand: **Successfully blacklisted `{string}`!**'
            )
        else:
            await self.mbot.send_message(
                message.channel,
                f':cry: **Could not blacklist `{string}`!**'
            )

    @command(regex='^whitelist (.*?)$', usage='whitelist <string2;string1...>',
             description='whitelist string(s) or url(s)', perms=8)
    async def whitelist(self, message, string):
        ret = await self.remove_from_blacklist(message.server.id, string)

        if ret:
            await self.mbot.send_message(
                message.channel,
                f':ok_hand: **Successfully whitelisted `{string}`!**'
            )
        else:
            await self.mbot.send_message(
                message.channel,
                f':cry: **Could not whitelist `{string}`!**'
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
