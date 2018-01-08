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
