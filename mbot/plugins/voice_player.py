import logging
import asyncio
from collections import deque, defaultdict

from youtube_dl import YoutubeDL

from ..plugin import BasePlugin
from ..command import command
from ..utils import long_running_task


log = logging.getLogger(__name__)


class Player(object):
    __slots__ = ('player', 'q_loop', 'playlist', 'now_playing', 'done_playing')

    def __init__(self):
        self.player = None
        self.q_loop = None
        self.playlist = deque()
        self.now_playing = ''
        self.done_playing = asyncio.Event()


class VoicePlayer(BasePlugin):
    def __init__(self, mbot):
        super().__init__(mbot)

        self.players = defaultdict(Player)

    @long_running_task()
    def get_url_info(self, url):
        ytdl = YoutubeDL()
        info = ytdl.extract_info(url, download=False)

        if 'twitch' in url:
            # Twtich has the title and description mixed up...
            title = info.get('description')
            description = info.get('title')

            info['title'] = title
            info['description'] = description

        return info

    async def join_voice_channel(self, server, channel_name=None, channel_obj=None):
        if server.voice_client and server.voice_client.is_connected():
            if (channel_name == server.voice_client.channel.name) or (channel_obj == server.voice_client.channel):
                return
            else:
                await server.voice_client.disconnect()

        # Providing a `channel_obj` argument overrides the `channel_name` and joins the
        # the channel to which the object points.
        if channel_obj is not None:
            await self.mbot.join_voice_channel(channel_obj)
            return

        for channel in server.channels:
            if (str(channel.type) == 'voice') and (channel.name == channel_name):
                await self.mbot.join_voice_channel(channel)
                break

    async def play_url(self, message, url, channel_name=None, after=None):
        if channel_name is not None:
            await self.join_voice_channel(message.server, channel_name=channel_name)
        else:
            if message.server.voice_client is None or not message.server.voice_client.is_connected():
                if message.author.voice.voice_channel is not None:
                    await self.join_voice_channel(message.server, channel_obj=message.author.voice.voice_channel)
                else:
                    await self.mbot.send_message(message.channel, '*I am not connected to any voice channels...*')
                    return

        if self.players[message.server.id].player is not None:
            self.players[message.server.id].player.stop()

        info = await self.get_url_info(url, _message=message)
        await self.mbot.send_message(message.channel, f':notes: | Playing | **{info["title"]}**')

        self.players[message.server.id].player = await message.server.voice_client.create_ytdl_player(url, after=after)
        self.players[message.server.id].player.volume = 0.5
        self.players[message.server.id].player.start()

    @command(regex='^join(?: (.*?))?$', description='join a voice channel', usage='join [channel]')
    async def join(self, message, channel_name=None):
        if channel_name:
            await self.join_voice_channel(message.server, channel_name=channel_name)
        else:
            await self.join_voice_channel(message.server, channel_obj=message.author.voice.voice_channel)

    @command(regex='^play <?(.*?)>?(?: (.*?))?$', description='stream audio from a url',
             usage='play <url> [channel]', cooldown=5)
    async def play(self, message, url, channel_name=None):
        await self.play_url(message, url, channel_name)

    @command(regex='^stop$', description='stop the player', usage='stop')
    async def stop(self, message):
        if self.players[message.server.id].player is not None:
            self.players[message.server.id].player.stop()
            await message.server.voice_client.disconnect()
            del self.players[message.server.id]

    @command(regex='^volume (\d+\.\d+)$', description='adjust the volume of the player', usage='volume <%>')
    async def volume(self, message, vol):
        if self.players[message.server.id].player is not None:
            self.players[message.server.id].player.volume = float(vol)

    @command(regex='^queue add <?(.*?)>?$', name='queue add', description='schedule an audio stream',
             usage='queue add <url>')
    async def queue_add(self, message, url):
        info = await self.get_url_info(url, _message=message)
        await self.mbot.send_message(message.channel, f':notes: | Scheduled | **{info["title"]}**')
        self.players[message.server.id].playlist.append(url)

    @command(regex='^queue list$', name='queue list', description='list the current stream queue', usage='queue list')
    async def queue_list(self, message):
        print(self.players[message.server.id].playlist)

    async def queue_loop(self, server):
        await self.mbot.wait_until_ready()

        while not self.mbot.is_closed:
            await self.players[server.id].done_playing.wait()

            if self.players[server.id].playlist and server.voice_client.is_connected():
                self.players[server.id].player = \
                    await server.voice_client.create_ytdl_player(
                        self.players[server.id].playlist.popleft(), after=self.players[server.id].done_playing.set
                    )

                self.players[server.id].player.volume = 0.5
                self.players[server.id].player.start()

            self.players[server.id].done_playing.clear()
            await asyncio.sleep(5)

    @command(regex='^queue start(?: (.*?))?$', name='queue start', description='start the queue',
             usage='queue start [channel]', cooldown=5)
    async def queue_play(self, message, channel_name=None):
        if message.server.voice_client is None or not message.server.voice_client.is_connected():
            await self.join_voice_channel(message.server, channel_name)

        if self.players[message.server.id].playlist and message.server.voice_client is not None:
            if self.players[message.server.id].player:
                self.players[message.server.id].player.stop()

            if not self.players[message.server.id].q_loop:
                self.players[message.server.id].q_loop = self.mbot.loop.create_task(self.queue_loop(message.server))

            self.players[message.server.id].done_playing.set()
