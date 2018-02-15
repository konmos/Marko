import os
import zerorpc
from flask import Flask, render_template, session, redirect, request, url_for, flash
from requests_oauthlib import OAuth2Session
from functools import wraps


RPC_HOST = os.environ.get('RPC_HOST', 'tcp://127.0.0.1:4243')

OAUTH2_CLIENT_ID = os.environ['OAUTH2_CLIENT_ID']
OAUTH2_CLIENT_SECRET = os.environ['OAUTH2_CLIENT_SECRET']
OAUTH2_REDIRECT_URI = 'http://localhost:5000/dashboard/auth'

API_BASE_URL = os.environ.get('API_BASE_URL', 'https://discordapp.com/api')
AUTHORIZATION_BASE_URL = API_BASE_URL + '/oauth2/authorize'
TOKEN_URL = API_BASE_URL + '/oauth2/token'

app = Flask(__name__)
app.debug = True
app.config['SECRET_KEY'] = OAUTH2_CLIENT_SECRET

if 'http://' in OAUTH2_REDIRECT_URI:
    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = 'true'


def rpc_client():
    client = zerorpc.Client()
    client.connect(RPC_HOST)
    return client


PLUGINS = rpc_client().installed_plugins()


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


@app.route('/dashboard/login')
def auth():
    scope = request.args.get(
        'scope',
        'identify guilds'
    )

    discord = make_session(scope=scope.split(' '))
    authorization_url, state = discord.authorization_url(AUTHORIZATION_BASE_URL)
    session['oauth2_state'] = state
    return redirect(authorization_url)


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

    user = user_data()
    session['user'] = user['user']
    session['guilds'] = user['guilds']
    return redirect('/dashboard/servers')


def user_data():
    discord = make_session(token=session.get('oauth2_token'))
    user = discord.get(API_BASE_URL + '/users/@me').json()
    guilds = discord.get(API_BASE_URL + '/users/@me/guilds').json()

    return {
        'user': user,
        'guilds': guilds
    }


def requires_auth(func):
    @wraps(func)
    def decorator(*args, **kwargs):
        if session.get('oauth2_token') is None:
            return redirect('/dashboard/login')

        if session.get('user') is None or session.get('guilds') is None:
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
    guilds = []
    for guild in session.get('guilds'):
        if guild['owner'] or guild['permissions'] in [2146958591, 8]:
            guilds.append(guild)

    return render_template('servers.html', servers=guilds)


# TODO: lots of security stuff BUT most importantly change this VVV
# to prevent arbitrary server id's and unauthorised management
# should also add a check for rate limiting
@app.route('/dashboard/server/<server>')
@requires_auth
def set_server(server):
    session['active_server'] = server
    return redirect('/dashboard')


@app.route('/dashboard')
@requires_auth
@requires_server
def index():
    plugins, enabled_plugins = PLUGINS, rpc_client().plugins_for_server(session.get('active_server'))
    print(enabled_plugins)
    return render_template('default.html', plugins=plugins, enabled_plugins=enabled_plugins)


@app.route('/dashboard/plugins/<plugin>')
@requires_auth
@requires_server
def get_plugin(plugin):
    rpc = rpc_client()
    enabled_plugins = rpc.plugins_for_server(session.get('active_server'))

    if os.path.isfile(os.path.join('templates', plugin + '.html')):
        return render_template(plugin + '.html')
    else:
        return render_template(
            'default_plugin.html',
            plugins=PLUGINS,
            plugin=plugin,
            commands=rpc.commands_for_plugin(plugin),
            enabled_plugins=enabled_plugins,
            enabled_commands=enabled_plugins.get(plugin, [])
        )


@app.route('/dashboard/update_commands', methods=['POST'])
@requires_auth
@requires_server
def update_commands():
    rpc = rpc_client()

    data = dict(request.form)
    plugin = data['_plugin'][0]

    commands = rpc.commands_for_plugin(plugin)
    enabled_commands = rpc.plugins_for_server(session.get('active_server')).get(plugin)

    to_disable, to_enable = [], []

    for cmd in commands:
        if cmd in enabled_commands and cmd not in data:
            # command was disabled
            to_disable.append(cmd)
        elif cmd in data and cmd not in enabled_commands:
            # command was enabled
            to_enable.append(cmd)

    enabled = rpc.enable_commands(session.get('active_server'), to_enable)
    disabled = rpc.disable_commands(session.get('active_server'), to_disable)

    if enabled and disabled:
        flash('OK! Configuration updated!')
    else:
        flash('Oops! Something went wrong...')

    return redirect(f'/dashboard/plugins/{plugin}')


if __name__ == '__main__':
    app.run()
