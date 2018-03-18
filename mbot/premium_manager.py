import uuid
import time
import datetime
import calendar


class KeyUsageExceeded(Exception):
    '''Raised when we attempt to exceed the max number of uses for a key.'''


class KeyExpired(Exception):
    '''Raised when we try to use an expired key.'''


class InvalidKey(Exception):
    '''Raised when we try to use a key which does not exist.'''


def calculate_expire_time(start_time, months):
    date = datetime.date.fromtimestamp(start_time)

    month = date.month - 1 + months
    year = date.year + month // 12
    month = month % 12 + 1
    day = min(date.day, calendar.monthrange(year, month)[1])

    return time.mktime(datetime.date(year, month, day).timetuple())


class Key(object):
    def __init__(self, **key_data):
        self.key = key_data.get('key', str(uuid.uuid4()))
        self.ttl = key_data.get('ttl', 24*60*60*5)
        self.time_generated = key_data.get('time_generated', time.time())
        self.generated_by = key_data.get('generated_by')
        self.expires = key_data.get('expires')
        self.key_type = key_data.get('key_type', 'pro-1')
        self.authorised_users = key_data.get('authorised_users', [])
        self.max_uses = key_data.get('max_uses', 1)
        self.uses_remaining = key_data.get('uses_remaining', 1)
        self.key_note = key_data.get('key_note', '')
        self.usage = key_data.get('usage', [])

        self._update_expire_time()
        self._update_uses_remaining()

    @property
    def expired(self):
        return self.uses_remaining <= 0 or self.expires < time.time()

    @property
    def key_data(self):
        return {
            'key': self.key,
            'ttl': self.ttl,
            'time_generated': self.time_generated,
            'generated_by': self.generated_by,
            'expires': self.expires,
            'key_type': self.key_type,
            'authorised_users': self.authorised_users,
            'max_uses': self.max_uses,
            'uses_remaining': self.uses_remaining,
            'key_note': self.key_note,
            'usage': self.usage
        }

    def _update_uses_remaining(self):
        self.uses_remaining = self.max_uses - len(self.usage)

    def _update_expire_time(self):
        self.expires = self.time_generated + self.ttl

    def add_authorised_user(self, user):
        if user not in self.authorised_users:
            self.authorised_users.append(user)

    def remove_authorised_user(self, user):
        if user in self.authorised_users:
            self.authorised_users.remove(user)

    def update_max_uses(self, update_by):
        self.max_uses += update_by
        self._update_uses_remaining()

    def set_max_uses(self, value):
        self.max_uses = value
        self._update_uses_remaining()

    def set_key_note(self, note):
        self.key_note = note

    def redeem_key(self, user_id, server_id):
        if self.uses_remaining <= 0:
            raise KeyUsageExceeded

        if self.expired:
            raise KeyExpired

        key_id = len(self.usage)

        self.usage.append({
            'key_id': key_id,
            'server_id': server_id,
            'user_id': user_id,
            'timestamp': time.time()
        })

        self._update_uses_remaining()
        return key_id


class PremiumGuild(object):
    def __init__(self, guild_id, key, key_id=0):
        self.key = key
        self.guild_id = guild_id
        self.key_id = int(key_id)

    @property
    def upgraded_by(self):
        _keys = {k['key_id']: {'user_id': k['user_id'], 'timestamp': k['timestamp']} for k in self.key.usage}
        return _keys.get(self.key_id, {}).get('user_id')

    @property
    def time_upgraded(self):
        _keys = {k['key_id']: {'user_id': k['user_id'], 'timestamp': k['timestamp']} for k in self.key.usage}
        return _keys.get(self.key_id, {}).get('timestamp', 0)

    @property
    def expires(self):
        upgrade_len = self.key.key_type[-1]
        return calculate_expire_time(self.time_upgraded, int(upgrade_len)) if not upgrade_len == 'i' else -1

    @property
    def expired(self):
        return self.expires < time.time()

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

    async def get_guild(self, server_id):
        doc = await self.guilds_db.find_one({'server_id': server_id})

        if doc:
            key, key_id = doc['key'].split('#')
            key_data = await self.keys_db.find_one({'key': key})

            return PremiumGuild(server_id, Key(**key_data), key_id)

    async def generate_key(self, user_id=None, max_uses=1, note=None, authorised_users=None, key_type=None):
        app_info = await self.mbot.application_info()

        key = Key(
            generated_by=user_id or app_info.owner.id,
            authorised_users=authorised_users or [],
            key_note=note or '',
            key_type=key_type or 'pro-1',
            max_uses=max_uses
        )

        await self.keys_db.insert_one(key.key_data)

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
