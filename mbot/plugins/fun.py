import io
import random
import mimetypes

import aiohttp
from wand.image import Image

from ..plugin import BasePlugin
from ..command import command
from ..utils import long_running_task


class Fun(BasePlugin):
    @long_running_task()
    def _magik(self, image_blob, scale=None):
        image_bytes = io.BytesIO()

        with Image(blob=image_blob) as i:
            i.format = 'jpg'
            i.alpha_channel = True
            i.transform(resize='800x800>')

            i.liquid_rescale(
                width=int(i.width * 0.5),
                height=int(i.height * 0.5),
                delta_x=int(0.5 * scale) if scale else 1,
                rigidity=0
            )

            i.liquid_rescale(
                width=int(i.width * 1.5),
                height=int(i.height * 1.5),
                delta_x=scale or 2,
                rigidity=0
            )

            i.save(file=image_bytes)
            image_bytes.seek(0)

        return image_bytes

    @command(regex='^magik(?: (.*?))?$', name='magik')
    async def magik(self, message, url=None):
        if not url:
            url = message.author.avatar_url or message.author.default_avatar_url

        try:
            with aiohttp.ClientSession() as client:
                async with client.head(url) as h:
                    size = int(h.headers.get('Content-Length', 0))
                    mimetype = h.headers.get('Content-Type')

                if not mimetype:
                    mimetype = mimetypes.guess_type(url=url)[0]

                if size > 10 * 1024 * 1024 or not mimetype.startswith('image'):
                    return await self.mbot.send_message(
                        message.channel,
                        '**This file is either not an image or is too large!**'
                    )

                async with client.get(url) as r:
                    image_buffer = await r.read()
        except:
            return await self.mbot.send_message(
                message.channel, '*Something went wrong...*'
            )

        im = await self._magik(image_buffer)
        await self.mbot.send_file(message.channel, im, filename='magik.jpg')

    @command(regex='^dice(?: (\d{0,2})d(\d{1,2}))?$')
    async def dice(self, message, no_dice=None, no_faces=None):
        a, x = int(no_dice or 1), int(no_faces or 6)
        result = sum([random.randint(1, x) for _ in range(a)])

        await self.mbot.send_message(
            message.channel,
            f'The result of your **{a}d{x}** is **{result}**.'
        )

    @command(regex='^choose (.*?)$')
    async def choose(self, message, inputs):
        choices = [x.strip() for x in inputs.split(';') if x.strip()]

        if not choices or len(choices) == 1:
            return await self.mbot.send_message(
                message.channel,
                '**Please give me at least two choices...**'
            )

        await self.mbot.send_message(
            message.channel,
            f'**I choose `{random.choice(choices)}`!**'
        )

    @command()
    async def coin(self, message):
        await self.mbot.send_message(
            message.channel,
            f'The coin landed **{random.choice(["heads", "tails"])}**!'
        )

    @command(regex='^8ball .+?$', name='8ball')
    async def eight_ball(self, message):
        response = random.choice([
            'It is certain.',
            'It is decidedly so.',
            'Without a doubt.',
            'Yes - definitely.',
            'You may rely on it.',
            'As I see it, yes.',
            'Most likely.',
            'Outlook good.',
            'Yes.',
            'Signs point to yes.',
            'Reply hazy, try again.',
            'Ask again later.',
            'Better not tell you now.',
            'Cannot predict now.',
            'Concentrate and ask again.',
            'Don\'t count on it.',
            'My reply is no.',
            'My sources say no.',
            'Outlook not so good.',
            'Very doubtful.'
        ])

        await self.mbot.send_message(message.channel, response)
