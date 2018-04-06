import os
import math
import time
import zerorpc
from functools import wraps
from pymongo import MongoClient
from requests_oauthlib import OAuth2Session
from flask import Flask, render_template, session, redirect, request, flash, abort, jsonify

# CONFIG
RPC_HOST = os.environ.get('RPC_HOST', 'tcp://127.0.0.1:4243')
MONGO_HOST = os.environ.get('MONGO_HOST', 'mongodb://localhost:27017/')

OAUTH2_CLIENT_ID = os.environ['OAUTH2_CLIENT_ID']
OAUTH2_CLIENT_SECRET = os.environ['OAUTH2_CLIENT_SECRET']
OAUTH2_REDIRECT_URI = 'http://localhost:5000/dashboard/auth'

API_BASE_URL = os.environ.get('API_BASE_URL', 'https://discordapp.com/api')
AUTHORIZATION_BASE_URL = API_BASE_URL + '/oauth2/authorize'
TOKEN_URL = API_BASE_URL + '/oauth2/token'

app = Flask(__name__)
app.debug = True
app.config['SECRET_KEY'] = OAUTH2_CLIENT_SECRET

db = MongoClient(MONGO_HOST)

if 'http://' in OAUTH2_REDIRECT_URI:
    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = 'true'


# RPC
def get_rpc_client():
    client = zerorpc.Client()
    client.connect(RPC_HOST)
    return client


# MONGO
def get_playlist(server_id):
    return db.plugin_data.voice_player.find_one({'server_id': server_id})


def mongo_enable_cmd(server_id, cmd):
    success, rpc = [], get_rpc_client()

    plugin = rpc.plugin_for_command(cmd)
    all_commands = rpc.commands_for_plugin(plugin)
    enabled_commands = plugins_for_server(session.get('active_server')).get(plugin, [])

    # Skip Core plugin.
    if (plugin == 'Core' and not rpc.is_user_su(session.get('user')['id'])) or not plugin:
        return False

    if all_commands[cmd]['perms'][0] and not rpc.is_user_su(session.get('user')['id']):
        return False

    if not (cmd in all_commands and cmd not in enabled_commands):
        return False

    doc = db.bot_data.config.find_one(
        {'server_id': server_id, 'plugins': {'$elemMatch': {'name': plugin}}}
    )

    if doc:
        ret = db.bot_data.config.update_one(
            {'server_id': server_id, 'plugins': {'$elemMatch': {'name': plugin}}},
            {'$addToSet': {'plugins.$.commands': cmd}}
        )

        return bool(ret)


def mongo_disable_cmd(server_id, cmd):
    rpc = get_rpc_client()

    plugin = rpc.plugin_for_command(cmd)
    all_commands = rpc.commands_for_plugin(plugin)
    enabled_commands = plugins_for_server(session.get('active_server')).get(plugin, [])

    # Skip Core plugin.
    if (plugin == 'Core' and not rpc.is_user_su(session.get('user')['id'])) or not plugin:
        return False

    if all_commands[cmd]['perms'][0] and not rpc.is_user_su(session.get('user')['id']):
        return False

    if not (cmd in all_commands and cmd in enabled_commands):
        return False

    doc = db.bot_data.config.find_one(
        {'server_id': server_id, 'plugins': {'$elemMatch': {'name': plugin}}}
    )

    if doc:
        ret = db.bot_data.config.update_one(
            {'server_id': server_id, 'plugins': {'$elemMatch': {'name': plugin}}},
            {'$pull': {'plugins.$.commands': cmd}}
        )

        return bool(ret)


def get_server_config(server_id):
    return db.bot_data.config.find_one({'server_id': server_id})


def get_guild_data(guild_id):
    return db.bot_data.bot_guilds.find_one({'server_id': guild_id})


def set_prefix(server_id, prefix):
    ret = db.bot_data.config.update_one(
        {'server_id': server_id},
        {'$set': {'prefix': prefix}}
    )

    return bool(ret)


def mongo_enable_plugin(server_id, plugin):
    rpc = get_rpc_client()

    if plugin == 'Core' or plugin not in rpc.installed_plugins():
        return

    doc = db.bot_data.config.find_one(
        {'server_id': server_id, 'plugins': {'$elemMatch': {'name': plugin}}}
    )

    if doc:
        # Plugin is already enabled.
        return False

    ret = db.bot_data.config.update_one(
        {'server_id': server_id},
        {'$push': {'plugins': {'name': plugin, 'commands': []}}}
    )

    return bool(ret)


def mongo_disable_plugin(server_id, plugin):
    rpc = get_rpc_client()

    if plugin == 'Core' or plugin not in rpc.installed_plugins():
        return

    ret = db.bot_data.config.update_one(
        {'server_id': server_id},
        {'$pull': {'plugins': {'name': plugin}}}
    )

    return bool(ret)


def plugins_for_server(server_id):
    doc = db.bot_data.config.find_one({'server_id': server_id})

    if doc:
        return {plugin['name']: plugin['commands'] for plugin in doc['plugins']}


def get_cached_user_guilds(user_id):
    doc = db.bot_data.user_guilds.find_one({'user_id': user_id})

    if doc:
        return doc['guilds']

    return {}


def cache_user_guilds(user_id, guilds):
    if guilds and isinstance(guilds, list):
        return db.bot_data.user_guilds.update_one(
            {'user_id': user_id},
            {'$set': {'guilds': guilds}},
            upsert=True
        )


# OAUTH
def token_updater(token):
    session['oauth2_token'] = token


def make_session(token=None, state=None, scope=None):
    return OAuth2Session(
        client_id=OAUTH2_CLIENT_ID,
        token=token,
        state=state,
        scope=scope,
        redirect_uri=OAUTH2_REDIRECT_URI,
        auto_refresh_kwargs={
            'client_id': OAUTH2_CLIENT_ID,
            'client_secret': OAUTH2_CLIENT_SECRET,
        },
        auto_refresh_url=TOKEN_URL,
        token_updater=token_updater
    )


# FLASK STUFF
@app.before_request
def csrf_protect():
    if request.method == 'POST':
        token = session.get('_csrf_token', None)
        if not token or token not in (request.form.get('_csrf_token'), request.headers.get('X-Csrftoken')):
            abort(403)


def generate_csrf_token():
    session['_csrf_token'] = os.urandom(8).hex()
    return session['_csrf_token']


def csrf_token():
    return session['_csrf_token']


app.jinja_env.globals['generate_csrf_token'] = generate_csrf_token
app.jinja_env.globals['csrf_token'] = csrf_token


# UTILITIES
def human_time(seconds):
    if seconds >= 3600:
        return f'{math.ceil(seconds / 3600)} hour(s)'
    elif seconds >= 60:
        return f'{math.ceil(seconds / 60)} minute(s)'
    else:
        return f'{seconds} second(s)'


app.jinja_env.globals['human_time'] = human_time


# DASHBOARD
@app.route('/')
def home():
    return render_template('index.html')


@app.route('/commands')
def commands():
    rpc = get_rpc_client()
    all_commands = []
    all_plugins = rpc.installed_plugins()

    for plugin in all_plugins:
        plugin_commands = rpc.commands_for_plugin(plugin)

        if plugin_commands:
            # Hide 'su' commands
            for command in plugin_commands.copy().items():
                if command[1]['perms'][0]:
                    del plugin_commands[command[0]]

            all_commands.append((plugin, plugin_commands))

    return render_template('commands.html', all_commands=all_commands)


@app.route('/playlist/<server>')
def playlist(server):
    pl = get_playlist(server)

    if not pl:
        abort(404)

    return render_template('playlist.html', playlist=pl)


@app.route('/dashboard/login')
def login():
    scope = request.args.get(
        'scope',
        'identify guilds'
    )

    discord = make_session(scope=scope.split(' '))
    authorization_url, state = discord.authorization_url(AUTHORIZATION_BASE_URL)
    session['oauth2_state'] = state
    return redirect(authorization_url)


@app.route('/dashboard/logout')
def logout():
    session.clear()
    return redirect('/')


@app.route('/dashboard/auth')
def callback():
    if request.values.get('error'):
        return request.values['error']

    discord = make_session(state=session.get('oauth2_state'))

    token = discord.fetch_token(
        TOKEN_URL,
        client_secret=OAUTH2_CLIENT_SECRET,
        authorization_response=request.url
    )

    session['oauth2_token'] = token

    user = get_user()
    session['user'] = user
    cache_user_guilds(user['id'], get_user_guilds())

    return redirect('/dashboard/servers')


def get_user():
    discord = make_session(token=session.get('oauth2_token'))
    user = discord.get(API_BASE_URL + '/users/@me').json()
    return user


def get_user_guilds():
    # Let's try to prevent a rate limit.
    if int(session.get('rate_limit_remaining', 1)) < 1 and int(session.get('rate_limit_reset', 0)) > time.time():
        return get_cached_user_guilds(session.get('user', {'id': 0})['id'])

    # Ooops.... We've already been rate limited.
    elif int(session.get('rate_limit_retry', 0)) > time.time():
        return get_cached_user_guilds(session.get('user', {'id': 0})['id'])

    discord = make_session(token=session.get('oauth2_token'))
    guilds = discord.get(API_BASE_URL + '/users/@me/guilds')

    json = guilds.json()

    if isinstance(json, dict) and json.get('message', '') == 'You are being rate limited.':
        # Discord docs say retry time is in milliseconds, but it is actually in seconds!??
        session['rate_limit_retry'] = time.time() + int(json.get('retry_after', 1))
        return get_cached_user_guilds(session.get('user', {'id': 0})['id'])

    session['rate_limit_remaining'] = guilds.headers.get('X-RateLimit-Remaining', 1)
    session['rate_limit_reset'] = guilds.headers.get('X-RateLimit-Reset', 0)

    return json


def requires_auth(func):
    @wraps(func)
    def decorator(*args, **kwargs):
        if session.get('oauth2_token') is None or session.get('user') is None:
            return redirect('/dashboard/login')
        return func(*args, **kwargs)
    return decorator


def requires_server(func):
    @wraps(func)
    def decorator(*args, **kwargs):
        if session.get('active_server') is None:
            return redirect('/dashboard/servers')
        return func(*args, **kwargs)
    return decorator


@app.route('/dashboard/servers')
@requires_auth
def servers():
    perms = [2146958591, 8]
    guilds = [g for g in get_user_guilds() if g.get('owner', False) or g.get('permissions, 0') in perms]
    return render_template('servers.html', servers=guilds)


@app.route('/dashboard/server/<server>')
@requires_auth
def set_server(server):
    guild = get_guild_data(server)

    if guild:
        perms = [2146958591, 8]
        guilds = [g['id'] for g in get_user_guilds() if g.get('owner', False) or g.get('permissions, 0') in perms]

        if server in guilds:
            session['active_server'] = server
            return redirect('/dashboard')

        return redirect('/dashboard/servers')
    else:
        return render_template('invite.html')


@app.route('/dashboard')
@requires_auth
@requires_server
def index():
    rpc = get_rpc_client()
    plugins = rpc.installed_plugins()
    enabled_plugins = plugins_for_server(session.get('active_server'))
    guilds = {g['id']: g['name'] for g in get_cached_user_guilds(session.get('user')['id'])}

    return render_template(
        'dashboard_home.html',
        plugins=plugins,
        enabled_plugins=enabled_plugins,
        server_name=guilds.get(session.get('active_server'), session.get('active_server')),
        server_config=get_server_config(session.get('active_server')),
        guild_data=get_guild_data(session.get('active_server'))
    )


@app.route('/dashboard/plugins/<plugin>')
@requires_auth
@requires_server
def get_plugin(plugin):
    rpc = get_rpc_client()

    if plugin not in rpc.installed_plugins():
        abort(403)

    enabled_plugins = plugins_for_server(session.get('active_server'))
    guilds = {g['id']: g['name'] for g in get_cached_user_guilds(session.get('user')['id'])}

    su = rpc.is_user_su(session.get('user')['id'])

    if os.path.isfile(os.path.join('templates', plugin + '.html')):
        return render_template(plugin + '.html')
    else:
        return render_template(
            'default_plugin.html',
            plugins=rpc.installed_plugins(),
            plugin=plugin,
            commands=rpc.commands_for_plugin(plugin),
            enabled_plugins=enabled_plugins,
            enabled_commands=enabled_plugins.get(plugin, []),
            server_name=guilds.get(session.get('active_server'), session.get('active_server')),
            su=su
        )


@app.route('/dashboard/disable_command/<command>', methods=['POST'])
@requires_auth
@requires_server
def disable_command(command):
    ret = mongo_disable_cmd(session.get('active_server'), command)
    return jsonify(status=('error', 'ok')[bool(ret)])


@app.route('/dashboard/enable_command/<command>', methods=['POST'])
@requires_auth
@requires_server
def enable_command(command):
    ret = mongo_enable_cmd(session.get('active_server'), command)
    return jsonify(status=('error', 'ok')[bool(ret)])


@app.route('/dashboard/enable_plugin/<plugin>', methods=['POST'])
@requires_auth
@requires_server
def enable_plugin(plugin):
    ret = mongo_enable_plugin(session.get('active_server'), plugin)

    if ret:
        flash('OK! Configuration updated!')
        return redirect(f'/dashboard/plugins/{plugin}')
    else:
        flash('Oops! Something went wrong...')
        return redirect('/dashboard')


@app.route('/dashboard/disable_plugin/<plugin>', methods=['POST'])
@requires_auth
@requires_server
def disable_plugin(plugin):
    ret = mongo_disable_plugin(session.get('active_server'), plugin)

    if ret:
        flash('OK! Configuration updated!')
    else:
        flash('Oops! Something went wrong...')

    return redirect('/dashboard')


@app.route('/dashboard/update_config', methods=['POST'])
@requires_auth
@requires_server
def update_config():
    data = dict(request.form)

    if data.get('prefix')[0]:
        ret = set_prefix(session.get('active_server'), data.get('prefix')[0])
    else:
        ret = False

    if ret:
        flash('OK! Configuration updated!')
    else:
        flash('Oops! Something went wrong...')

    return redirect('/dashboard')


if __name__ == '__main__':
    app.run()
