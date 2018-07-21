import os
import io
import time
import random
from hashlib import sha256
from datetime import datetime, timezone

import discord
from PIL import Image
from bson.objectid import ObjectId
from bson.errors import InvalidId

from .badge_data import BADGE_DATA, BADGE_MAP
from ..plugin import BasePlugin
from ..command import command
from ..utils import human_time, long_running_task


PLAYTIME_RESET = 24 * 60 * 60
DAILY_CAP = 2 * 60 * 60

trade_options = {
    'sf': 'Fragment(s) [Standard]',
    'ff': 'Fragment(s) [Foil]',
    'sb': 'Badge [Standard]',
    'fb': 'Badge [Foil]'
}


class Badges(BasePlugin):
    def __init__(self, mbot):
        super().__init__(mbot)

        self.badges_db = self.mbot.mongo.plugin_data.badges
        self.trade_db = self.mbot.mongo.plugin_data.trades

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

    async def _push_fragments(self, user_id, badge_id):
        await self.badges_db.update_one(
            {'user_id': user_id, 'fragments.badge_id': {'$ne': badge_id}},
            {'$push': {'fragments': {'badge_id': badge_id, 'standard': 0, 'foil': 0}}}
        )

    async def update_fragments(self, user_id, badge_id, fragments=0, foil_fragments=0, trading=False):
        await self._push_fragments(user_id, badge_id)

        if not trading:
            await self.badges_db.update_one(
                {'user_id': user_id, 'fragments': {'$elemMatch': {'badge_id': badge_id}}},
                {'$inc': {'fragments.$.standard': fragments, 'fragments.$.foil': foil_fragments}}
            )
        else:
            await self.badges_db.update_one(
                {'user_id': user_id, 'fragments': {'$elemMatch': {'badge_id': badge_id}}},
                {'$inc': {'fragments.$.trading_standard': fragments, 'fragments.$.trading_foil': foil_fragments}}
            )

    async def drop_rewards(self, user_id, badge_id, seconds_played):
        await self._push_fragments(user_id, badge_id)

        minutes_played = int(seconds_played / 60)
        fragments, foil_fragments = 0, 0

        for _ in range(minutes_played):
            # 1% chance to be rewarded a foil fragment.
            if random.randrange(1, 101) == random.randrange(1, 101):
                foil_fragments += 1
            else:
                fragments += 1

        await self.update_fragments(user_id, badge_id, fragments, foil_fragments)

    async def check_inventory(self, user_id):
        doc = await self.badges_db.find_one({'user_id': user_id})

        if not doc:
            return False

        if doc['inventory']:
            return True

        for f in doc['fragments']:
            if f['foil'] or f['standard']:
                return True

        return False

    async def set_trading(self, trade, badge_id, user_id, amount=None, unset=False):
        _type = "foil" if trade[0] == "f" else "standard"

        if trade[1] == 'f':
            if trade[0] == 'f':
                await self.update_fragments(user_id, badge_id, foil_fragments=amount)
            else:
                await self.update_fragments(user_id, badge_id, fragments=amount)

            await self.badges_db.update_one(
                {'user_id': user_id, 'fragments': {'$elemMatch': {'badge_id': badge_id}}},
                {'$set' if not unset else '$unset': {f'fragments.$.trading_{_type}': abs(amount)}}
            )
        elif trade[1] == 'b':
            _id = f'{badge_id}.{_type}'
            await self.badges_db.update_one(
                {'user_id': user_id, 'inventory': {'$elemMatch': {'badge_id': _id}}},
                {'$set' if not unset else '$unset': {f'inventory.$.trading': True}}
            )

    async def remove_badge_from_display(self, user_id, badge):
        await self.badges_db.update_one(
            {'user_id': user_id},
            {'$pull': {'display': {'badge_id': badge}}}
        )

    async def remove_badge_from_inventory(self, user_id, badge):
        await self.remove_badge_from_display(user_id, badge)
        await self.badges_db.update_one(
            {'user_id': user_id},
            {'$pull': {'inventory': {'badge_id': badge}}}
        )

    async def add_badge_to_inventory(self, user_id, badge, level=0):
        await self.badges_db.update_one(
            {'user_id': user_id, 'inventory.badge_id': {'$ne': badge}},
            {'$push': {'inventory': {'badge_id': badge, 'time_added': time.time(), 'level': level}}}
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

    @command(regex='^badges mystats', name='badges mystats')
    async def badges_stats(self, message):
        doc = await self.get_member_info(message.author.id)

        hit_cap = doc['hit_cap']
        _hit_cap = human_time(time.time() - doc['hit_cap'])
        playtime = int(doc['total_playtime'] / 60)
        playtime_remaining= int(max(DAILY_CAP - doc['total_playtime'], 0) / 60)

        return await self.mbot.send_message(
            message.channel,
            f'**Your playtime stats for the latest {int(DAILY_CAP / 3600)}-hour session**\n\n'
            f'{"You have never hit the daily cap before" if hit_cap == 0 else "You hit the cap " + _hit_cap}.\n'
            f'The daily playtime cap is {DAILY_CAP} seconds. The playtime cooldown is {PLAYTIME_RESET} seconds.\n'
            f'You have {playtime} minute(s) of playtime in this session and {playtime_remaining} minute(s) remaining.'
        )

    async def _browse_badges(self, message, header='', craftable_only=False, silent=False):
        badges, page = [], 0
        doc = await self.get_member_info(message.author.id)
        fragments = {x['badge_id']: (x['standard'], x['foil']) for x in doc['fragments']}

        for badge in BADGE_DATA.items():
            if craftable_only and (not badge[1]['craftable'] or not fragments.get(badge[0])):
                continue

            if craftable_only and (fragments[badge[0]][0] < badge[1]['standard_cost']['fragments']
                or fragments[badge[0]][1] < badge[1]['standard_cost']['foil_fragments']): pass
            else:
                badges.append((f'{badge[0]}.standard', f'{badge[1]["badge_name"]} [Standard]'))

            if badge[1]['has_foil']:
                if craftable_only and (fragments[badge[0]][0] < badge[1]['foil_cost']['fragments']
                    or fragments[badge[0]][1] < badge[1]['foil_cost']['foil_fragments']): pass
                else:
                    badges.append((f'{badge[0]}.foil', f'{badge[1]["badge_name"]} [Foil]'))

        badges = sorted(badges, key=lambda t: t[1])

        if not badges:
            if not silent:
                await self.mbot.send_message(
                    message.channel,
                    f'**{"You have no resources to craft any badges" if craftable_only else "Something went wrong."}**'
                )

            return

        while True:
            items = badges[page * 8: (page * 8) + 8]
            next_page = badges[(page + 1) * 8: ((page + 1) * 8) + 8]

            options = dict(items)

            option = await self.mbot.option_selector(
                message, header, options, np=bool(next_page), pp=page != 0, timeout=180
            )

            if not option:
                if not silent:
                    await self.mbot.send_message(
                        message.channel, '**Closing menu.**'
                    )

                break

            if option == 'np':
                page += 1
            elif option == 'pp':
                page -= 1
            else:
                yield option

    @command(regex='^badges craft$', name='badges craft', usage='badges craft', mutex='badges')
    async def badges_craft(self, message):
        header = '**Showing Badges You Can Craft**\nEnter an option number from the menu to craft badges or move pages.'

        async for b in self._browse_badges(message, header=header, craftable_only=True):
            break
        else:
            return

        badge_id, badge_type = b.split('.')
        badge = BADGE_DATA[badge_id]

        doc = await self.get_member_info(message.author.id)
        inventory = [i['badge_id'] for i in doc['inventory']]

        if b in inventory:
            return await self.mbot.send_message(
                message.channel,
                '**You already own this badge.**'
            )

        if badge_type == 'standard':
            cost = badge['standard_cost']
        else:
            cost = badge['foil_cost']

        # Badge exists and the user has enough fragments to craft it;
        await self.update_fragments(message.author.id, badge_id, -cost['fragments'], -cost['foil_fragments'])
        await self.add_badge_to_inventory(message.author.id, b)

        await self.mbot.send_message(
            message.channel,
            f'**Badge has been crafted!** :ok_hand:'
        )

    @command(regex='^badges upgrade$', name='badges upgrade', mutex='badges')
    async def badges_upgrade(self, message):
        header = '**Which Badge Would You Like To Upgrade?**'
        async for b in self._browse_inventory(message, header=header, fragments=False, foil=False):
            break
        else:
            return

        badge_id = b.split(' ')[1]
        cost = BADGE_DATA[badge_id]['standard_cost']
        doc = await self.get_member_info(message.author.id)
        badges = {x['badge_id']: (x['level'], x.get('trading', False)) for x in doc['inventory']}
        fragments = {x['badge_id']: (x['standard'], x['foil']) for x in doc['fragments']}.get(badge_id)

        if badges[f'{badge_id}.standard'][1]:
            return await self.mbot.send_message(
                message.channel,
                '**You cannot upgrade this badge while it is being traded!**\n'
                'Please wait until an offer to your trade is made, or cancel the trade.'
            )

        if not fragments or fragments[0] < cost['fragments'] or fragments[1] < cost['foil_fragments']:
            return await self.mbot.send_message(
                message.channel, '**You do not have enough fragments to upgrade this badge!**'
            )

        if badges[f'{badge_id}.standard'][0] == 4:
            return await self.mbot.send_message(
                message.channel, '**This badge cannot be upgraded any further!**'
            )

        await self.update_fragments(message.author.id, badge_id, -cost['fragments'], -cost['foil_fragments'])

        await self.badges_db.update_one(
            {'user_id': message.author.id, 'inventory': {'$elemMatch': {'badge_id': f'{badge_id}.standard'}}},
            {'$inc': {'inventory.$.level': 1}}
        )

        await self.mbot.send_message(
            message.channel,
            f':ok_hand: **Upgraded badge to level *{badges[f"{badge_id}.standard"][0] + 1}*.**'
        )

    @command(regex='^badges dismantle$', name='badges dismantle', mutex='badges')
    async def badges_dismantle(self, message):
        async for b in self._browse_inventory(message, '**Select the badge you want to dismantle**', fragments=False):
            break
        else:
            return

        badge = b.split(' ')
        badge_id, badge_level = badge[1], badge[3]
        doc = await self.get_member_info(message.author.id)
        trading = {x['badge_id']: x.get('trading', False) for x in doc['inventory']}

        if trading[f'{badge_id}.{"standard" if badge[0][0] == "s" else "foil"}']:
            return await self.mbot.send_message(
                message.channel,
                '**You cannot dismantle this badge while it is being traded!**\n'
                'Please wait until an offer to your trade is made, or cancel the trade.'
            )

        if badge[0][0] == 'f':
            cost = BADGE_DATA[badge_id]['foil_cost']
        else:
            cost = BADGE_DATA[badge_id]['standard_cost']

        await self.update_fragments(
            message.author.id,
            badge_id,
            fragments=cost['fragments'] + (cost['fragments'] * int(badge_level)),
            foil_fragments=cost['foil_fragments'] + (cost['foil_fragments'] * int(badge_level))
        )

        await self.remove_badge_from_inventory(
            message.author.id, f'{badge_id}.{"standard" if badge[0][0] == "s" else "foil"}'
        )

        await self.mbot.send_message(message.channel, '**Badge has been dismantled!**')

    @command(regex='^badges display$', name='badges display', mutex='badges')
    async def badges_display(self, message):
        header = '**Your Badges**\nEnter an option number from the menu to display a badge or move pages.'

        async for b in self._browse_inventory(message, header=header, fragments=False):
            break
        else:
            return

        b = b.split(' ')
        badge_id = b[1]
        badge = f'{badge_id}.{"standard" if b[0][0] == "s" else "foil"}'
        doc = await self.get_member_info(message.author.id)

        display = {x['badge_id']: x['slot'] for x in doc['display']}

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

        if display.get(badge) == slot.content:
            return await self.mbot.send_message(
                message.channel,
                '*It seems that this badge is already on display.*'
            )

        moved = False

        if display.get(badge):
            await self.remove_badge_from_display(message.author.id, badge)
            moved = True

        if slot.content in list(display.values()):
            await self.badges_db.update_one(
                {'user_id': message.author.id},
                {'$pull': {'display': {'slot': slot.content}}}
            )

        ret = await self.badges_db.update_one(
            {'user_id': message.author.id, 'display.badge_id': {'$ne': badge}},
            {'$push': {'display': {'badge_id': badge, 'time_displayed': time.time(), 'slot': slot.content}}}
        )

        if ret.modified_count == 1:
            return await self.mbot.send_message(
                message.channel,
                f'**{"Badge is now on display!" if not moved else "Badge was moved to the selected slot!"}**'
            )

        return await self.mbot.send_message(
            message.channel,
            'It seems that something went wrong on my end...'
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
            badge_name = f'badge{display_data[slot][0]}-{display_data[slot][1]}{display_data[slot][2]}.png'
            badge_buf = Image.open(os.path.join('data', 'badges', badge_name))

            bckg.paste(badge_buf, slot_positions[slot], badge_buf)

        buffer = io.BytesIO()
        bckg.save(buffer, format='png', mode='wb')
        buffer.seek(0)

        return buffer

    @command(cooldown=60)
    async def badges(self, message):
        doc = await self.get_member_info(message.author.id)
        levels = {x['badge_id']: x['level'] for x in doc['inventory']}

        if not doc['display']:
            return await self.mbot.send_file(message.channel, fp=os.path.join('data', 'badges', 'display0.png'))

        display = {x['slot']: (
            x['badge_id'].split('.')[0], x['badge_id'].split('.')[1], levels[x['badge_id']]
        ) for x in doc['display']}

        buffer = await self.generate_badges_image(display, _message=message)
        await self.mbot.send_file(message.channel, buffer, filename='badges.png')

    async def _browse_inventory(self, message, header='', fragments=True, badges=True, foil=True, silent=False):
        doc = await self.get_member_info(message.author.id)
        inventory, page = [], 0

        if badges:
            for badge in doc['inventory']:
                badge_id, badge_type = badge['badge_id'].split('.')

                if not foil and badge_type == 'foil':
                    continue

                badge_data = BADGE_DATA[badge_id]
                inventory.append(
                    (f'{badge_type[0]}b {badge_id} 1 {badge["level"]}',
                     f'{badge_data["badge_name"]} Badge [{badge_type.title()}] {{#{badge["level"]}}}')
                )

        if fragments:
            for fragment in doc['fragments']:
                badge_data = BADGE_DATA[fragment['badge_id']]

                if fragment['standard']:
                    inventory.append(
                        (f'sf {fragment["badge_id"]} {fragment["standard"]}',
                         f'{badge_data["badge_name"]} Fragment(s) [Standard] {{{fragment["standard"]}}}')
                    )

                if fragment['foil']:
                    if not foil:
                        continue

                    inventory.append(
                        (f'ff {fragment["badge_id"]} {fragment["foil"]}',
                         f'{badge_data["badge_name"]} Fragment(s) [Foil] {{{fragment["foil"]}}}')
                    )

        if not inventory:
            if not silent:
                await self.mbot.send_message(
                    message.channel, '**You have nothing in your inventory.**'
                )

            return

        inventory = sorted(inventory, key=lambda t: t[1])

        while True:
            items = inventory[page * 8: (page * 8) + 8]
            next_page = inventory[(page + 1) * 8: ((page + 1) * 8) + 8]

            options = dict(items)

            option = await self.mbot.option_selector(
                message, header, options, np=bool(next_page), pp=page != 0, timeout=180
            )

            if not option:
                if not silent:
                    await self.mbot.send_message(
                        message.channel, '**Closing menu.**'
                    )

                break

            if option == 'np':
                page += 1
            elif option == 'pp':
                page -= 1
            else:
                yield option

    async def fetch_trades(self, page, user_id=None):
        trades, query = [], {}

        if user_id is not None:
            query['user_id'] = user_id

        async for trade in self.trade_db.find(query).skip(page * 8).limit(8):  # A page represents 8 records / trades.
            trades.append(trade)

        return trades

    async def _browse_trades(self, message, header='', user_id=None, silent=False):
        page = 0

        while True:
            trades = await self.fetch_trades(page, user_id=user_id)
            next_page = await self.fetch_trades(page + 1, user_id=user_id)

            if not trades:
                if not silent:
                    await self.mbot.send_message(
                        message.channel, '**I couldn\'t find any trades.**'
                    )

                break

            options = {}
            for x in enumerate(trades):
                options[str(x[0])] = '{:<7} {:<22} {{{}}}'.format(
                    f'{x[1]["amount"]}x',
                    f'{trade_options[x[1]["trade_type"]]}',
                    BADGE_DATA[x[1]["badge_id"]]['badge_name']
                )

            option = await self.mbot.option_selector(
                message,
                f'**Badge & Fragment Trades**\n{header}',
                options, timeout=180, pp=page != 0, np=bool(next_page)
            )

            if not option:
                if not silent:
                    await self.mbot.send_message(
                        message.channel, '**Closing menu.**'
                    )

                break

            if option == 'np':
                page += 1
            elif option == 'pp':
                page -= 1
            else:
                yield trades[int(option)]

    @command(regex='^trade sell$', name='trade sell', mutex='badges')
    async def trade_sell(self, message):
        header = '**Your Inventory**\nEnter the option number of the item you want to put up for trade.'

        async for t in self._browse_inventory(message, header=header):
            break
        else:
            return

        t = t.split(' ')
        trade, badge_id, max_amount, amount = t[0], t[1], int(t[2]), 1

        _ = await self.trade_db.find_one(
            {'user_id': message.author.id, 'trade_type': trade, 'badge_id': badge_id}
        )

        if _:
            return await self.mbot.send_message(
                message.channel,
                f'*You have already put this item up for trade (trade ID **{str(_["_id"])}**)*'
            )

        if trade[1] == 'f':
            amount = await self.mbot.wait_for_input(
                message,
                f'**Enter the amount of fragments you want to sell (max {max_amount});**',
                check=lambda m: m.content.isdigit() and int(m.content) > 0
            )

            amount = min(int(amount.content) if amount else 1, max_amount)

        description = await self.mbot.wait_for_input(
            message,
            '**Enter a description for this trade.**\n'
            'The format of this description is not important, you can write anything you want, however, '
            'it is important to mention at the very least what you want in return so other users '
            'can make offers which are more likely to interest you, e.g. something along the lines of '
            '*"looking for the Witcher badge (ID 00) or it\'s foil fragments, willing to negotiate"* '
            'would be considered a good description. Remember that if your listing receives no offers within '
            'a week, it will be deleted. :ok_hand:',
            timeout=180
        )

        if description is not None:
            human_string = f'{amount}x {BADGE_DATA[badge_id]["badge_name"]} {trade_options[trade]}'

            if trade[1] == 'b':
                human_string += f' {{#{t[-1]}}}'

            await self.trade_db.insert_one(
                {
                    'user_id': message.author.id,
                    'trade_type': trade,
                    'badge_id': badge_id,
                    'badge_level': int(t[3]) if trade[1] == 'b' else None,
                    'amount': amount,
                    'human_string': human_string,
                    'description': description.content,
                    'time_submitted': time.time(),
                    'offers': []
                }
            )

            await self.set_trading(trade, badge_id, message.author.id, -amount)

            return await self.mbot.send_message(
                message.channel,
                ':ok_hand: **Item is now up for sale!** :dollar:',
            )

        return await self.mbot.send_message(
            message.channel,
            '*The item description must be supplied.*'
        )

    @command(regex='^trade cancel$', name='trade cancel', mutex='badges')
    async def trade_cancel(self, message):
        header = 'Your trades\nEnter an appropriate option number to cancel a trade.'

        async for trade in self._browse_trades(message, header, user_id=message.author.id):
            break
        else:
            return

        await self.set_trading(
            trade["trade_type"], trade["badge_id"], message.author.id, amount=trade["amount"], unset=True
        )

        await self.trade_db.delete_one(
            {'_id': trade["_id"]}
        )

        await self.mbot.send_message(message.channel, '**Trade cancelled!** :ok_hand:')

    @command(regex='^trade browse$', name='trade browse')
    async def trade_browse(self, message):
        header = '**Enter an option number from the menu.**\n' \
                 'The trade information will be sent in a PM to you\n' \

        async for trade in self._browse_trades(message, header, user_id={'$ne': message.author.id}):
            try:
                author = await self.mbot.get_user_info(trade['user_id'])
            except (discord.NotFound, discord.HTTPException):
                author = None

            time_str = datetime.fromtimestamp(trade['time_submitted']).strftime('%Y-%m-%d %H:%M:%S')
            # noinspection PyArgumentList
            utc_offset = datetime.now(timezone.utc).astimezone().strftime('%z')
            badge = BADGE_DATA.get(trade['badge_id'])

            await self.mbot.send_message(
                message.author,
                f'**Trade *{str(trade["_id"])}***\n'
                f'Trade submitted by {author.mention if author else "<@user>"} (ID: {trade["user_id"]})'
                f'\nDate submitted {time_str} {utc_offset}\n\n'
                '**Trade Information**\n'
                f'  • Trade Type - `{trade["trade_type"]}` | `{trade_options[trade["trade_type"]]}`\n'
                f'  • Trade Vol. - `{trade["amount"]}`\n\n'
                '**Badge / Fragments Information**\n'
                f'  • Badge / Fragments Name - `{badge["badge_name"]}`\n'
                f'  • Badge / Fragments ID - `{trade["badge_id"]}`\n'
                f'  • Badge Level - `{trade["badge_level"] if trade["badge_level"] is not None else "N/A"}`\n'
                f'  • Games - `{badge["games"]}`\n\n'
                '**Trade Description**\n'
                f'```{trade["description"]}```\n\n'
                f'To make an offer to this trade, run the command `trade offer {str(trade["_id"])}`'
                ' in any server that I\'m in using that server\'s prefix.'
            )

    async def _make_offer(self, message):
        if not await self.check_inventory(message.author.id):
            return await self.mbot.send_message(
                message.channel,
                '**You have no tradable items in your inventory.**'
            )

        offer, header = {}, '**Enter the appropriate option number to add an item to your offer;**'

        while True:
            actions = {'1': 'Add/Update Item'}

            if offer:
                actions['2'] = 'Remove Item'
                actions['3'] = '~ Confirm Offer'

            _m = '\n'.join([x[1] for x in sorted(offer.values())])

            action = await self.mbot.option_selector(
                message,
                options=actions,
                header='**Enter the number of the action you want to perform.**',
                footer=f'\n**Current Offer:**\n```{_m or "empty"}```',
                timeout=60
            )

            if not action:
                return await self.mbot.send_message(
                    message.channel,
                    '**Exiting Offer Menu!**'
                )

            if action == '1':
                async for item in self._browse_inventory(message, header, silent=True):
                    break
                else:
                    continue

                amount = 1

                _item = item.split(' ')
                item_type, item_id, item_level = _item[0], _item[1], None

                if item_type[1] == 'b':
                    item_level = int(_item[3])

                if item_type[1] == 'f':
                    max_amount = int(_item[2])
                    amount = await self.mbot.wait_for_input(
                        message,
                        f'**Enter the amount of fragments you want to sell (max {max_amount});**',
                        check=lambda m: m.content.isdigit() and int(m.content) > 0, timeout=30
                    )

                    max_amount = int(item.split(' ')[2])
                    amount = min(int(amount.content) if amount else 1, max_amount)

                human_string = f'{amount}x {BADGE_DATA[item_id]["badge_name"]} {trade_options[item_type]}'

                if item_type[1] == 'b':
                    human_string += f' {{#{_item[-1]}}}'

                offer[f'{item_type} {item_id}'] = (amount, human_string, item_level)

            elif action == '2':
                opt = await self.mbot.option_selector(
                    message, 'Enter the corresponding option number to remove an item.',
                    {x[0]: x[1][1] for x in offer.items()}
                )

                if not opt:
                    continue

                del offer[opt]

            elif action == '3':
                break

        return [
            {'item': x[0], 'amount': x[1][0], 'human_string': x[1][1], 'badge_level': x[1][2]} for x in offer.items()
        ]

    @command(regex='^trade offer (.*?)$', name='trade offer', mutex='badges')
    async def trade_offer(self, message, trade_id):
        try:
            trade = await self.trade_db.find_one({'_id': ObjectId(trade_id)})
        except InvalidId:
            return await self.mbot.send_message(
                message.channel,
                '*Invalid trade ID...* :cry:'
            )

        if not trade:
            return await self.mbot.send_message(
                message.channel,
                '*This trade does not exist... Maybe it was deleted...* :thinking:'
            )

        offer = await self._make_offer(message)

        if not offer:
            return await self.mbot.send_message(
                message.channel,
                '**Invalid offer.**'
            )

        offer_dict = {
            'offer': offer,
            'user_id': message.author.id,
            'timestamp': time.time()
        }

        offer_id = sha256(str(offer_dict).encode('utf-8')).hexdigest()[:16]
        offer_dict['offer_id'] = offer_id

        await self.trade_db.update_one(
            {'_id': ObjectId(trade_id)},
            {'$push': {'offers': offer_dict}}
        )

        for item in offer:
            await self.set_trading(
                item['item'].split(' ')[0],
                item['item'].split(' ')[1],
                message.author.id,
                -item['amount']
            )

        user = await self.mbot.get_user_info(trade['user_id'])

        if user:
            offer_msg = '\n'.join(x['human_string'] for x in offer)

            await self.mbot.send_message(
                user,
                f'{message.author.mention} has made an offer to your trade (**{str(trade["_id"])}**);\n\n'
                f'```{offer_msg}```\n\n'
                f'To accept this offer run the command `trade accept {str(trade["_id"])} {offer_id}` in any server'
                ' that I\'m in using that server\'s prefix.'
            )

        await self.mbot.send_message(
            message.channel,
            '**The specified offer has been made and the trade owner notified!** :ok_hand:'
        )

    @command(regex='^trade accept (.*?) (.*?)$', name='trade accept', mutex='badges')
    async def trade_accept(self, message, trade_id, offer_id):
        try:
            trade = await self.trade_db.find_one({'_id': ObjectId(trade_id), 'user_id': message.author.id})
        except InvalidId:
            return await self.mbot.send_message(
                message.channel,
                '*Invalid trade ID...* :cry:'
            )

        if not trade:
            return await self.mbot.send_message(
                message.channel,
                '*This trade does not exist... Maybe it was deleted...* :thinking:'
            )

        offer = {o['offer_id']: o for o in trade['offers']}.get(offer_id)

        if offer is None:
            return await self.mbot.send_message(
                message.channel,
                '*This offer does not exist!*'
            )

        for item in offer['offer']:
            item_type, item_id = item['item'].split(' ')

            if item_type[1] == 'b':
                await self.add_badge_to_inventory(
                    message.author.id,
                    f'{item_id}.{"standard" if item_type[0] == "s" else "foil"}',
                    item['badge_level']
                )

                await self.remove_badge_from_inventory(
                    offer['user_id'], f'{item_id}.{"standard" if item_type[0] == "s" else "foil"}'
                )

            elif item_type[1] == 'f':
                await self.update_fragments(
                    message.author.id, badge_id=item_id,
                    fragments=item['amount'] if item_type[0] == 's' else 0,
                    foil_fragments=item['amount'] if item_type[0] == 'f' else 0
                )

                await self.update_fragments(
                    offer['user_id'], item_id,
                    fragments=-item['amount'] if item_type[0] == 's' else 0,
                    foil_fragments=-item['amount'] if item_type[0] == 'f' else 0,
                    trading=True
                )

        t_item_type, t_item_id = trade['trade_type'], trade['badge_id']

        if t_item_type[1] == 'f':
            await self.update_fragments(
                message.author.id, badge_id=t_item_id,
                fragments=-trade['amount'] if t_item_type[0] == 's' else 0,
                foil_fragments=-trade['amount'] if t_item_type[0] == 'f' else 0,
                trading=True
            )

            await self.update_fragments(
                offer['user_id'], badge_id=t_item_id,
                fragments=trade['amount'] if t_item_type[0] == 's' else 0,
                foil_fragments=trade['amount'] if t_item_type[0] == 'f' else 0
            )

        elif t_item_type[1] == 'b':
            await self.remove_badge_from_inventory(
                message.author.id, f'{t_item_id}.{"standard" if t_item_type[0] == "s" else "foil"}'
            )

            await self.add_badge_to_inventory(
                offer['user_id'],
                f'{t_item_id}.{"standard" if t_item_type[0] == "s" else "foil"}',
                trade['badge_level']
            )

        offer_msg = '\n'.join(x['human_string'] for x in offer['offer'])

        await self.mbot.send_message(
            message.channel,
            '**Trade Complete!** :ok_hand:\n\n'
            'The following item(s) have been added to your inventory:\n'
            f'```{offer_msg}```\n\n'
            'The following item(s) have been removed from your inventory:\n'
            f'```{trade["human_string"]}```'
        )

        offer_user = await self.mbot.get_user_info(offer['user_id'])

        if offer_user:
            await self.mbot.send_message(
                offer_user,
                f'Your offer for trade **{str(trade["_id"])}** has been accepted.\n\n'
                'The following item(s) have been added to your inventory:\n'
                f'```{trade["human_string"]}```\n\n'
                'The following item(s) have been removed from your inventory:\n'
                f'```{offer_msg}```'
            )

        await self.trade_db.delete_one(
            {'_id': ObjectId(trade_id)}
        )
