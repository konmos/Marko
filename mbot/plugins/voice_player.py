import time
import math
import random
import logging
import asyncio
from collections import defaultdict

from pymongo.errors import PyMongoError
from discord import Channel
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
        self.done_playing = asyncio.Event()


class VoicePlayer(BasePlugin):
    def __init__(self, mbot):
        super().__init__(mbot)

        self.players = defaultdict(Player)
        self.player_db = self.mbot.mongo.plugin_data.voice_player

    async def on_ready(self):
        # If we've been disconnected, reset the `now_playing` field in the db.
        await self.player_db.update_many(
            {}, {'$set': {'now_playing': None}}
        )

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

        info['url'] = url
        return info

    async def _create_playlist(self, server_id):
        await self.player_db.insert_one(
            {
                'server_id': server_id,
                'volume': 0.2,
                'shuffle': False,
                'playlist': [],
                'now_playing': None
            }
        )

    async def ensure_playlist_exists(self, server_id):
        # Check if mongo document exists, create it if not.
        doc = await self.player_db.find_one({'server_id': server_id})

        if not doc:
            await self._create_playlist(server_id)

    async def get_playlist(self, server_id):
        await self.ensure_playlist_exists(server_id)
        return await self.player_db.find_one({'server_id': server_id})

    async def add_to_playlist(self, server_id, user, media_info):
        await self.ensure_playlist_exists(server_id)

        try:
            ret = await self.player_db.update_one(
                {'server_id': server_id},
                {'$push': {'playlist': {
                    'id': media_info['id'],
                    'title': media_info['title'],
                    'url': media_info['url'],
                    'duration': media_info.get('duration'),
                    'is_live': media_info.get('is_live') or False,
                    'user': user,
                    'timestamp': time.time()
                }}}
            )

            return ret.modified_count > 0
        except PyMongoError:
            return False

    async def remove_from_playlist(self, server_id, media_id):
        await self.ensure_playlist_exists(server_id)

        try:
            ret = await self.player_db.update_one(
                {'server_id': server_id},
                {'$pull': {'playlist': {'id': media_id}}}
            )

            return ret.modified_count > 0
        except PyMongoError:
            return False

    async def set_volume(self, server_id, volume):
        await self.ensure_playlist_exists(server_id)

        try:
            ret = await self.player_db.update_one(
                {'server_id': server_id},
                {'$set': {'volume': volume}}
            )

            return ret.modified_count > 0
        except PyMongoError:
            return False

    async def set_shuffle(self, server_id):
        await self.ensure_playlist_exists(server_id)

        try:
            ret = await self.player_db.update_one(
                {'server_id': server_id},
                {'$set': {'shuffle': True}}
            )

            return ret.modified_count > 0
        except PyMongoError:
            return False

    async def set_unshuffle(self, server_id):
        await self.ensure_playlist_exists(server_id)

        try:
            ret = await self.player_db.update_one(
                {'server_id': server_id},
                {'$set': {'shuffle': False}}
            )

            return ret.modified_count > 0
        except PyMongoError:
            return False

    async def set_playing(self, server_id, user, media_info):
        await self.ensure_playlist_exists(server_id)

        if media_info.get('id') is not None:
            try:
                ret = await self.player_db.update_one(
                    {'server_id': server_id},
                    {'$set': {'now_playing': {
                        'id': media_info['id'],
                        'title': media_info['title'],
                        'url': media_info['url'],
                        'duration': media_info.get('duration'),
                        'is_live': media_info.get('is_live') or False,
                        'user': user,
                        'timestamp': time.time(),
                        'skip_votes': {
                            'num_votes': 0,
                            'users': []
                        }
                    }}}
                )

                return ret.modified_count > 0
            except PyMongoError:
                return False

    async def reset_playing(self, server_id):
        try:
            ret = await self.player_db.update_one(
                {'server_id': server_id},
                {'$set': {'now_playing': None}}
            )

            return ret.modified_count > 0
        except PyMongoError:
            return False

    @staticmethod
    def is_voice_connected(server):
        return server.voice_client and server.voice_client.is_connected()

    def kill_queue(self, server):
        if self.players[server].q_loop is not None:
            try:
                self.players[server].q_loop.cancel()
            except:
                pass

            self.players[server].done_playing.set()

    def stop_player(self, server):
        if self.players[server].player is not None:
            self.players[server].player.stop()

    def is_current_channel_empty(self, message):
        # A voice channel is considered empty if there are no users in it,
        # or if the only users in it are the message author and/or the bot itself.
        if self.is_voice_connected(message.server):
            if message.author in message.server.voice_client.channel.voice_members:
                max_users = 2
            else:
                max_users = 1

            if not len(message.server.voice_client.channel.voice_members) <= max_users:
                return False

        return True

    async def check_empty_channel(self, message):
        channel_empty = self.is_current_channel_empty(message)

        if channel_empty or message.author.permissions_in(message.channel).administrator:
            return True

        await self.mbot.send_message(
            message.channel, '**You cannot restart the player while others are listening!**'
        )

    async def _join_voice_channel(self, server, channel):
        '''
        Join a voice channel in a server. This disconnects the client if it exists, and rejoins.
        This should not be used to move channels.

        :param server: A `Server` object
        :param channel: Either a server object of a string representing the channel name.
        :return: Return value of `is_voice_connected(server)`
        '''
        await self.ensure_playlist_exists(server.id)

        if self.is_voice_connected(server):
            if channel == server.voice_client.channel.name or channel == server.voice_client.channel:
                # We're already in the correct channel.
                return
            else:
                # Disconnect first, if we want to rejoin to a different channel.
                await server.voice_client.disconnect()

        if isinstance(channel, Channel):
            await self.mbot.join_voice_channel(channel)
        elif isinstance(channel, str):
            for ch in server.channels:
                if str(ch.type) == 'voice' and ch.name == channel:
                    await self.mbot.join_voice_channel(ch)
                    break

    async def join_voice_channel(self, message, channel_name):
        if channel_name is not None:
            await self._join_voice_channel(message.server, channel=channel_name)
        elif message.author.voice.voice_channel is not None:
            await self._join_voice_channel(message.server, channel=message.author.voice.voice_channel)

        return self.is_voice_connected(message.server)

    async def play_url(self, message, url, after=None, info=None, kill_q=True):
        self.stop_player(message.server.id)

        if kill_q:
            self.kill_queue(message.server.id)

        if info is None:
            info = await self.get_url_info(url, _message=message)

        playlist = await self.get_playlist(message.server.id)

        self.players[message.server.id].player = await message.server.voice_client.create_ytdl_player(url, after=after)
        self.players[message.server.id].player.volume = playlist['volume']
        self.players[message.server.id].player.start()

        await self.set_playing(message.server.id, f'{message.author.name}#{message.author.discriminator}', info)
        return info

    @command(regex='^join(?: (.*?))?$', description='join a voice channel', usage='join [channel]')
    async def join(self, message, channel_name=None):
        if not await self.check_empty_channel(message):
            return

        connected = await self.join_voice_channel(message, channel_name)

        if not connected:
            await self.mbot.send_message(message.channel, '*I could not connect to any voice channels...*')

    @command(regex='^play <?(.*?)>?(?: (.*?))?$', description='stream audio from a url',
             usage='play <url> [channel]', cooldown=10)
    async def play(self, message, url, channel_name=None):
        if not await self.check_empty_channel(message):
            return

        connected = await self.join_voice_channel(message, channel_name)

        if not connected:
            return await self.mbot.send_message(message.channel, '*I could not connect to any voice channels...*')

        info = await self.play_url(message, url)
        await self.mbot.send_message(message.channel, f':notes: | Playing | **{info["title"]}**')

    @command(regex='^stop$', description='stop the player', usage='stop')
    async def stop(self, message):
        if not await self.check_empty_channel(message):
            return

        self.stop_player(message.server.id)
        self.kill_queue(message.server.id)
        del self.players[message.server.id]

        await message.server.voice_client.disconnect()
        await self.reset_playing(message.server.id)

    @command(regex='^volume (\d+\.\d+)$', description='adjust the volume of the player', usage='volume <%>')
    async def volume(self, message, vol):
        await self.set_volume(message.server.id, float(vol))

        if self.players[message.server.id].player is not None:
            self.players[message.server.id].player.volume = float(vol)

    @command(regex='^queue add <?(.*?)>?$', name='queue add', description='schedule an audio stream',
             usage='queue add <url>')
    async def queue_add(self, message, url):
        info = await self.get_url_info(url, _message=message)
        await self.add_to_playlist(message.server.id, f'{message.author.name}#{message.author.discriminator}', info)
        await self.mbot.send_message(message.channel, f':notes: | Scheduled | **{info["title"]}**')

    @command(regex='^queue list$', name='queue list', description='list the current stream queue', usage='queue list')
    async def queue_list(self, message):
        await self.ensure_playlist_exists(message.server.id)
        await self.mbot.send_message(
            message.channel,
            f'**View the playlist for this server at https://markobot.xyz/playlist/{message.server.id}**'
        )

    async def queue_loop(self, message):
        server = message.server

        await self.mbot.wait_until_ready()

        while not self.mbot.is_closed:
            await self.players[server.id].done_playing.wait()
            playlist = await self.get_playlist(server.id)

            if playlist['playlist'] and self.is_voice_connected(message.server):
                if playlist['shuffle']:
                    item = random.choice(playlist['playlist'])
                else:
                    item = playlist['playlist'][0]

                await self.play_url(
                    message, item['url'], info=item, after=self.players[server.id].done_playing.set, kill_q=False
                )
                await self.remove_from_playlist(server.id, item['id'])
            else:
                return await self.reset_playing(message.server.id)

            self.players[server.id].done_playing.clear()
            await asyncio.sleep(5)

    @command(regex='^queue start(?: (.*?))?$', name='queue start', description='start the queue',
             usage='queue start [channel]', cooldown=10)
    async def queue_play(self, message, channel_name=None):
        if not await self.check_empty_channel(message):
            return

        connected = await self.join_voice_channel(message, channel_name)

        if not connected:
            return await self.mbot.send_message(message.channel, '*I could not connect to any voice channels...*')

        playlist = await self.get_playlist(message.server.id)

        if playlist['playlist']:
            self.stop_player(message.server.id)
            self.kill_queue(message.server.id)
            self.players[message.server.id].q_loop = self.mbot.loop.create_task(self.queue_loop(message))
            self.players[message.server.id].done_playing.set()

    @command(description='shuffle the playlist', usage='shuffle')
    async def shuffle(self, message):
        ret = await self.set_shuffle(message.server.id)

        if ret:
            await self.mbot.send_message(message.channel, ':ok_hand: **Set playlist to shuffle!**')
        else:
            await self.mbot.send_message(message.channel, ':cry: **Could not set playlist to shuffle!**')

    @command(description='unshuffle the playlist', usage='unshuffle')
    async def unshuffle(self, message):
        ret = await self.set_unshuffle(message.server.id)

        if ret:
            await self.mbot.send_message(message.channel, ':ok_hand: **Unshuffled playlist!**')
        else:
            await self.mbot.send_message(message.channel, ':cry: **Could not unshuffle playlist!**')

    @command(description='vote to skip the current song', usage='skip', name='skip')
    async def skip_song(self, message):
        playlist = await self.get_playlist(message.server.id)

        if not self.is_voice_connected(message.server) or playlist['now_playing'] is None:
            return await self.mbot.send_message(message.channel, ':cry: **Nothing seems to be playing...**')

        if message.author.id in playlist['now_playing']['skip_votes']['users']:
            return await self.mbot.send_message(message.channel, '**You\'ve already voted!**')

        num_users = len(message.server.voice_client.channel.voice_members)

        await self.player_db.update_one(
            {'server_id': message.server.id},
            {'$inc': {'now_playing.skip_votes.num_votes': 1}}
        )

        await self.player_db.update_one(
            {'server_id': message.server.id},
            {'$push': {'now_playing.skip_votes.users': message.author.id}}
        )

        votes = playlist['now_playing']['skip_votes']['num_votes'] + 2  # We add 2 because we ignore the bot.

        # To skip a song, the number of votes must be greater than the `ceil` of 60%
        # the number of users in the voice channel.
        if votes >= math.ceil(num_users * 0.6):
            await self.mbot.send_message(message.channel, ':ok_hand: **Skipping song.**')
            self.stop_player(message.server.id)
            await self.reset_playing(message.server.id)
            self.players[message.server.id].done_playing.set()
        else:
            diff = math.ceil(num_users * 0.6) - votes
            await self.mbot.send_message(
                message.channel,
                f':ok_hand: **Voted to skip... {diff} more votes needed to skip this song!**'
            )
