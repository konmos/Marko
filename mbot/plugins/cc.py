import re
import shlex
import asyncio
from copy import copy
# noinspection PyUnresolvedReferences
from string import whitespace

from discord import Forbidden

from ..plugin import BasePlugin
from ..command import command


class ParsingError(Exception):
    pass


class CustomCommands(BasePlugin):
    def __init__(self, mbot):
        super().__init__(mbot)

        self.cc_db = self.mbot.mongo.plugin_data.custom_commands

    def parse_cc(self, message, cmd_string, args):
        tokens = []
        lines = cmd_string.split(';')

        if len(lines) > 10:
            raise ParsingError('Maximum script size exceeded.')

        # code from https://stackoverflow.com/questions/6116978/how-to-replace-multiple-substrings-of-a-string
        replacements = {
            '$sep': ';',

            '$user.name': message.author.name,
            '$user.discriminator': message.author.discriminator,
            '$user.mention': message.author.mention,
            '$user.avatar': message.author.avatar_url or message.author.default_avatar_url,
            '$user.id': message.author.id,
            '$user.created_at': str(message.author.created_at),
            '$user.display_name': message.author.display_name,
            '$user.joined_at': str(message.author.joined_at),
            '$user.status': str(message.author.status),
            '$user.game': str(message.author.game) if message.author.game else '',
            '$user.nick': message.author.nick or '',
            '$user.color': str(message.author.colour),
            '$user.colour': str(message.author.colour),

            '$server.name': message.server.name,
            '$server.id': message.server.id,
            '$server.region': str(message.server.region),
            '$server.afk_timeout': str(message.server.afk_timeout),
            '$server.icon_url': message.server.icon_url,
            '$server.splash_url': message.server.splash_url,
            '$server.members': str(message.server.member_count),
            '$server.created_at': str(message.server.created_at),

            '$channel.id': message.channel.id,
            '$channel.name': message.channel.name,
            '$channel.created_at': str(message.channel.created_at),
            '$channel.mention': message.channel.mention,
            '$channel.position': str(message.channel.position)
        }

        for i, arg in enumerate(args):
            replacements[f'${i + 1}'] = arg
            replacements[f'$>{i + 1}'] = ' '.join(args[i:])
            replacements[f'$<{i + 1}'] = ' '.join(args[:i])

        rep = dict((re.escape(k), v) for k, v in replacements.items())
        pattern = re.compile('|'.join(rep.keys()))

        for line in lines:
            line = line.strip()

            if not line:
                continue

            op, *args = line.split(' ', 1)

            try:
                args[0] = pattern.sub(lambda m: rep[re.escape(m.group(0))], args[0])

                if op in ['speak', 'role', 'cmd', 'pm']:
                    tokens.append((op, args[0]))

                elif op == 'sleep':
                    tokens.append((op, max(int(args[0]), 10)))

                elif op == 'perms':
                    tokens.append((op, int(args[0])))

                elif op in ['delete', 'check_perms', '!check_perms', 'global_commands', '!global_commands']:
                    tokens.append((op, None))
            except:
                raise ParsingError(f'Error parsing line: {repr(line)}')

        return tokens

    async def execute_cc(self, message, tokens):
        env = {'check_perms': True, 'global_commands': False}

        for token in tokens:
            if token[0] == 'speak':
                await self.mbot.send_message(message.channel, token[1])

            elif token[0] == 'pm':
                await self.mbot.send_message(message.author, token[1])

            elif token[0] == 'role':
                if not any([role.name == token[1] for role in message.author.roles]):
                    return

            elif token[0] == 'perms':
                if not self.mbot.perms_check(message.author, message.channel, token[1]):
                    return

            elif token[0] == 'cmd':
                cmd = copy(message)
                cmd.content = token[1]
                await self.mbot.run_command(
                    cmd, fail_silently=True, check_perms=env['check_perms'], global_commands=env['global_commands']
                )

            elif token[0] == 'sleep':
                await asyncio.sleep(token[1])

            elif token[0] == 'check_perms':
                env['check_perms'] = True

            elif token[0] == '!check_perms':
                env['check_perms'] = False

            elif token[0] == 'global_commands':
                env['global_commands'] = True

            elif token[0] == '!global_commands':
                env['global_commands'] = False

            elif token[0] == 'delete':
                try:
                    await self.mbot.delete_message(message)
                except Forbidden:
                    pass

    @command(regex='^cc (.*?)(?: (.*?))?$', name='cc')
    async def run_cc(self, message, cmd, args=None):
        doc = await self.cc_db.find_one(
            {'server_id': message.server.id, 'cmd_name': cmd}
        )

        if not doc:
            return await self.mbot.send_message(
                message.channel, '**I could not find that command...**'
            )

        cmd_string = doc['cmd_string']
        parsed = self.parse_cc(message, cmd_string, shlex.split(args) if args else [])

        await self.execute_cc(message, parsed)

    @command(regex='^cc-add (.*?)$', name='cc-add', perms=32)
    async def add_cc(self, message, name):
        _p = f'[{re.escape(whitespace)}]'
        name = re.sub(_p, '-', name)

        doc = await self.cc_db.find_one(
            {'server_id': message.server.id, 'cmd_name': name}
        )

        if doc:
            return await self.mbot.send_message(
                message.channel, '**This command already exists...**'
            )

        cmd_string = await self.mbot.wait_for_input(
            message,
            '**Please enter the full command script you wish to add**\n'
            'Remember... command statements are separated by a semicolon (;).\n'
            'New lines can be entered by pressing "shift" + "enter".',
            timeout=180
        )

        if cmd_string:
            try:
                self.parse_cc(message, cmd_string.content, [])
            except ParsingError as e:
                return await self.mbot.send_message(
                    message.channel,
                    '**There was an error while adding this command**\n'
                    f'`{str(e)}`'
                )

            await self.cc_db.insert_one(
                {'server_id': message.server.id, 'cmd_name': name, 'cmd_string': cmd_string.content}
            )

            await self.mbot.send_message(
                message.channel,
                f'**Successfully added command `{name}`!'
            )

