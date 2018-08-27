import os
import random

import praw
import discord
from prawcore import exceptions
from praw.exceptions import ClientException

from ..plugin import BasePlugin
from ..command import command
from ..utils import long_running_task


class Reddit(BasePlugin):
    def __init__(self, mbot):
        super().__init__(mbot)

        self.client_id = self.mbot.config.plugin_data.get('reddit', {}).get('client_id')
        self.client_secret = self.mbot.config.plugin_data.get('reddit', {}).get('client_secret')

        self.user_agent = f'{os.name}:markobot.xyz:{self.client_id} (/u/markothebot)'

        try:
            self.reddit = praw.Reddit(
                client_id=self.client_id,
                client_secret=self.client_secret,
                user_agent=self.user_agent
            )
        except ClientException:
            self.reddit = None

    async def _config_check(self, channel=None):
        if self.client_id and self.client_secret and self.reddit:
            return True

        if channel:
            await self.mbot.send_message(
                channel, '*Well... This shouldn\'t happen. I am missing my reddit config.* :cry:'
            )

        return False

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
        if not await self._config_check(message.channel):
            return

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
        if not await self._config_check(message.channel):
            return

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
