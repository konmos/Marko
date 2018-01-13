import os
import io
import time
import random
import mimetypes

import aiohttp
import discord
import peewee as pe
from PIL import Image, ImageDraw, ImageFont

from ..plugin import BasePlugin
from ..database import BaseModel
from ..command import command
from ..utils import long_running_task


class RankedProfile(BaseModel):
    '''
    Represents a global profile for a ranked user.
    '''
    user_id = pe.CharField(unique=True)
    bio = pe.CharField(default='A very mysterious person...')
    background = pe.CharField(
        default='https://img00.deviantart.net/95e7/i/2014/007/d/3/google_abstract_by_dynamicz34-d718hzj.png'
    )


class RankedUser(BaseModel):
    '''
    Represents a single user in a particular server.
    '''
    server = pe.CharField()
    user_id = pe.CharField()
    xp = pe.IntegerField()

    profile = pe.ForeignKeyField(RankedProfile, to_field='user_id')


class Ranking(BasePlugin):
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

    async def on_ready(self):
        self.mbot.db.db.create_tables([RankedProfile, RankedUser], safe=True)

    async def on_message(self, message):
        profile = RankedProfile.select().where(
            RankedProfile.user_id == message.author.id
        )

        if not profile.exists():
            profile = RankedProfile.create(
                user_id=message.author.id
            )

            profile.save()

        user = RankedUser.select().where(
            RankedUser.user_id == message.author.id, RankedUser.server == message.server.id
        )

        if not user.exists():
            user = RankedUser.create(
                server=message.server.id,
                user_id=message.author.id,
                username=message.author,
                xp=random.randint(2, 14),
                profile=profile.get().user_id
            )

            user.save()
        else:
            update_xp = RankedUser.update(xp=RankedUser.xp + random.randint(2, 14)).where(
                RankedUser.user_id == message.author.id,
                RankedUser.server == message.server.id
            )

            update_xp.execute()

    @command(description='view your current total xp', usage='xp', call_on_message=True)
    async def xp(self, message):
        user = RankedUser.select().where(
            RankedUser.user_id == message.author.id, RankedUser.server == message.server.id
        )

        total_xp = str(user.get().xp) if user.exists() else '0'
        await self.mbot.send_message(message.channel, f'{message.author.mention} **TOTAL XP: {total_xp}**')

    @command(description='view your (legacy) ranking profile', usage='old_profile', call_on_message=True)
    async def old_profile(self, message):
        user = RankedUser.select().where(
            RankedUser.user_id == message.author.id, RankedUser.server == message.server.id
        )

        embed = discord.Embed(
            title = message.author.name,
            colour = 0x1abc9c
        )

        embed.set_footer(text=str(int(time.time())))
        embed.set_thumbnail(url=self.get_avatar_url(message.author))

        xp = user.get().xp if user.exists() else 0
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

    @command(description='view your ranking profile', usage='profile', call_on_message=True)
    async def profile(self, message):
        user = RankedUser.select().where(
            RankedUser.user_id == message.author.id, RankedUser.server == message.server.id
        )

        if not user.exists():
            return

        xp = user.get().xp
        bio = user.get().profile.bio
        background = user.get().profile.background

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

    @command(regex='^bio (.*?)$', description='set bio for (beta) profile', usage='bio <bio>', call_on_message=True)
    async def bio(self, message, bio):
        user = RankedUser.select(RankedUser).where(
            RankedUser.user_id == message.author.id, RankedUser.server == message.server.id
        )

        if user.exists():
            update_bio = RankedProfile.update(bio=bio).where(
                RankedProfile.user_id == message.author.id
            )

            update_bio.execute()

    @command(regex='^background <?(.*?)>?$', description='set a background for your profile',
             usage='background <url>', call_on_message=True)
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

        user = RankedUser.select(RankedUser).where(
            RankedUser.user_id == message.author.id, RankedUser.server == message.server.id
        )

        if user.exists():
            update_bckg = RankedProfile.update(background=url).where(
                RankedProfile.user_id == message.author.id
            )

            update_bckg.execute()

    @command(description='view the top 10 ranked players in the server', usage='top', call_on_message=True)
    async def top(self, message):
        top = []
        for x, ru in enumerate(
                RankedUser.select().where(RankedUser.server == message.server.id).order_by(-RankedUser.xp)):
            if x != 10:
                top.append((ru.user_id, ru.xp))

        code_block = '```\n'
        for x, ru in enumerate(top):
            u = message.server.get_member(ru[0])
            code_block += f'[{x+1}]\t>\t{u.name}\n\t\t\t  Total XP: {ru[1]}\n'

        code_block += '\n```'
        await self.mbot.send_message(message.channel, code_block)
