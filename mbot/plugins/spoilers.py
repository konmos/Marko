import io
import os

import asyncio
import imageio
from PIL import Image, ImageDraw, ImageFont
from discord import Forbidden

from ..plugin import BasePlugin
from ..command import command
from ..utils import long_running_task


class SpoilerBot(BasePlugin):
    @long_running_task()
    def create_image(self, text):
        img = Image.new('RGB', (500, 90), (60, 63, 68))
        draw = ImageDraw.Draw(img)
        font = ImageFont.truetype(os.path.join('data', 'SourceSansPro-Regular.ttf'), 18)
        w, h = draw.textsize(text, font=font)
        draw.text(((502 - w) / 2, (92 - h) / 2), text, (192, 186, 158), font=font)
        border = Image.new('RGB', (502, 92), (192, 186, 158))
        border.paste(img, (1, 1))
        buffer = io.BytesIO()
        border.save(buffer, format='jpeg', mode='wb')
        buffer.seek(0)
        img.close()
        return buffer

    @long_running_task()
    def create_gif(self, images):
        im = []
        for image in images:
            im.append(imageio.imread(image, format='jpeg'))
            image.seek(0)

        buffer = io.BytesIO()
        imageio.mimwrite(buffer, im, duration=1, format='gif')
        buffer.seek(0)
        return buffer

    @command(regex='^spoiler (.*?)$')
    async def spoiler(self, message, spoiler):
        try:
            await self.mbot.delete_message(message)
        except Forbidden:
            msg = await self.mbot.send_message(message.channel, '*I cannot do that...* :cry:')
            await asyncio.sleep(5)
            await self.mbot.delete_message(msg)
            return

        a = await self.create_image('Hover to view spoilers.')
        b = await self.create_image(spoiler)
        gif = await self.create_gif((a, b, b, b))

        await self.mbot.send_message(message.channel, f'*{message.author.mention} says...*')
        await self.mbot.send_file(message.channel, gif, filename='spoiler.gif')

        a.close()
        b.close()
        gif.close()
