import time
import asyncio
import discord
import peewee as pe

from ..plugin import BasePlugin
from ..command import command
from ..database import BaseModel


class Reminder(BaseModel):
    user_id = pe.CharField()
    sleep = pe.IntegerField()
    timestamp = pe.DoubleField()
    reminder_msg = pe.CharField()


class ReminderBot(BasePlugin):
    def __init__(self, mbot):
        super().__init__(mbot)

        # Time unit: second multiplier
        self.time_conversion = {
            'day': 24*60*60,
            'days': 24*60*60,
            'hour': 60*60,
            'hours': 60*60,
            'minute': 60,
            'minutes': 60
        }

    async def on_ready(self):
        self.mbot.db.db.create_table(Reminder, True)
        self.mbot.loop.create_task(self.check_pending_reminders())

    async def check_pending_reminders(self):
        await self.mbot.wait_until_ready()

        while not self.mbot.is_closed:
            for pending in Reminder.select().where(time.time() - Reminder.timestamp >= Reminder.sleep):
                await self.mbot.send_message(discord.User(id=pending.user_id), pending.reminder_msg)
                pending.delete_instance()

            await asyncio.sleep(60)

    @command(regex='^remindme (?:in )?(\d+) (days?|hours?|minutes?) (.*?)$', description='set a friendly reminder',
             usage='remindme <n> (days|hours|minutes) <reminder>', cooldown=10)
    async def remindme(self, message, num=None, unit=None, msg=None):
        reminder = Reminder.create(
            user_id = message.author.id,
            sleep = self.time_conversion[unit] * int(num),
            timestamp = time.time(),
            reminder_msg = msg
        )

        reminder.save()

        await self.mbot.send_message(message.channel, f':date: | Reminder set for {message.author.mention}')
