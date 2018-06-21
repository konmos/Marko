import os
import io
import time
import random

from PIL import Image

from .badge_data import BADGE_DATA, BADGE_MAP
from ..plugin import BasePlugin
from ..command import command
from ..utils import human_time, long_running_task


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
            'inventory': [],
            'display': []
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

    @command(regex='^badges display$', name='badges display')
    async def badges_display(self, message):
        badge_id = await self.mbot.wait_for_input(
            message,
            '**Which badge would you like to display? Enter the two character badge ID;**',
            check=lambda m: len(m.content) == 2
        )

        if not badge_id or not badge_id.content or badge_id.content not in BADGE_DATA:
            return await self.mbot.send_message(
                message.channel,
                '*Invalid badge ID.* :cry:'
            )

        badge_id = badge_id.content

        doc = await self.get_member_info(message.author.id)
        inventory = {i['badge_id']: i['timestamp'] for i in doc['inventory']}

        if f'{badge_id}.foil' not in inventory or f'{badge_id}.standard' not in inventory:
            return await self.mbot.send_message(
                message.channel,
                '*You do not own this badge.* :cry:'
            )

        if f'{badge_id}.standard' in inventory and f'{badge_id}.foil' in inventory:
            badge_type = await self.mbot.wait_for_input(
                message,
                '**Would you like to display the standard or foil badge?**'
                '\nPlease reply with either `standard` or `foil`. The default is `foil`.',
                check=lambda m: m.content in ['standard', 'foil']
            )

            badge_type = badge_type.content if badge_type else ''
            badge = f'{badge_id}.{badge_type or "foil"}'
        elif f'{badge_id}.standard' in inventory:
            badge = f'{badge_id}.standard'
        else:
            badge = f'{badge_id}.foil'

        slot = await self.mbot.wait_for_input(
            message,
            '**Display Slots:**\n```[1]\t[2]\t[3]```\n Which slot would you like to place the badge in? '
            'Please enter either `1`, `2`, or `3`.',
            check=lambda m: m.content.isdigit()
        )

        if not slot or slot.content not in ['1', '2', '3']:
            return await self.mbot.send_message(
                message.channel,
                '*Unrecognised slot.* :cry:'
            )

        ret = await self.badges_db.update_one(
            {'user_id': message.author.id, 'display.badge_id': {'$ne': badge}},
            {'$push': {'display': {'badge_id': badge, 'timestamp': time.time(), 'slot': slot.content}}}
        )

        if ret.modified_count == 1:
            return await self.mbot.send_message(
                message.channel,
                '**Badge is now on display!**'
            )

        return await self.mbot.send_message(
            message.channel,
            'It seems that you already have this badge on display... or something went wrong on my end...'
        )

    @long_running_task(send_typing=True)
    def generate_badges_image(self, display_data):
        slot_positions = {
            '1': (39, 39),
            '2': (389, 39),
            '3': (739, 39)
        }

        if len(display_data) == 3:
            fname = 'display3.png'
        else:
            fname = f'display{len(display_data)}-{"".join(sorted(display_data.keys()))}.png'

        bckg = Image.open(os.path.join('data', 'badges', fname))

        for slot in display_data:
            badge_name = f'badge{display_data[slot][0]}-{display_data[slot][1]}.png'
            badge_buf = Image.open(os.path.join('data', 'badges', badge_name))

            bckg.paste(badge_buf, slot_positions[slot], badge_buf)

        buffer = io.BytesIO()
        bckg.save(buffer, format='png', mode='wb')
        buffer.seek(0)

        return buffer

    @command(cooldown=60)
    async def badges(self, message):
        doc = await self.get_member_info(message.author.id)

        if not doc['display']:
            return await self.mbot.send_file(message.channel, fp=os.path.join('data', 'badges', 'display0.png'))

        display = {x['slot']: (x['badge_id'].split('.')[0], x['badge_id'].split('.')[1]) for x in doc['display']}

        buffer = await self.generate_badges_image(display, _message=message)
        await self.mbot.send_file(message.channel, buffer, filename='badges.png')
