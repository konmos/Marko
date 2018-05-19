import aiohttp
from bs4 import BeautifulSoup

from ..plugin import BasePlugin
from ..command import command


class Games(BasePlugin):
    @command(regex='^steam (.*?)$', description='grab a steam sig', usage='steam [id]', cooldown=5)
    async def steam(self, message, steamid):
        with aiohttp.ClientSession() as client:
            async with client.post('https://steamprofile.com', data={'steamid': steamid}) as r:
                soup = BeautifulSoup(await r.text(), 'html.parser')

                for meta in soup.find_all('meta'):
                    if meta.get('property') == 'og:image:url':
                        sig = meta.get('content')
                        break

        await self.mbot.send_file(
            destination=message.channel,
            fp=f'https://badges.steamprofile.com/profile/default/steam/{sig}'
        )
