import os
import random

import praw
import discord
from prawcore import exceptions

from ..config import Config
from ..plugin import BasePlugin
from ..command import command
from ..utils import long_running_task


_cfg = Config(os.environ['mbot_config'])
if _cfg.plugin_data.get('reddit', {}).get('client_id', '') and \
    _cfg.plugin_data.get('reddit', {}).get('client_secret', ''):

    class Reddit(BasePlugin):
        def __init__(self, mbot):
            super().__init__(mbot)

            self.client_id = self.mbot.config.plugin_data.get('reddit', {}).get('client_id', '')
            self.client_secret = self.mbot.config.plugin_data.get('reddit', {}).get('client_secret', '')

            self.user_agent = f'{os.name}:github.com/konmos/MarkoBot:v0-{self.client_id[:6]} (/u/markothebot)'

            self.reddit = praw.Reddit(
                client_id=self.client_id,
                client_secret=self.client_secret,
                user_agent=self.user_agent
            )

        @long_running_task()
        def _get_submissions(self, subreddit, sort=None, limit=25):
            try:
                reddit = self.reddit.subreddit(subreddit)

                submissions = {
                    'hot': reddit.hot,
                    'controversial': reddit.controversial,
                    'gilded': reddit.gilded,
                    'new': reddit.new,
                    'rising': reddit.rising,
                    'top': reddit.top
                }.get(sort, reddit.new)

                posts = []

                for post in submissions(limit=limit):
                    posts.append(post)
            except (exceptions.RequestException, exceptions.ResponseException):
                posts = []

            return posts

        async def _grab_image(self, subreddit, sort=None, _message=None):
            images = []
            submissions = await self._get_submissions(subreddit, sort, _message=_message)

            for post in submissions:
                try:
                    if post.url.endswith('.jpg') or post.url.endswith('.png'):
                        images.append((post.title, post.url))
                except AttributeError:
                    pass

            if images:
                return random.choice(images)

            return []

        async def _grab_post(self, subreddit, sort=None, _message=None):
            posts = []
            submissions = await self._get_submissions(subreddit, sort, _message=_message)

            for post in submissions:
                try:
                    if post.is_self:
                        posts.append((post.title, post.selftext, post.author, post.score, post.id))
                except AttributeError:
                    pass

            if posts:
                return random.choice(posts)

            return []

        @command(regex='^image (.*?)(?: (.*?))?$', usage='image <subreddit>',
                 description='grab a random image from a subreddit', cooldown=5)
        async def image(self, message, subreddit, sort=None):
            im = await self._grab_image(subreddit, sort, _message=message)

            if im:
                await self.mbot.send_file(message.channel, im[1], content=f'**{im[0]}**')
            else:
                await self.mbot.send_message(
                    message.channel,
                    f'**{message.author.mention} I couldn\'t find anything...** :cry:'
                )

        @command(regex='^reddit (.*?)(?: (.*?))?$', usage='reddit <subreddit>',
                 description='grab a random post from a subreddit', cooldown=5)
        async def reddit(self, message, subreddit, sort=None):
            post = await self._grab_post(subreddit, sort, _message=message)

            if post:
                embed = discord.Embed(
                    title=f'[{post[3]}] {post[0]} ({post[4]})',
                    description=f'{post[1][:1024]}\n...',
                    colour=0x0277bd
                )

                embed.set_footer(text=f'/u/{post[2]}')

                await self.mbot.send_message(message.channel, embed=embed)
            else:
                await self.mbot.send_message(
                    message.channel,
                    f'**{message.author.mention} I couldn\'t find anything...** :cry:'
                )
