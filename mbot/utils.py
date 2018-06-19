from functools import wraps, partial
from discord import Client


def long_running_task(send_typing=True):
    '''
    Decorator which can be used to run long running methods as a background task
    in the main loop. The method can then be used as a co-routine.

    :param send_typing: Bool indicating whether or not to send typing status to discord.
    '''
    def decorator(func):
        @wraps(func)
        async def wrapper(self, *args, _message=None, **kwargs):
            if isinstance(self, Client):
                mbot = self
            else:
                mbot = self.mbot

            f = partial(func, self, *args, **kwargs)

            if send_typing and _message is not None:
                await mbot.send_typing(_message.channel)

            return await mbot.loop.run_in_executor(None, f)
        return wrapper
    return decorator


def human_time(seconds, past_tense=True):
    '''
    Return a very rough approximate for an amount of seconds in plain english.
    '''
    string = ''
    seconds = int(seconds)
    days = seconds // (24 * 60 * 60)

    if seconds < 0:
        return ''

    if days == 0:
        if seconds < 10:
            string = 'just now'
        elif seconds < 60:
            string = f'{seconds} seconds'
        elif seconds < 120:
            string = 'a minute'
        elif seconds < 3600:
            string = f'{seconds // 60} minutes'
        elif seconds < 7200:
            string = 'an hour'
        elif seconds < 86400:
            string = f'{seconds // 3600} hours'

    elif days == 1:
        string = 'Yesterday'
    elif days < 7:
        string = f'{days} days'
    elif days < 31:
        string = f'{days // 7} week(s)'
    elif days < 365:
        string = f'{days // 30} month(s)'
    else:
        string = f'{days // 365} year(s)'

    if past_tense and string != 'just now':
        return string + ' ago'

    return string
