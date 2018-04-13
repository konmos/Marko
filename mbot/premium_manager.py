import uuid
import time
import random
import datetime

import asyncio
from dateutil.relativedelta import relativedelta
from discord import Forbidden


DEFAULT_KEY_NOTES = (
    'key made just for you <3',
    'key forged in the finest Mahakaman workshop',
    'a key fit for Marko himself',
    'thanks for your support! <3'
)


class KeyUsageExceeded(Exception):
    '''Raised when we attempt to exceed the max number of uses for a key.'''


class KeyExpired(Exception):
    '''Raised when we try to use an expired key.'''


class InvalidKey(Exception):
    '''Raised when we try to use a key which does not exist.'''


class KeyUnauthorised(Exception):
    '''Raised when an unauthorised user tries to redeem a key.'''


def calculate_expire_time(start_time, months=0, days=0):
    date = datetime.date.fromtimestamp(start_time)
    new_date = date + relativedelta(months=months, days=days)

    return time.mktime(new_date.timetuple())


class Key(object):
    '''
    Data class used to represent an upgrade key.
    '''
    def __init__(self, **key_data):
        self.key = key_data.get('key') or str(uuid.uuid4())
        self.ttl = int(key_data.get('ttl') or -1)
        self.time_generated = key_data.get('time_generated') or time.time()
        self.generated_by = key_data.get('generated_by')
        self.key_type = key_data.get('key_type') or '1-month'
        self.authorised_users = key_data.get('authorised_users') or []
        self.max_uses = int(key_data.get('max_uses') or 1)
        self.key_note = key_data.get('key_note') or random.choice(DEFAULT_KEY_NOTES)
        self.usage = key_data.get('usage') or []
        self.reserved_uses = key_data.get('reserved_uses') or []

    @property
    def uses_remaining(self):
        return self.max_uses - (len(self.usage) + len(self.reserved_uses))

    @property
    def expires(self):
        return self.time_generated + self.ttl if self.ttl != -1 else -1

    @property
    def expired(self):
        return self.uses_remaining <= 0 or self.expires < time.time() if self.expires != -1 else False

    @property
    def readable_type(self):
        return f'Marko Premium - {self.key_type.replace("-", " ").title()}'

    @property
    def key_data(self):
        return {
            'key': self.key,
            'ttl': self.ttl,
            'time_generated': self.time_generated,
            'generated_by': self.generated_by,
            'key_type': self.key_type,
            'authorised_users': self.authorised_users,
            'max_uses': self.max_uses,
            'key_note': self.key_note,
            'usage': self.usage,
            'reserved_uses': self.reserved_uses
        }

    def _check_key(self, user_id=None):
        if self.uses_remaining <= 0:
            raise KeyUsageExceeded

        if self.expired:
            raise KeyExpired

        if user_id is not None:
            if self.authorised_users and user_id not in self.authorised_users:
                raise KeyUnauthorised

    def _redeem_key(self, user_id, server_id):
        key_id = len(self.usage)

        self.usage.append({
            'key_id': key_id,
            'server_id': server_id,
            'user_id': user_id,
            'timestamp': time.time()
        })

        return key_id

    def redeem_key(self, user_id, server_id):
        self._check_key(user_id)
        return self._redeem_key(user_id, server_id)

    def reserve_key(self, user_id, server_id):
        self._check_key(user_id)

        self.reserved_uses.append({
            'user_id': user_id,
            'server_id': server_id
        })

    def redeem_from_reserve(self, user_id, server_id):
        for data in self.reserved_uses:
            if data['user_id'] == user_id and data['server_id'] == server_id:
                break
        else:
            return

        self.reserved_uses.remove(data)
        return self._redeem_key(data['user_id'], data['server_id'])


class PremiumGuild(object):
    '''
    Data class to represent a premium guild.
    '''
    def __init__(self, guild_id, key, key_id=0, expires=None, key_history=None):
        self.guild_id = guild_id

        self.key = key
        self.key_id = int(key_id)
        self.key_history = key_history
        self.expires = expires or self._calculate_expire_time()

    def _calculate_expire_time(self):
        if self.key.key_type == 'lifetime':
            return -1

        upgrade = self.key.key_type.split('-')

        if upgrade[1] in ['month', 'months']:
            return calculate_expire_time(self.time_upgraded, months=int(upgrade[0]))
        elif upgrade[1] in ['day', 'days']:
            return calculate_expire_time(self.time_upgraded, days=int(upgrade[0]))

    @property
    def upgraded_by(self):
        _keys = {k['key_id']: {'user_id': k['user_id'], 'timestamp': k['timestamp']} for k in self.key.usage}
        return _keys.get(self.key_id, {}).get('user_id')

    @property
    def time_upgraded(self):
        _keys = {k['key_id']: {'user_id': k['user_id'], 'timestamp': k['timestamp']} for k in self.key.usage}
        return _keys.get(self.key_id, {}).get('timestamp')

    @property
    def expired(self):
        return self.expires < time.time() if self.expires != -1 else False

    @property
    def guild_data(self):
        return {
            'key': f'{self.key.key}#{self.key_id}',
            'server_id': self.guild_id,
            'expires': self.expires
        }


class PremiumManager(object):
    def __init__(self, mbot):
        self.mbot = mbot

        self.keys_db = self.mbot.mongo.bot_data.premium_keys
        self.guilds_db = self.mbot.mongo.bot_data.premium_guilds

    async def get_reserved_keys(self, server_id):
        keys = []

        async for document in self.keys_db.find({'reserved_uses': {'$elemMatch': {'server_id': server_id}}}):
            keys.append(Key(**document))

        return keys

    async def get_key_history(self, server_id):
        keys = []

        async for document in self.keys_db.find({'usage': {'$elemMatch': {'server_id': server_id}}}):
            keys.append(Key(**document))

        return keys

    async def get_guild(self, server_id):
        doc = await self.guilds_db.find_one({'server_id': server_id})

        if doc:
            key, key_id = doc['key'].split('#')
            key_data = await self.keys_db.find_one({'key': key})
            key_history = await self.get_key_history(server_id)

            return PremiumGuild(server_id, Key(**key_data), key_id, doc['expires'], key_history)

    async def generate_key(self, user_id=None, max_uses=1, note=None, authorised_users=None, key_type=None, ttl=None):
        app_info = await self.mbot.application_info()

        key = Key(
            generated_by=user_id or app_info.owner.id,
            authorised_users=authorised_users,
            key_note=note,
            key_type=key_type,
            max_uses=max_uses,
            ttl=ttl
        )

        await self.keys_db.insert_one(key.key_data)
        return key

    async def is_key_valid(self, key):
        key_data = await self.keys_db.find_one({'key': key})

        if key_data:
            key_obj = Key(**key_data)

            if not key_obj.expired:
                return True

        return False

    async def get_key(self, key):
        key_data = await self.keys_db.find_one({'key': key})

        if key_data:
            return Key(**key_data)

    async def upgrade_guild(self, server_id, user_id, key):
        key_data = await self.keys_db.find_one({'key': key})

        if key_data:
            key_obj = Key(**key_data)
            key_id = key_obj.redeem_key(user_id, server_id)
            guild = PremiumGuild(server_id, key_obj, key_id)

            data = key_obj.key_data
            data.pop('key')

            await self.keys_db.update_one(
                {'key': key},
                {'$set': data},
                upsert=True
            )

            await self.guilds_db.update_one(
                {'server_id': server_id},
                {'$set': guild.guild_data},
                upsert=True
            )
        else:
            raise InvalidKey

    async def is_guild_premium(self, server_id):
        guild = await self.get_guild(server_id)

        if guild:
            return not guild.expired

        return False
