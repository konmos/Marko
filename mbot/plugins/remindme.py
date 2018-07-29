import time
import asyncio
from datetime import datetime, timezone

import discord
from bson.objectid import ObjectId

from ..plugin import BasePlugin
from ..command import command


class Reminders(BasePlugin):
    def __init__(self, mbot):
        super().__init__(mbot)

        self.reminder_db = self.mbot.mongo.plugin_data.reminders

        # Time unit: second multiplier
        self.time_conversion = {
            'd': 24*60*60,
            'h': 60*60,
            'm': 60,
        }

        self.mbot.loop.create_task(self.check_pending_reminders())

    async def check_pending_reminders(self):
        await self.mbot.wait_until_ready()

        while not self.mbot.is_closed:
            tstamp = time.time()

            async for document in self.reminder_db.find({'expires': {'$lte': tstamp}}):
                await self.mbot.send_message(discord.User(id=document['user_id']), document['message'])
                await self.reminder_db.delete_one({'_id': ObjectId(document['_id'])})

            await asyncio.sleep(60)

    @command(regex='^remindme (?:in )?(\d+) (days?|hours?|minutes?) (.*?)$', description='set a friendly reminder',
             usage='remindme <n> (days|hours|minutes) <reminder>', cooldown=10)
    async def remindme(self, message, num=None, unit=None, msg=None):
        await self.reminder_db.insert_one({
            'user_id': message.author.id,
            'expires': time.time() + self.time_conversion[unit[0]] * int(num),
            'message': msg
        })

        await self.mbot.send_message(message.channel, f':date: | Reminder set for {message.author.mention}')

    @command()
    async def myreminders(self, message):
        reminders = []

        async for r in self.reminder_db.find({'user_id': message.author.id}).sort('expires', 1).limit(8):
            time_str = datetime.fromtimestamp(r['expires']).strftime('%Y-%m-%d %H:%M:%S')
            # noinspection PyArgumentList
            utc_offset = datetime.now(timezone.utc).astimezone().strftime('%z')

            reminders.append((r['message'], f'{time_str} {utc_offset}'))

        if not reminders:
            return await self.mbot.send_message(
                message.channel,
                '**You have not set any reminders!**'
            )

        m = ''
        for reminder in reminders:
            m += f'{reminder[1]}\n\t> {reminder[0]}\n\n'

        return await self.mbot.send_message(
            message.channel,
            f'**Your most recent reminders:**\n\n```{m}```'
        )
