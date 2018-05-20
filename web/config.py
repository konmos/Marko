'''Web app specific configuration.'''

import os

__all__ = [
    'RPC_HOST',
    'MONGO_HOST',
    'OAUTH2_CLIENT_ID',
    'OAUTH2_CLIENT_SECRET',
    'OAUTH2_REDIRECT_URI',
    'API_BASE_URL',
    'AUTHORIZATION_BASE_URL',
    'TOKEN_URL'
]

RPC_HOST = os.environ.get('RPC_HOST', 'tcp://127.0.0.1:4243')
MONGO_HOST = os.environ.get('MONGO_HOST', 'mongodb://localhost:27017/')

OAUTH2_CLIENT_ID = os.environ['OAUTH2_CLIENT_ID']
OAUTH2_CLIENT_SECRET = os.environ['OAUTH2_CLIENT_SECRET']
OAUTH2_REDIRECT_URI = 'http://localhost:5000/dashboard/auth'

API_BASE_URL = os.environ.get('API_BASE_URL', 'https://discordapp.com/api')
AUTHORIZATION_BASE_URL = API_BASE_URL + '/oauth2/authorize'
TOKEN_URL = API_BASE_URL + '/oauth2/token'
