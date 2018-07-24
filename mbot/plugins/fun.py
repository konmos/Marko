import io
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
