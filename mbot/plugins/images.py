import random
import aiohttp
from bs4 import BeautifulSoup

from ..plugin import BasePlugin
from ..command import command


HEADERS = {'User-Agent': r'Mozilla/5.0 (Windows NT 6.1; WOW64; rv:40.0) Gecko/20100101 Firefox/40.1'}


class ImageEngine(BasePlugin):
    '''
    Extracts all imgur links from chosen subreddits. *Only supports imgur at the moment!!*
    This simply parses html and grabs random links. For more advanced imgur operations
    use the imgur plugin which uses the API.
    '''
    def __init__(self, mbot):
        super().__init__(mbot)

        self.already_done = set()

    async def extract_imgur(self, subreddit):
        links = set()

        with aiohttp.ClientSession() as client:
            async with client.get(rf'https://imgur.com/r/{subreddit}/new', headers=HEADERS) as r:
                soup = BeautifulSoup(await r.text(), 'html.parser')

                # Extract all imgur links...
                for a in soup.find_all(lambda tag: tag.name == 'a' and subreddit in tag.get('href')):
                    links.add(f'https://imgur.com{a.get("href")}')

        if self.already_done:
            return tuple(links - self.already_done)
        else:
            return tuple(links)

    async def image(self, message, subreddit):
        await self.mbot.send_typing(message.channel)

        rand = random.choice(await self.extract_imgur(subreddit))
        self.already_done.add(rand)

        await self.mbot.send_message(message.channel, rand)

    @command(regex='^wallpaper$', usage='wallpaper', description='get a random wallpaper from reddit')
    async def wallpaper(self, message):
        await self.image(message, 'wallpapers')

    @command(regex='^nsfwallpaper$', name='nsfwallpaper', usage='nsfwallpaper',
             description='get random NSFW wallpaper')
    async def nsfw_wallpaper(self, message):
        await self.image(message, 'NSFW_Wallpapers')

    @command(regex='^image (.*?)$', name='image', usage='image <subreddit>',
             description='return random image from any subreddit')
    async def image_cmd(self, message, subreddit):
        await self.image(message, subreddit)
