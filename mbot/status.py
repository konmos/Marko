import random

import asyncio
from discord import Game


class Status(object):
    # Status:
    #   (name, url, type, timeout)
    # type:
    #   0: Playing, 1: Streaming, 2: Listening, 3: Watching (Undocumented!?)
    statuses = [
        ('Anime', None, 3, 60*10),
        ('Gwent', None, 0, 60*10),
        ('markobot.xyz', None, 0, 60*15),
        ('m!help', None, 0, 60*15),
        ('Spotify', None, 2, 60*10),
        ('with Playing with', None, 0, 60*10),
        ('with fire', None, 0, 60*10),
        ('chess for years', None, 0, 60*10),
        ('in {servers} guilds', None, 0, 60*10),
        ('the world burn', None, 3, 60*10),
        ('you', None, 3, 60*10)
    ]

    def __init__(self, mbot):
        self.mbot = mbot
        self.mbot.loop.create_task(self.status_task())

        self.current_status = None

    def get_status(self):
        status = random.choice(self.statuses)

        formatted_status = (
            status[0].format(servers=len(self.mbot.servers)),
            status[1],
            status[2],
            status[3]
        )

        return formatted_status

    async def status_task(self):
        await self.mbot.wait_until_ready()

        while not self.mbot.is_closed:
            status = self.get_status()
            self.current_status = status

            await self.mbot.change_presence(
                game=Game(name=status[0], url=status[1], type=status[2])
            )

            await asyncio.sleep(status[3])
