import re
import shlex
import random
import asyncio
from copy import copy
# noinspection PyUnresolvedReferences
from string import whitespace

from discord import Forbidden, Embed
from lark import Lark, Transformer
from lark.exceptions import UnexpectedToken
from lark.parsers.lalr_analysis import LALR_Analyzer, Shift

from ..plugin import BasePlugin
from ..command import command
from ..utils import long_running_task


RESERVED_CHARS = {
    '$(semicolon)': ';',
    '$(lbrace)': '{',
    '$(rbrace)': '}',
    '$(quote)': '"',
    '$(colon)': ':'
}

GRAMMAR = r'''
    start: cmd+
    ?cmd: speak
         | pm
         | block
         | random
         | if_stmt
         | role
         | perms
         | command
         | sleep
         | cp_disable
         | cp_enable
         | gc_disable
         | gc_enable
         | delete
         | nop

    block: "{" "block" ":" cmd (";" cmd)+ "}"
    if_stmt: "{" "if" ":" ESCAPED_STRING ";" IF_OP ";" ESCAPED_STRING ";" cmd ";" cmd "}"
    speak: "{" "speak" ":" ESCAPED_STRING "}" | TEXT
    pm: "{" "pm" ":" ESCAPED_STRING "}"
    role: "{" "role" ":" ESCAPED_STRING "}"
    perms: "{" "perms" ":" (INT | HEX) "}"
    command: "{" "cmd" ":" ESCAPED_STRING "}"
    sleep: "{" "sleep" ":" (INT | HEX) "}"
    cp_enable: "{" "check_perms" "}"
    cp_disable: "{" "!check_perms" "}"
    gc_enable: "{" "global_commands" "}"
    gc_disable: "{" "!global_commands" "}"
    delete: "{" "delete" "}"
    random: "{" "random" ":" cmd (";" cmd)+ "}"
    nop: "{" "nop" "}"

    IF_OP: "eq" | "ne" | "in" | "not in" | "lt" | "gt" | "le" | "ge"
    CHAR: "a".."z" | "A".."Z" | "0".."9" | /[!\"#$%&\'()*+,\-.\/:<=>?@[\\\]\^_`\|~]/
    TEXT: CHAR (WS? CHAR)*
    HEX: "0x" HEXDIGIT+

    %import common.ESCAPED_STRING
    %import common.HEXDIGIT
    %import common.INT
    %import common.WS
    %ignore WS
    '''


PRIVILEGED_RULES = ['cp_enable', 'cp_disable', 'gc_enable', 'gc_disable']
PRIVILEGED_COMMANDS = ['check_perms', '!check_perms', 'global_commands', '!global_commands']


class ParsingError(Exception):
    pass


class MyParser(object):
    def __init__(self, parser_conf):
        assert all(r.options is None or r.options.priority is None
                   for r in parser_conf.rules), 'LALR doesn\'t yet support prioritization'

        analysis = LALR_Analyzer(parser_conf)
        analysis.compute_lookahead()
        callbacks = {rule: getattr(parser_conf.callback, rule.alias or rule.origin, None) for rule in parser_conf.rules}

        self._parse_table = analysis.parse_table
        self.parser_conf = parser_conf
        self.parser = _MyParser(analysis.parse_table, callbacks)  # MONKEY PATCH
        self.parse = self.parser.parse


class _MyParser(object):
    def __init__(self, parse_table, callbacks):
        self.states = parse_table.states
        self.start_state = parse_table.start_state
        self.end_state = parse_table.end_state
        self.callbacks = callbacks

    def parse(self, seq, set_state=None):
        i = 0
        token = None
        stream = iter(seq)
        states = self.states

        state_stack = [self.start_state]
        value_stack = []

        rules = set()  # MONKEY PATCH

        if set_state:
            set_state(self.start_state)

        def get_action(key):
            state = state_stack[-1]

            try:
                return states[state][key]
            except KeyError:
                expected = states[state].keys()
                raise UnexpectedToken(token, expected, state=state)

        def reduce(rule):
            size = len(rule.expansion)

            if size:
                s = value_stack[-size:]
                del state_stack[-size:]
                del value_stack[-size:]
            else:
                s = []

            # MONKEY PATCH
            if not rule.origin.name.startswith('_'):
                rules.add(rule.origin.name)

            value = self.callbacks[rule](s)

            _action, new_state = get_action(rule.origin.name)
            assert _action is Shift
            state_stack.append(new_state)
            value_stack.append(value)

        # Main LALR-parser loop
        for i, token in enumerate(stream):
            while True:
                action, arg = get_action(token.type)
                assert arg != self.end_state

                if action is Shift:
                    state_stack.append(arg)
                    value_stack.append(token)

                    if set_state:
                        set_state(arg)

                    break  # next token
                else:
                    reduce(arg)

        while True:
            _action, arg = get_action('$END')
            if _action is Shift:
                assert arg == self.end_state
                val, = value_stack
                return val, rules
            else:
                reduce(arg)


class MyTransformer(Transformer):
    def block(self, args):
        return ('block', *args)

    def if_stmt(self, args):
        return ('if', args[0].value[1:-1], args[1].value, args[2].value[1:-1], *args[3:])

    def speak(self, args):
        if args[0].type == 'TEXT':
            return 'speak', args[0].value

        return 'speak', args[0][1:-1]

    def pm(self, args):
        return 'pm', args[0][1:-1]

    def role(self, args):
        return 'role', args[0].value[1:-1]

    def perms(self, args):
        return 'perms', int(args[0], base=16 if args[0].startswith('0x') else 10)

    def command(self, args):
        return 'cmd', args[0].value[1:-1]

    def sleep(self, args):
        return 'sleep', min(int(args[0], base=16 if args[0].startswith('0x') else 10), 10)

    def cp_enable(self, *args):
        return 'check_perms', None

    def cp_disable(self, *args):
        return '!check_perms', None

    def gc_enable(self, *args):
        return 'global_commands', None

    def gc_disable(self, *args):
        return '!global_commands', None

    def delete(self, *args):
        return 'delete', None

    def random(self, args):
        return ('random', *args)

    def nop(self, *args):
        return 'nop', None


class CustomCommands(BasePlugin):
    def __init__(self, mbot):
        super().__init__(mbot)

        self.cc_db = self.mbot.mongo.plugin_data.custom_commands

        self.parser = Lark(GRAMMAR, parser='lalr', lexer='contextual', transformer=MyTransformer())
        self.parser.parser.parser = MyParser(self.parser.parser.parser.parser_conf)  # MOKNEY PATCH

    @staticmethod
    def subs_vars(replacements, string):
        # code from https://stackoverflow.com/questions/6116978/how-to-replace-multiple-substrings-of-a-string
        rep = dict((re.escape(k), v) for k, v in replacements.items())
        pattern = re.compile('|'.join(rep.keys()))
        return pattern.sub(lambda m: rep[re.escape(m.group(0))], string)

    @long_running_task()
    def parse_cc(self, cmd_string, message, args):
        replacements = {
            '$(user.name)': message.author.name,
            '$(user.discriminator)': message.author.discriminator,
            '$(user.mention)': message.author.mention,
            '$(user.avatar)': message.author.avatar_url or message.author.default_avatar_url,
            '$(user.id)': message.author.id,
            '$(user.created_at)': str(message.author.created_at),
            '$(user.display_name)': message.author.display_name,
            '$(user.joined_at)': str(message.author.joined_at),
            '$(user.status)': str(message.author.status),
            '$(user.game)': str(message.author.game) if message.author.game else '',
            '$(user.nick)': message.author.nick or '',
            '$(user.color)': str(message.author.colour),
            '$(user.colour)': str(message.author.colour),

            '$(server.name)': message.server.name,
            '$(server.id)': message.server.id,
            '$(server.region)': str(message.server.region),
            '$(server.afk_timeout)': str(message.server.afk_timeout),
            '$(server.icon_url)': message.server.icon_url,
            '$(server.splash_url)': message.server.splash_url,
            '$(server.members)': str(message.server.member_count),
            '$(server.created_at)': str(message.server.created_at),

            '$(channel.id)': message.channel.id,
            '$(channel.name)': message.channel.name,
            '$(channel.created_at)': str(message.channel.created_at),
            '$(channel.mention)': message.channel.mention,
            '$(channel.position)': str(message.channel.position)
        }

        for i, arg in enumerate(args):
            replacements[f'$({i + 1})'] = arg
            replacements[f'$(>{i + 1})'] = ' '.join(args[i:])
            replacements[f'$(<{i + 1})'] = ' '.join(args[:i])

        cmd_string = self.subs_vars(replacements, cmd_string)

        try:
            tree, rules = self.parser.parse(cmd_string)
            return tree.children, rules
        except Exception as e:
            raise ParsingError(str(e))

    def _build_embed(self, string):
        if not string:
            return

        try:
            e = Embed()

            for field in string.split('::'):
                key = self.subs_vars(RESERVED_CHARS, field.split(':', 1)[0]).strip()
                value = self.subs_vars(RESERVED_CHARS, field.split(':', 1)[1]).strip()

                if not key or not value:
                    return

                if key == '$$title':
                    e.title = value
                elif key == '$$description':
                    e.description = value
                elif key in ['$$color', '$$colour']:
                    e.colour = int(value, base=16 if value.startswith('0x') else 10)
                elif key == '$$thumbnail':
                    e.set_thumbnail(url=value)
                elif key == '$$image':
                    e.set_image(url=value)
                elif key == '$$footer':
                    e.set_footer(text=value)
                else:
                    e.add_field(name=key, value=value)

            return e
        except:
            return

    async def execute_cc(self, message, tokens, env=None, _depth=0):
        env = env or {'check_perms': True, 'global_commands': False}

        for token in tokens:
            if token[0] == 'if':
                token[1] = self.subs_vars(RESERVED_CHARS, token[1])
                token[3] = self.subs_vars(RESERVED_CHARS, token[3])

                bool_map = {
                    'eq': token[1] == token[3],
                    'ne': token[1] != token[3],
                    'in': token[1] in token[3],
                    'not in': token[1] not in token[3],
                    'lt': token[1] < token[3],
                    'gt': token[1] > token[3],
                    'le': token[1] <= token[3],
                    'ge': token[1] >= token[3]
                }

                if bool_map[token[2]]:
                    env = await self.execute_cc(message, [token[4]], env=env, _depth=_depth + 1)
                else:
                    env = await self.execute_cc(message, [token[5]], env=env, _depth=_depth + 1)

            if token[0] == 'block':
                env = await self.execute_cc(message, token[1:], env=env, _depth=_depth + 1)

            if token[0] == 'random':
                env = await self.execute_cc(message, [random.choice(token[1:])], env=env, _depth=_depth + 1)

            if token[0] == 'speak':
                if token[1].startswith('$$embed:'):
                    embed = self._build_embed(token[1][8:])

                    if embed is not None:
                        await self.mbot.send_message(message.channel, embed=embed)
                        continue

                await self.mbot.send_message(
                    message.channel, self.subs_vars(RESERVED_CHARS, token[1])
                )

            elif token[0] == 'pm':
                if token[1].startswith('$$embed:'):
                    embed = self._build_embed(token[1][8:])

                    if embed is not None:
                        await self.mbot.send_message(message.author, embed=embed)
                        continue

                await self.mbot.send_message(
                    message.author, self.subs_vars(RESERVED_CHARS, token[1])
                )

            elif token[0] == 'role':
                if not any([role.name == self.subs_vars(RESERVED_CHARS, token[1]) for role in message.author.roles]):
                    return

            elif token[0] == 'perms':
                if not self.mbot.perms_check(message.author, message.channel, token[1]):
                    return

            elif token[0] == 'cmd':
                await asyncio.sleep(1)

                cmd = copy(message)
                cmd.content = self.subs_vars(RESERVED_CHARS, token[1])
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

            elif token[0] == 'nop':
                pass

        return env

    async def _run_command(self, message, cmd_server_id, cmd, args=None):
        doc = await self.cc_db.find_one(
            {'server_id': cmd_server_id, 'cmd_name': cmd}
        )

        if not doc:
            return await self.mbot.send_message(
                message.channel, '**I could not find that command...**'
            )

        if doc['access'] == 'me' and message.author.id != doc['owner_id']:
            return await self.mbot.send_message(message.channel, '*This command can only be used by it\'s author.*')
        elif doc['access'] == 'local' and message.server.id != doc['server_id']:
            return await self.mbot.send_message(message.channel, '*This command can only be used in it\'s server.*')

        if doc['access'] == 'me' and message.author.id != doc['owner_id']:
            return await self.mbot.send_message(
                message.channel, '*This command can only be used by it\'s author.*'
            )

        cmd_string = doc['cmd_string']
        parsed, _ = await self.parse_cc(cmd_string, message, shlex.split(args) if args else [])
        self.mbot.loop.create_task(self.execute_cc(message, parsed))

    @command(regex='^cc (.*?)(?: (.*?))?$', name='cc')
    async def run_cc(self, message, cmd, args=None):
        await self._run_command(message, message.server.id, cmd, args)

    @command(regex='^cc-run (\d*?) (.*?)(?: (.*?))?$', name='cc-run')
    async def run_cc_extended(self, message, server_id, cmd, args=None):
        await self._run_command(message, server_id, cmd, args)

    @command(regex='^cc-info (.*?)(?: (\d*?))?$', name='cc-info')
    async def cc_info(self, message, cmd, server_id=None):
        doc = await self.cc_db.find_one(
            {'server_id': server_id or message.server.id, 'cmd_name': cmd}
        )

        if not doc:
            return await self.mbot.send_message(
                message.channel, '**I could not find that command...**'
            )

        return await self.mbot.send_message(
            message.channel,
            f'**Info for custom command `{cmd}`**\n\n'
            f'  • Command Owner -`{doc["owner_id"] or "-"}`\n'
            f'  • Command Server -`{doc["server_id"] or "-"}`\n'
            f'  • Help - `{doc["help"] or "-"}`\n'
            f'  • Usage - `{doc["usage"] or "-"}`'
        )

    @staticmethod
    def parse_metadata(cmd_string):
        access, help_string, usage, = 'global', '', ''
        lines = cmd_string.splitlines(True)
        _meta_lines = 0

        for x, line in enumerate(lines):
            if line.strip().startswith('$$access:'):
                if line[9:].strip() in ['local', 'global', 'me']:
                    access = line[9:].strip()

                _meta_lines += 1

            elif line.strip().startswith('$$help:'):
                help_string = line[7:].strip()
                _meta_lines += 1

            elif line.strip().startswith('$$usage'):
                usage = line[7:].strip()
                _meta_lines += 1

            else:
                break  # Meta lines should only appear at the beginning of the string.

        return ''.join(lines[_meta_lines:]), access, help_string, usage

    async def command_check(self, cmd_string, message):
        try:
            tokens, rules = await self.parse_cc(cmd_string, message, [])

            if any([x in rules for x in PRIVILEGED_RULES]) and not self.mbot.perms_check(
                    message.author, message.channel, required_perms=32
            ):
                _ = '\n'.join(PRIVILEGED_COMMANDS)
                return (
                    '**Something went wrong...**\n\n'
                    f'```{cmd_string}```\n:exclamation: **ERROR**'
                    ' You do not have permission to use one or more of the following commands:'
                    f'```{_}```'
                )
        except ParsingError as e:
            return (
                '**Something went wrong...**\n\n'
                f'```{cmd_string}```\n'
                f':exclamation: **ERROR**\n```{str(e)}```'
            )

        return tokens, rules

    @command(regex='^cc-add (.*?)$', name='cc-add')
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
            cmd_string.content, access, help_string, usage = self.parse_metadata(cmd_string.content)
            ret = await self.command_check(cmd_string.content, message)

            if isinstance(ret, str):
                return await self.mbot.send_message(message.channel, ret)
            else:
                tokens, rules = ret

            await self.cc_db.insert_one({
                'server_id': message.server.id,
                'owner_id': message.author.id,
                'cmd_name': name,
                'cmd_string': cmd_string.content,
                'access': access,
                'help': help_string,
                'usage': usage,
                'restricted': 'perms' in rules or 'role' in rules,
                'calls_external': 'command' in rules,
                'privileged': any([x in rules for x in PRIVILEGED_RULES])
            })

            await self.mbot.send_message(
                message.channel,
                f'**Successfully added command `{name}`**!\n\n'
                f'```{cmd_string.content}```'
            )

    async def fetch_commands(self, page, query=None):
        commands = []
        query = query or {}

        async for trade in self.cc_db.find(query).skip(page * 8).limit(8):  # A page represents 8 records.
            commands.append(trade)

        return commands

    @command(regex='^cc-browse(?: (.*?))?$', name='cc-browse')
    async def cc_browse(self, message, filters=None):
        _q = {'server_id': message.server.id}

        if filters:
            for f in filters.split(' '):
                try:
                    key, val = f.split(':')
                    key = key.strip()
                except ValueError:
                    return await self.mbot.send_message(
                        message.channel, '**Invalid filter!**'
                    )

                if key not in ['owner_id', 'server_id', 'access', 'restricted', 'calls_external', 'privileged']:
                    return await self.mbot.send_message(
                        message.channel,
                        f'**Unrecognised filter `{key}`!**'
                    )

                if key in ['restricted', 'calls_external', 'privileged'] and val in ['true', 'false']:
                    _q[key] = False if val == 'false' else True
                else:
                    _q[key] = val

        page = 0

        while True:
            commands = await self.fetch_commands(page, _q)
            next_page = await self.fetch_commands(page + 1, _q)

            if not commands:
                return await self.mbot.send_message(
                    message.channel, '**I couldn\'t find any commands.**'
                )

            options = {}

            for x in commands:
                options[x['cmd_name'] + x['server_id']] = '{:<32} [{}]'.format(
                    x['cmd_name'],
                    (x['access'][0]) +
                    ('h' if x['help'] else '-') +
                    ('u' if x['usage'] else '-') +
                    ('c' if x['calls_external'] else '-') +
                    ('r' if x['restricted'] else '-') +
                    ('p' if x['privileged'] else '-')

                )

            option = await self.mbot.option_selector(
                message,
                f'**Custom Commands for '
                f'`{message.server.name if _q.get("server_id") == message.server.id else _q.get("server_id")}`**\n'
                f'Enter an option number to see more details.',
                footer='**Command Metadata Explained**\n'
                       '```[012345]\n\n'
                       '  > [0] "g" if the command can be used globally, "l" if the command can only be used locally, '
                       '"m" if the command can only be used by it\'s author, "-" otherwise.\n'
                       '  > [1] "h" if the command has a help string, "-" otherwise.\n'
                       '  > [2] "u" if the command has a usage string, "-" otherwise.\n'
                       '  > [3] "c" if the command calls external bot commands ({cmd: ...}), "-" otherwise.\n'
                       '  > [4] "r" if the command restricts it\'s usage to certain permissions or roles, '
                       '"-" otherwise.\n'
                       '  > [5] "p" if the command uses privileged commands ({check_perms}, {!check_perms},'
                       '{global_commands}, {!global_commands}).```',
                options=options, timeout=180, pp=page != 0, np=bool(next_page)
            )

            if not option:
                return await self.mbot.send_message(
                    message.channel, '**Closing menu.**'
                )

            if option == 'np':
                page += 1
            elif option == 'pp':
                page -= 1
            else:
                cmd_map = {x['cmd_name'] + x['server_id']: x for x in commands}
                cmd = cmd_map[option]

                script = '<hidden>' if cmd['access'] == 'local' and message.server.id != cmd['server_id'] \
                         or cmd['access'] == 'me' and message.author.id != cmd['owner_id'] \
                         else cmd['cmd_string']

                await self.mbot.send_message(
                    message.author,
                    f'**Custom Command - `{cmd["cmd_name"]}`**\n\n'
                    f'  • Owner ID: {cmd["owner_id"]}\n'
                    f'  • Server ID: {cmd["server_id"]}\n'
                    f'  • Help: {cmd["help"]}\n'
                    f'  • Usage: {cmd["usage"]}\n'
                    f'  • Restricted: {"yes" if cmd["restricted"] else "no"}\n'
                    f'  • Privileged: {"yes" if cmd["privileged"] else "no"}\n'
                    f'  • Calls external commands: {"yes" if cmd["calls_external"] else "no"}\n\n'
                    f'**Command Script / Response**\n'
                    f'```{script}```'
                )

    @command(regex='^cc-remove (.*?)(?: (\d*?))?$', name='cc-remove')
    async def cc_remove(self, message, cmd, server_id=None):
        ret = await self.cc_db.delete_one(
            {'server_id': server_id or message.server.id, 'cmd_name': cmd, 'owner_id': message.author.id}
        )

        if ret.deleted_count != 1:
            return await self.mbot.send_message(
                message.channel,
                f'**Could not delete the `{cmd}` command.**'
            )

        return await self.mbot.send_message(
            message.channel,
            f':ok_hand: **Successfully deleted the `{cmd}` command.**'
        )

    @command(regex='^cc-edit (.*?)(?: (\d*?))?$', name='cc-edit')
    async def cc_edit(self, message, cmd, server_id=None):
        doc = await self.cc_db.find_one(
            {'server_id': server_id or message.server.id, 'cmd_name': cmd, 'owner_id': message.author.id}
        )

        if not doc:
            return await self.mbot.send_message(
                message.channel, '**I could not find that command...**'
            )

        cmd_string = await self.mbot.wait_for_input(
            message,
            '**Please enter the new command script**\n'
            'Note that you cannot modify command metadata here.\n\n'
            f'The current script is:\n```{doc["cmd_string"]}```', timeout=180
        )

        if cmd_string:
            ret = await self.command_check(cmd_string.content, message)

            if isinstance(ret, str):
                return await self.mbot.send_message(message.channel, ret)
            else:
                tokens, rules = ret

            await self.cc_db.update_one(
                {'server_id': server_id or message.server.id, 'cmd_name': cmd, 'owner_id': message.author.id},
                {'$set': {
                    'cmd_string': cmd_string.content,
                    'restricted': 'perms' in rules or 'role' in rules,
                    'calls_external': 'command' in rules,
                    'privileged': any([x in rules for x in PRIVILEGED_RULES])}
                }
            )

            await self.mbot.send_message(
                message.channel,
                '**Successfully updated the command script!**'
            )
