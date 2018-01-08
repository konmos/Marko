import inspect

from .plugin_registry import PluginRegistry


class BasePlugin(object, metaclass=PluginRegistry):
    '''
    Base plugin class from which all plugins should inherit.
    '''
    def __init__(self, mbot):
        self.mbot = mbot
        self.commands = []

        for member in inspect.getmembers(self):
            if hasattr(member[1], '_command'):
                member[1].info['plugin'] = self.__class__.__name__

                self.commands.append(member[1])

    async def on_ready(self):
        '''Called when the client is done preparing the data received from Discord.'''

    async def on_resumed(self):
        '''Called when the client has resumed a session.'''

    async def on_error(self, event, *args, **kwargs):
        '''Supress the default action of printing the traceback.'''

    async def on_message(self, message):
        '''Called when a message is created and sent to a server.'''

    async def on_socket_raw_receive(self, msg):
        '''Called whenever a message is received from the websocket.'''

    async def on_socket_raw_send(self, payload):
        '''Called whenever a send operation is done on the websocket.'''

    async def on_message_delete(self, message):
        '''Called when a message is deleted.'''

    async def on_message_edit(self, before, after):
        '''Called when a message receives an update event.'''

    async def on_reaction_add(self, reaction, user):
        '''Called when a message has a reaction added to it.'''

    async def on_reaction_remove(self, reaction, user):
        '''Called when a message has a reaction removed from it.'''

    async def on_reaction_clear(self, message, reactions):
        '''Called when a message has all its reactions removed from it.'''

    async def on_channel_delete(self, channel):
        '''Called whenever a channel is removed from a server.'''

    async def on_channel_create(self, channel):
        '''Called whenever a channel is added to a server.'''

    async def on_channel_update(self, before, after):
        '''Called whenever a channel is updated.'''

    async def on_member_join(self, member):
        '''Called when a member joins a server.'''

    async def on_member_remove(self, member):
        '''Called when a member leaves a server.'''

    async def on_member_update(self, before, after):
        '''Called when a member updates their profile.'''

    async def on_server_join(self, server):
        '''Called when a server is either created by the client or when te client joins a server.'''

    async def on_server_remove(self, server):
        '''Called when a server is removed from the client.'''

    async def on_server_update(self, before, after):
        '''Caled when a server updates.'''

    async def on_server_role_create(self, role):
        '''Called when a server creates a new role.'''

    async def on_server_role_delete(self, role):
        '''Called when a server deletes a role.'''

    async def on_server_role_update(self, before, after):
        '''Called when a role is changed server-wide.'''

    async def on_server_emojis_update(self, before, after):
        '''Called when a server adds ot remoes Emoji.'''

    async def on_server_available(self, server):
        '''Called when a server becomes unavailable.'''

    async def on_server_unavailable(self, server):
        '''Called when a server becomes unavailable.'''

    async def on_voice_state_update(self, before, after):
        '''Called when a member changes their voice state.'''

    async def on_member_ban(self, member):
        '''Called when a member gets banned from a server.'''

    async def on_member_unban(self, server, user):
        '''Called when a user gets unbanned from a server.'''

    async def on_typing(self, channel, user, when):
        '''Called when someone begins typing a message.'''

    async def on_group_join(self, channel, user):
        '''Called when someone joins a group.'''

    async def on_group_remove(self, channel, user):
        '''Called when someone leaves a group.'''
