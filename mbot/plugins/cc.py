import re
import shlex
import random
import asyncio
from copy import copy
# noinspection PyUnresolvedReferences
from string import whitespace

from discord import Forbidden
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
    perms: "{" "perms" ":" HEX "}"
    command: "{" "cmd" ":" ESCAPED_STRING "}"
    sleep: "{" "sleep" ":" INT "}"
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
    HEX: HEXDIGIT+

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
        return (
            'if',
            CustomCommands.subs_vars(RESERVED_CHARS, args[0].value[1:-1]),
            args[1].value,
            CustomCommands.subs_vars(RESERVED_CHARS, args[2].value[1:-1]),
            *args[3:]
        )

    def speak(self, args):
        if args[0].type == 'TEXT':
            return 'speak', CustomCommands.subs_vars(RESERVED_CHARS, args[0].value)

        return 'speak', CustomCommands.subs_vars(RESERVED_CHARS, args[0][1:-1])

    def pm(self, args):
        return 'pm', CustomCommands.subs_vars(RESERVED_CHARS, args[0][1:-1])

    def role(self, args):
        return 'role', CustomCommands.subs_vars(RESERVED_CHARS, args[0].value[1:-1])

    def perms(self, args):
        return 'perms', int(args[0], base=16)

    def command(self, args):
        return 'cmd', CustomCommands.subs_vars(RESERVED_CHARS, args[0].value[1:-1])

    def sleep(self, args):
        return 'sleep', min(int(args[0]), 10)

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

    async def execute_cc(self, message, tokens, env=None, _depth=0):
        env = env or {'check_perms': True, 'global_commands': False}

        for token in tokens:
            if token[0] == 'if':
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
                await asyncio.sleep(1)

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

            elif token[0] == 'nop':
                pass

        return env

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
        parsed, _ = await self.parse_cc(cmd_string, message, shlex.split(args) if args else [])
        self.mbot.loop.create_task(self.execute_cc(message, parsed))

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
                tokens, rules = await self.parse_cc(cmd_string.content, message, [])

                if any([x in rules for x in PRIVILEGED_RULES]) and not self.mbot.perms_check(
                        message.author, message.channel, required_perms=32
                ):
                    _ = '\n'.join(PRIVILEGED_COMMANDS)
                    return await self.mbot.send_message(
                        message.channel,
                        '**There was an error while adding this command**\n\n'
                        f'```{cmd_string.content}```\n:exclamation: **ERROR**'
                        ' You do not have permission to use one or more of the following commands:'
                        f'```{_}```'
                    )
            except ParsingError as e:
                return await self.mbot.send_message(
                    message.channel,
                    '**There was an error while adding this command**\n\n'
                    f'```{cmd_string.content}```\n'
                    f':exclamation: **ERROR**\n```{str(e)}```'
                )

            await self.cc_db.insert_one({
                'server_id': message.server.id,
                'owner_id': message.author.id,
                'cmd_name': name,
                'cmd_string': cmd_string.content
            })

            await self.mbot.send_message(
                message.channel,
                f'**Successfully added command `{name}`**!\n\n'
                f'```{cmd_string.content}```'
            )
