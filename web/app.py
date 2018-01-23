import os
import zerorpc
from flask import Flask, render_template

app = Flask(__name__)


def rpc_client(host='tcp://127.0.0.1', port=4242):
    c = zerorpc.Client()
    c.connect(f'{host}:{port}')
    return c


PLUGINS = rpc_client().all_plugins()


@app.route("/")
def hello():
    plugins = PLUGINS
    return render_template('default.html', plugins=plugins)


@app.route('/plugins/<plugin>')
def get_plugin(plugin):
    plugins = PLUGINS

    if os.path.isfile(os.path.join('templates', plugin + '.html')):
        return render_template(plugin + '.html')
    else:
        return render_template('default_plugin.html', plugins=plugins, plugin=plugin, commands=plugins[plugin])


app.run(debug=True)
