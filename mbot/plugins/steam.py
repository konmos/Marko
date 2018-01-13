import re

import aiohttp

from ..plugin import BasePlugin
from ..command import command


class SteamSig(BasePlugin):
    @command(regex='^steam (.*?)$', description='grab a steam sig', usage='steam [id]', cooldown=5)
    async def steam(self, message, steamid):
        with aiohttp.ClientSession() as client:
            async with client.post('https://steamprofile.com', data={'steamid': steamid}) as r:
                sig = re.search('\d+\.png', await r.text(), re.M)

        await self.mbot.send_file(
            destination=message.channel,
            fp=f'https://badges.steamprofile.com/profile/default/steam/{sig.group(0)}'
        )
