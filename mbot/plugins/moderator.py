import time

from discord import Forbidden, NotFound, HTTPException

from ..plugin import BasePlugin
from ..command import command


class Moderator(BasePlugin):
    def __init__(self, mbot):
        super().__init__(mbot)

        self.db = self.mbot.mongo.plugin_data.moderator

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

    async def _create_blacklist(self, server_id, strings=None, users=None):
        doc = await self.db.find_one({'server_id': server_id})

        if not doc:
            ret = await self.db.insert_one(
                {
                    'server_id': server_id,
                    'strings_blacklist': strings or [],
                    'users_blacklist': users or []
                }
            )

            return ret

    async def get_strings_blacklist(self, server_id):
        doc = await self.db.find_one({'server_id': server_id})

        if doc:
            return doc['strings_blacklist']
        else:
            return []

    async def is_user_blacklisted(self, user_id, server_id):
        q = await self.db.find_one(
            {'server_id': server_id, 'users_blacklist': {'$elemMatch': {'user_id': user_id}}}
        )

        if q is not None:
            return True

        return False

    async def blacklist_user(self, server_id, user_id, reason):
        doc = await self.db.find_one({'server_id': server_id})

        if not doc:
            ret = await self._create_blacklist(
                server_id, users=[{'user_id': user_id, 'reason': reason, 'timestamp': time.time()}]
            )

            return bool(ret)
        else:
            ret = await self.db.update_one(
                {'server_id': server_id, 'users_blacklist': {'$ne': {'user_id': user_id}}},
                {'$push': {'users_blacklist': {'user_id': user_id, 'reason': reason, 'timestamp': time.time()}}}
            )

            return ret.modified_count == 1

    async def whitelist_user(self, server_id, user_id):
        doc = await self.db.find_one({'server_id': server_id})

        if not doc:
            await self._create_blacklist(server_id)
            return False
        else:
            ret = await self.db.update_one(
                {'server_id': server_id},
                {'$pull': {'users_blacklist': {'user_id': user_id}}}
            )

            return ret.modified_count == 1

    async def blacklist_string(self, server_id, string):
        doc = await self.db.find_one({'server_id': server_id})

        if not doc:
            ret = await self._create_blacklist(server_id, strings=[string])
            return bool(ret)
        else:
            if string not in doc['strings_blacklist']:
                ret = await self.db.update_one(
                    {'server_id': server_id},
                    {'$push': {'strings_blacklist': string}}
                )

                return ret.modified_count == 1

    async def whitelist_string(self, server_id, string):
        doc = await self.db.find_one({'server_id': server_id})

        if not doc:
            await self._create_blacklist(server_id)
            return False
        else:
            ret = await self.db.update_one(
                {'server_id': server_id},
                {'$pull': {'strings_blacklist': string}}
            )

            return ret.modified_count == 1

    async def on_message(self, message):
        blist = await self.get_strings_blacklist(message.server.id)

        if blist and any([s and s in message.content for s in blist]):
            await self.mbot.send_message(
                message.author,
                f'Your message *(snippet: `{message.content[:300]}`)* was filtered by the blacklist in '
                f'the server `{message.server.name}`! :angry:'
            )

            try:
                await self.mbot.delete_message(message)
            except Forbidden:
                pass

    @command(regex='^blacklist string (.*?)$', usage='blacklist string <string>',
             description='blacklist string(s) or url(s)', perms=8, name='blacklist string')
    async def blacklist_string_cmd(self, message, string):
        ret = await self.blacklist_string(message.server.id, string)

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

    @command(regex='^whitelist string (.*?)$', usage='whitelist string <string>',
             description='whitelist string(s) or url(s)', perms=8, name='whitelist string')
    async def whitelist_string_cmd(self, message, string):
        ret = await self.whitelist_string(message.server.id, string)

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

    @command(regex='^blacklist user (\d+) (.*?)$', usage='blacklist user <user_id> <reason>',
             description='blacklist a user by their ID', perms=8, name='blacklist user')
    async def blacklist_user_cmd(self, message, user_id, reason):
        try:
            user = await self.mbot.get_user_info(user_id)
        except (NotFound, HTTPException):
            return await self.mbot.send_message(
                message.channel,
                '**This user does not exist!**'
            )

        ret = await self.blacklist_user(message.server.id, user_id, reason)

        if ret:
            await self.mbot.send_message(
                message.channel,
                f':ok_hand: **Successfully blacklisted the user `{user_id}`!**'
            )

            await self.mbot.send_message(
                user,
                f'You have been blacklisted in the server `{message.server.name}`.\n'
                f'The reason for this was `{reason}`.'
            )
        else:
            await self.mbot.send_message(
                message.channel,
                f':cry: **Could not blacklist the user `{user_id}`!**'
            )

    @command(regex='^whitelist user (.*?)$', usage='whitelist user <user_id>',
             description='whitelist a user', perms=8, name='whitelist user')
    async def whitelist_user_cmd(self, message, user_id):
        ret = await self.whitelist_user(message.server.id, user_id)

        if ret:
            await self.mbot.send_message(
                message.channel,
                f':ok_hand: **Successfully whitelisted the user `{user_id}`!**'
            )

            try:
                user = await self.mbot.get_user_info(user_id)

                await self.mbot.send_message(
                    user,
                    f'You have been removed from the blacklist in the server `{message.server.name}`.'
                )
            except (NotFound, HTTPException):
                return
        else:
            await self.mbot.send_message(
                message.channel,
                f':cry: **Could not whitelist the user `{user_id}`!**'
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
