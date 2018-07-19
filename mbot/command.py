import re
import time
import logging
from functools import wraps

import asyncio
from discord import Forbidden

log = logging.getLogger(__name__)


class ABORT_COMMAND(object):
    '''
    Custom type which indicates that the execution of a command should be aborted.
    This should be only used from within the command handler method of a plugin.
    This allows greater control over the execution of a command on a per-plugin basis. If
    this is not returned explicitly, the command will be processed and executed as normal.
    '''


def command(*, regex='', usage='', description='', name='', call_on_message=False,
            su=False, perms=None, cooldown=None, aliases=None, nsfw=False, mutex=None):
    '''
    Utility function to make creating commands easier. Takes care of common tasks such as
    pattern matching, permissions, roles, usages, etc... When a message matches the `regex`,
    the decorated function is called instead of the `on_message` method.
    '''

    def decorator(func):
        if aliases:
            pat, cmd_name = regex or f'^{name or func.__name__}$', name or func.__name__

            pattern = re.compile(pat.replace(
                cmd_name,
                f'(?:{cmd_name}|{"|".join(aliases)})'
            ))
        else:
            # Pattern defaults to function name.
            pattern = re.compile(regex or f'^{name or func.__name__}$')

        @wraps(func)
        async def wrapper(self, message):
            match = pattern.match(message.content)

            # This is checked in the main loop anyway, but we'll check anyway in case
            # this gets called from outside the loop.
            if not match:
                return

            ch = await self.mbot.plugin_manager.get_command_handler(wrapper.info['plugin'])(message, wrapper)
            if ch is not None and issubclass(ch, ABORT_COMMAND):
                return

            log.debug(f'running command {wrapper.info["name"]} in server {message.server.id} {match.groups()}')

            # Check if command history exists. Create it if not.
            doc = await self.mbot.mongo.cmd_history.find_one(
                {'user_id': message.author.id}
            )

            if doc is None:
                await self.mbot.mongo.cmd_history.insert_one(
                    {
                        'user_id': message.author.id,
                        'commands': []
                    }
                )

                history = {}
            else:
                history = dict([(cmd['name'], cmd['timestamp']) for cmd in doc['commands']])

            await self.mbot.update_stats({'commands_received': 1}, scopes=['global', message.server])

            # Check cooldown
            if cooldown and not self.mbot.perms_check(message.author, su=True):  # SU can bypass cooldown.
                timestamp = history.get(wrapper.info['name'], None)

                if timestamp is not None and timestamp + cooldown > time.time():
                    return await self.mbot.send_message(
                        message.channel,
                        f'**{message.author.name}, slow down there (this command has a cooldown)...\n'
                        f'*{max(int((timestamp + cooldown) - time.time()), 1)}* second(s) remaining.**'
                    )

            # Check NSFW status
            config = await self.mbot.mongo.config.find_one({'server_id': message.server.id})

            if nsfw and message.channel.id not in config['nsfw_channels']:
                return await self.mbot.send_message(message.channel, '*You cannot use NSFW commands here...*')

            # Check if the user has necessary permissions.
            if not self.mbot.perms_check(message.author, message.channel, perms, su):
                return await self.mbot.send_message(message.channel, '*You do not have permission to do that...*')

            try:
                await func(self, message, *match.groups())

                await self.mbot.mongo.stats.update_many(
                    {
                        'scope': {'$in': ['global', message.server.id]},
                        'commands_executed.command': {'$ne': wrapper.info['name']}
                    },
                    {'$addToSet': {'commands_executed': {'command': wrapper.info['name'], 'n': 0}}}
                )

                await self.mbot.update_stats(
                    {'commands_executed.$.n': 1},
                    scopes=['global', message.server],
                    query={'commands_executed': {'$elemMatch': {'command': wrapper.info['name']}}}
                )

            except Forbidden:
                log.error(
                    f'forbidden to run command {wrapper.info["name"]} in server {message.server.id} {match.groups()}'
                )

                msg = await self.mbot.send_message(message.channel, '*I cannot do that...* :cry:')
                await asyncio.sleep(5)
                await self.mbot.delete_message(msg)
            except Exception:
                log.exception(f'error while running {wrapper.info["name"]} in server {message.server.id}')

            if call_on_message:
                await self.on_message(message)

            # Update timestamps
            if wrapper.info['name'] not in history:
                await self.mbot.mongo.cmd_history.update_one(
                    {'user_id': message.author.id},
                    {'$push': {'commands': {'name': wrapper.info['name'], 'timestamp': time.time()}}}
                )
            else:
                tstamp = time.time()
                await self.mbot.mongo.cmd_history.update_one(
                    {'user_id': message.author.id, 'commands': {'$elemMatch': {'name': wrapper.info['name']}}},
                    {'$set': {'commands.$.timestamp': tstamp}}
                )

        wrapper._command = True
        wrapper._func = func
        wrapper._pattern = pattern
        wrapper._mutex = mutex

        wrapper.info = {
            'usage': usage or '',
            'desc': description or '',
            'name': name or func.__name__,
            'plugin': '',
            'aliases': aliases or [],
            'perms': (su, perms)
        }

        return wrapper
    return decorator
