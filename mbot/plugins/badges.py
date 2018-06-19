import time
import random

from .badge_data import BADGE_DATA, BADGE_MAP
from ..plugin import BasePlugin
from ..command import command
from ..utils import human_time


PLAYTIME_RESET = 24 * 60 * 60
DAILY_CAP = 2 * 60 * 60


class Badges(BasePlugin):
    def __init__(self, mbot):
        super().__init__(mbot)

        self.badges_db = self.mbot.mongo.plugin_data.badges

    @staticmethod
    def badge_for_game(game_name):
        return BADGE_DATA.get(BADGE_MAP.get(game_name))

    @staticmethod
    def _default_doc(user_id):
        return {
            'user_id': user_id,
            'total_playtime': 0,
            'hit_cap': 0,
            'fragments': [],  # [{"badge_id": ..., "standard": ..., "foil": ...}, ...]
            'now_playing': {
                'game': None,
                'started_playing': None
            },
            'inventory': []
        }

    async def drop_rewards(self, user_id, badge_id, seconds_played):
        await self.badges_db.update_one(
            {'user_id': user_id, 'fragments.badge_id': {'$ne': badge_id}},
            {'$push': {'fragments': {'badge_id': badge_id, 'standard': 0, 'foil': 0}}}
        )

        minutes_played = int(seconds_played / 60)
        fragments, foil_fragments = 0, 0

        for _ in range(minutes_played):
            # 1% chance to be rewarded a foil fragment.
            if random.randrange(1, 101) == random.randrange(1, 101):
                foil_fragments += 1
            else:
                fragments += 1

        await self.badges_db.update_one(
            {'user_id': user_id, 'fragments': {'$elemMatch': {'badge_id': badge_id}}},
            {'$inc': {'fragments.$.standard': fragments, 'fragments.$.foil': foil_fragments}}
        )

    async def get_member_info(self, user_id):
        doc = await self.badges_db.find_one({'user_id': user_id})

        if not doc:
            default = self._default_doc(user_id)
            await self.badges_db.insert_one(default)
            return default

        return doc

    async def on_member_update(self, before, after):
        if after.bot:
            return

        try:
            new_game = after.game.name
        except AttributeError:
            new_game = None

        try:
            old_game = before.game.name
        except AttributeError:
            old_game = None

        if new_game == old_game:
            return

        tstamp = time.time()
        doc = await self.get_member_info(after.id)

        now_playing = doc['now_playing']

        await self.badges_db.update_one(
            {'user_id': after.id},
            {'$set': {'now_playing': {'game': new_game or None, 'started_playing': tstamp if new_game else None}}}
        )

        if now_playing['game'] is not None and now_playing['game'] == old_game and now_playing['game'] in BADGE_MAP:
            playtime = tstamp - now_playing['started_playing']

            # We make sure that the total playtime has not exceeded the cap and that there has been
            # a period of at least 24 hours since the last time that the cap was hit.
            if doc['total_playtime'] < DAILY_CAP and doc['hit_cap'] + PLAYTIME_RESET <= tstamp:
                # Player has hit the daily cap of 2 hours of playtime
                if doc['total_playtime'] + playtime > DAILY_CAP:
                    reward = DAILY_CAP - doc['total_playtime']

                    # Reset the playtime, and update the timestamp of reaching the cap.
                    # NO more rewards will be given for a period of 24 hours.
                    # ALSO, the playtime does not rollover if you play past the 24 hour cooldown, ie.
                    # the game must be started AFTER the 24 hour cooldown has elapsed to be given rewards.
                    await self.badges_db.update_one(
                        {'user_id': after.id},
                        {'$set': {'hit_cap': tstamp, 'playtime': 0}}
                    )
                else:
                    reward = playtime

                    await self.badges_db.update_one(
                        {'user_id': after.id},
                        {'$inc': {'total_playtime': playtime}}
                    )

                self.mbot.loop.create_task(self.drop_rewards(
                    doc['user_id'],
                    BADGE_MAP[now_playing['game']],
                    reward
                ))

    @command(regex='^badges cooldown$', name='badges cooldown')
    async def badges_cooldown(self, message):
        doc = await self.get_member_info(message.author.id)

        if doc['hit_cap'] == 0:
            return await self.mbot.send_message(
                message.channel,
                '**You have never hit the daily cap! Play some gaems man...** :ok_hand:'
            )

        hit_cap = human_time(time.time() - doc['hit_cap'])

        return await self.mbot.send_message(
            message.channel,
            f'**The last time you hit the cap was {hit_cap}.**'
        )

    @command(regex='^badges playtime$', name='badges playtime')
    async def badges_playtime(self, message):
        doc = await self.get_member_info(message.author.id)

        await self.mbot.send_message(
            message.channel,
            f'**Your total playtime for this session is {int(doc["total_playtime"] / 60)} minute(s).**'
        )

    @command(regex='^badges craft( foil)? (.*?)$', name='badges craft', usage='badges craft [foil] <badge_id>')
    async def badges_craft(self, message, foil, badge_id):
        if badge_id not in BADGE_DATA:
            return await self.mbot.send_message(
                message.channel,
                '**I could not find that badge...** :cry:'
            )

        badge = BADGE_DATA[badge_id]

        if not badge['craftable']:
            return await self.mbot.send_message(
                message.channel,
                '**This badge is not craftable...**'
            )

        doc = await self.get_member_info(message.author.id)
        inventory = {i['badge_id']: i['timestamp'] for i in doc['inventory']}
        inventory_id = badge_id + ('.foil' if foil else '.standard')

        if inventory_id in inventory:
            return await self.mbot.send_message(
                message.channel,
                '**You already own this badge.**'
            )

        fragments = {b['badge_id']: (b['standard'], b['foil']) for b in doc['fragments']}
        wallet = fragments.get(badge_id, (0, 0))

        if not foil:
            cost = badge['standard_cost']
        else:
            cost = badge['foil_cost']

        if cost['fragments'] > wallet[0] or cost['foil_fragments'] > wallet[1]:
            return await self.mbot.send_message(
                message.channel,
                '**Not enough fragments to craft this badge... Play more games to earn more fragments.**'
            )

        # Badge exists and the user has enough fragments to craft it;
        await self.badges_db.update_one(
            {'user_id': message.author.id, 'fragments': {'$elemMatch': {'badge_id': badge_id}}},
            {'$inc': {'fragments.$.standard': -cost['fragments'], 'fragments.$.foil': -cost['foil_fragments']}}
        )

        await self.badges_db.update_one(
            {'user_id': message.author.id, 'inventory.badge_id': {'$ne': badge_id}},
            {'$push': {'inventory': {'badge_id': inventory_id, 'timestamp': time.time()}}}
        )

        await self.mbot.send_message(
            message.channel,
            f'**Badge has been crafted!** :ok_hand:'
        )
