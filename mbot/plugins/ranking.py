import os
import io
import time
import random
import mimetypes

import aiohttp
import discord
from PIL import Image, ImageDraw, ImageFont

from ..plugin import BasePlugin
from ..command import command
from ..utils import long_running_task


# The XP cooldown represents the amount of time in seconds
# that needs to elapse before reaching maximum XP gains.
# When XP is gained by talking, an initial number is randomly selected
# and this is then multiplied by [`time.time() - last_awarded_xp` / `XP_COOLDOWN`].
# This is done to minimise rewards when messages are spammed, or sent in
# rapid succession. Note that the multiplier value cannot exceed 1.
XP_COOLDOWN = 30


class Ranking(BasePlugin):
    def __init__(self, mbot):
        super().__init__(mbot)

        self.ranking_db = self.mbot.mongo.plugin_data.ranking

    @staticmethod
    def _get_level(total_xp):
        if not total_xp % 10:
            total_xp += 1

        level = 0
        while total_xp > 0:
            total_xp -= 400 + (100 * level)
            level += 1

        return level

    @staticmethod
    def get_avatar_url(user):
        url = user.avatar_url

        # Sometimes no URL is present...
        if not url:
            return user.default_avatar_url

        return url

    async def _create_user(self, user_id, bio=None, bckg=None):
        doc = await self.ranking_db.find_one({'user_id': user_id})

        if not doc:
            ret = await self.ranking_db.insert_one({
                'user_id': user_id,
                'profile_bio': bio or 'A very mysterious person...',
                'profile_background': bckg or 'https://image.ibb.co/iup1Vc/580_680_76_D_33966_1393393398_420_588.jpg',
                'ranking': []
            })

            return ret

    async def _push_server(self, user_id, server_id):
        doc = await self.ranking_db.find_one(
            {'user_id': user_id, 'ranking': {'$elemMatch': {'server_id': server_id}}}
        )

        if not doc:
            ret = await self.ranking_db.update_one(
                {'user_id': user_id},
                {'$push': {'ranking': {
                    'server_id': server_id, 'score': 0, 'last_awarded_xp': XP_COOLDOWN
                }}}
            )

            return ret

    async def ensure_profile_exists(self, user_id, server_id=None):
        await self._create_user(user_id)

        if server_id is not None:
            await self._push_server(user_id, server_id)

    async def update_xp(self, user_id, server_id, by):
        await self.ensure_profile_exists(user_id, server_id)

        await self.ranking_db.update_one(
            {'user_id': user_id, 'ranking': {'$elemMatch': {'server_id': server_id}}},
            {'$inc': {'ranking.$.score': by}}
        )

        if by > 0:
            await self.ranking_db.update_one(
                {'user_id': user_id, 'ranking': {'$elemMatch': {'server_id': server_id}}},
                {'$set': {'ranking.$.last_awarded_xp': time.time()}}
            )

    async def update_background(self, user_id, bckg):
        await self.ensure_profile_exists(user_id)

        await self.ranking_db.update_one(
            {'user_id': user_id},
            {'$set': {'profile_background': bckg}}
        )

    async def update_bio(self, user_id, bio):
        await self.ensure_profile_exists(user_id)

        await self.ranking_db.update_one(
            {'user_id': user_id},
            {'$set': {'profile_bio': bio}}
        )

    async def get_user_data(self, user_id):
        await self.ensure_profile_exists(user_id)

        doc = await self.ranking_db.find_one(
            {'user_id': user_id}
        )

        server_scores = {}
        for server in doc['ranking']:
            server_scores[server['server_id']] = server['score']

        return {
            'user_id': user_id,
            'bio': doc['profile_bio'],
            'background': doc['profile_background'],
            'scores': server_scores
        }

    async def on_message(self, message):
        reward = random.randint(5, 15)

        doc = await self.ranking_db.find_one(
            {'user_id': message.author.id}
        )

        if doc is not None:
            last_awards = {server['server_id']: server['last_awarded_xp'] for server in doc['ranking']}

            if last_awards.get(message.server.id):
                reward *= min((time.time() - last_awards[message.server.id]), XP_COOLDOWN) / XP_COOLDOWN

        await self.update_xp(
            message.author.id,
            message.server.id,
            int(reward)
        )

    @command(description='view your current total xp', usage='xp', call_on_message=True)
    async def xp(self, message):
        user_data = await self.get_user_data(message.author.id)
        total_xp = user_data['scores'].get(message.server.id) or 0
        await self.mbot.send_message(message.channel, f'{message.author.mention} **TOTAL XP: {total_xp}**')

    @command(description='view your (legacy) ranking profile', usage='old_profile', call_on_message=True, cooldown=5)
    async def old_profile(self, message):
        user_data = await self.get_user_data(message.author.id)

        embed = discord.Embed(
            title = message.author.name,
            colour = 0x1abc9c
        )

        embed.set_footer(text=user_data['user_id'])
        embed.set_thumbnail(url=self.get_avatar_url(message.author))

        xp = user_data['scores'].get(message.server.id) or 0
        level = self._get_level(xp)

        embed.add_field(name='Total XP:', value=str(xp), inline=True)
        embed.add_field(name='Current Level: ', value=str(level), inline=True)

        await self.mbot.send_message(message.channel, embed=embed)

    @long_running_task(send_typing=True)
    def gen_profile(self, xp, name, bio, bckg_buffer, profile_buffer):
        # Check if any text contains unicode characters...
        # If so, we'll hvae to switch fonts as Source Sans Pro doesn't support them.
        try:
            name.encode('ascii')
            name.encode('ascii')
            font = ImageFont.truetype(os.path.join('data', 'SourceSansPro-Bold.ttf'), 18)
            font_small = ImageFont.truetype(os.path.join('data', 'SourceSansPro-Regular.ttf'), 12)
        except UnicodeError:
            font = ImageFont.truetype(os.path.join('data', 'DejaVuSans-Bold.ttf'), 18)
            font_small = ImageFont.truetype(os.path.join('data', 'DejaVuSans.ttf'), 12)

        bckg = Image.open(bckg_buffer)

        if bckg.mode != 'RGB':
            bckg = bckg.convert(mode='RGB')

        bckg = bckg.resize((310, 120), Image.ANTIALIAS)
        draw = ImageDraw.Draw(bckg)

        ppic = Image.open(profile_buffer)
        ppic = ppic.resize((80, 80), Image.ANTIALIAS)

        profile_template = Image.open(os.path.join('data', 'profile_template.png'))

        bckg.paste(profile_template, (0, 0), profile_template)
        bckg.paste(ppic, (20, 20))

        draw.text((110, 20), name, (33, 33, 33), font=font)
        draw.text((110, 42), bio, (33, 33, 33), font=font_small)
        draw.text((110, 60), 'LEVEL', (33, 33, 33), font=font)
        draw.text((110, 80), str(self._get_level(xp)), (33, 33, 33), font=font_small)
        draw.text((200, 60), 'XP', (33, 33, 33), font=font)
        draw.text((200, 80), str(xp), (33, 33, 33), font=font_small)

        profile_card = io.BytesIO()
        bckg.save(profile_card, format='png', mode='wb')
        profile_card.seek(0)

        return profile_card

    @command(description='view your ranking profile', usage='profile', call_on_message=True, cooldown=20)
    async def profile(self, message):
        user_data = await self.get_user_data(message.author.id)

        xp = user_data['scores'].get(message.server.id) or 0
        bio = user_data['bio']
        background = user_data['background']

        # Try to download background...
        try:
            with aiohttp.ClientSession() as client:
                async with client.get(background) as r:
                    bckg_buffer = io.BytesIO(bytes(await r.read()))
        except:
            return

        # Try to download profile pic...
        try:
            with aiohttp.ClientSession() as client:
                async with client.get(self.get_avatar_url(message.author)) as r:
                    profile_buffer = io.BytesIO(bytes(await r.read()))
        except:
            return

        profile = await self.gen_profile(xp, message.author.name, bio, bckg_buffer, profile_buffer, _message=message)
        await self.mbot.send_file(message.channel, profile, filename='profile.png')

    @command(regex='^bio (.*?)$', description='set bio for profile', usage='bio <bio>',
             call_on_message=True, cooldown=60)
    async def bio(self, message, bio):
        await self.update_bio(message.author.id, bio)

    @command(regex='^background <?(.*?)>?$', description='set a background for your profile',
             usage='background <url>', call_on_message=True, cooldown=60)
    async def background(self, message, url):
        try:
            with aiohttp.ClientSession() as client:
                async with client.head(url) as r:
                    size = r.headers.get('Content-Length', 0)
                    mimetype = r.headers.get('Content-Type')

            if not mimetype:
                mimetype = mimetypes.guess_type(url=url)[0]

            if size > 2*1024*1024 or not mimetype.startswith('image'):
                # We'll set a 2MB limit and the file must be an image.
                # This should do for now, but we'll probably need to make this more strict
                # in the future.
                return
        except:
            pass

        await self.update_background(message.author.id, url)

    @command(description='view the top 10 ranked players in the server', usage='top',
             cooldown=5, call_on_message=True)
    async def top(self, message):
        top = []

        # Thanks to https://stackoverflow.com/questions/28889240/mongodb-sort-documents-by-array-elements
        pipeline = [
            {'$match': {'ranking.server_id': message.server.id}},
            {'$addFields': {
                'order': {
                    '$filter': {
                        'input': '$ranking',
                        'as': 'r',
                        'cond': {'$eq': ['$$r.server_id', message.server.id]}
                    }
                }
            }},
            {'$sort': {'order': -1}}
        ]

        async for doc in self.ranking_db.aggregate(pipeline):
            user = message.server.get_member(doc['user_id'])

            if user:
                scores = {server['server_id']: server['score'] for server in doc['ranking']}
                top.append((user, scores[message.server.id]))

            if len(top) == 10:
                break

        code_block = '```\n'
        for x, ru in enumerate(top):
            code_block += '{:<8} >\t{:<32} {}\n'.format(f'[{x + 1}]', ru[0].name, f'({ru[1]})')

        code_block += '\n```'
        await self.mbot.send_message(message.channel, code_block)
