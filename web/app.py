import os
import zerorpc
from flask import Flask, render_template, session, redirect, request, url_for, flash, get_flashed_messages
from requests_oauthlib import OAuth2Session
from functools import wraps


OAUTH2_CLIENT_ID = os.environ['OAUTH2_CLIENT_ID']
OAUTH2_CLIENT_SECRET = os.environ['OAUTH2_CLIENT_SECRET']
OAUTH2_REDIRECT_URI = 'http://localhost:5000/auth/callback'

API_BASE_URL = os.environ.get('API_BASE_URL', 'https://discordapp.com/api')
AUTHORIZATION_BASE_URL = API_BASE_URL + '/oauth2/authorize'
TOKEN_URL = API_BASE_URL + '/oauth2/token'

app = Flask(__name__)
app.debug = True
app.config['SECRET_KEY'] = OAUTH2_CLIENT_SECRET

if 'http://' in OAUTH2_REDIRECT_URI:
    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = 'true'


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


@app.route('/auth')
def auth():
    scope = request.args.get(
        'scope',
        'identify guilds'
    )

    discord = make_session(scope=scope.split(' '))
    authorization_url, state = discord.authorization_url(AUTHORIZATION_BASE_URL)
    session['oauth2_state'] = state
    return redirect(authorization_url)


@app.route('/auth/callback')
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
    return redirect(url_for('.me'))


def user_data():
    discord = make_session(token=session.get('oauth2_token'))
    user = discord.get(API_BASE_URL + '/users/@me').json()
    guilds = discord.get(API_BASE_URL + '/users/@me/guilds').json()

    return {
        'user': user,
        'guilds': guilds
    }


@app.route('/me')
def me():
    user = user_data()
    session['user'] = user['user']
    session['guilds'] = user['guilds']
    return redirect(url_for('.servers'))


def requires_auth(func):
    @wraps(func)
    def decorator(*args, **kwargs):
        if session.get('oauth2_token') is None:
            return redirect(url_for('.auth'))

        if session.get('user') is None or session.get('guilds') is None:
            return redirect(url_for('.auth'))

        return func(*args, **kwargs)

    return decorator


def requires_server(func):
    @wraps(func)
    def decorator(*args, **kwargs):
        if session.get('active_server') is None:
            return redirect(url_for('.servers'))

        return func(*args, **kwargs)

    return decorator


def rpc_client(host='tcp://127.0.0.1', port=4242):
    c = zerorpc.Client()
    c.connect(f'{host}:{port}')
    return c


PLUGINS = rpc_client().all_plugins()


@app.route('/servers')
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
@app.route('/server/<server>')
@requires_auth
def set_server(server):
    session['active_server'] = server
    return redirect('/')


@app.route('/')
@requires_auth
@requires_server
def index():
    plugins, enabled_plugins = PLUGINS, rpc_client().plugins_for_server(session.get('active_server'))
    return render_template('default.html', plugins=plugins, enabled_plugins=enabled_plugins)


@app.route('/plugins/<plugin>')
@requires_auth
@requires_server
def get_plugin(plugin):
    plugins, enabled_plugins = PLUGINS, rpc_client().plugins_for_server(session.get('active_server'))

    if os.path.isfile(os.path.join('templates', plugin + '.html')):
        return render_template(plugin + '.html')
    else:
        return render_template(
            'default_plugin.html',
            plugins=plugins,
            plugin=plugin,
            commands=plugins[plugin],
            enabled_plugins=enabled_plugins,
            enabled_commands=enabled_plugins.get(plugin, [])
        )


@app.route('/update_commands', methods=['POST'])
@requires_auth
@requires_server
def update_commands():
    rpc = rpc_client()

    data = dict(request.form)
    plugin = data['_plugin'][0]
    ret = []

    commands, enabled_commands = PLUGINS[plugin], rpc_client().plugins_for_server(session.get('active_server'))[plugin]

    for cmd in commands:
        if cmd in enabled_commands and cmd not in data:
            # command was disabled
            ret.extend(rpc.disable_commands(session.get('active_server'), [cmd]))
        elif cmd in data and cmd not in enabled_commands:
            # command was enabled
            ret.extend(rpc.enable_commands(session.get('active_server'), [cmd]))

    if not ret or all(ret):
        flash('OK! Configuration updated!')
    else:
        flash('Oops! Something went wrong...')

    return redirect(f'/plugins/{plugin}')


if __name__ == '__main__':
    app.run()
