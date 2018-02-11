# Marko

A (not yet complete) Discord bot which started as a simple side project.

## Running The Bot

First things first, you must edit the example config provided to suit your needs and then create a Discord app.
(https://discordapp.com/developers/docs/intro)
Create a bot user and keep note of the user token.

_example_config.yaml_
```
mbot:
    key: DISCORD_BOT_TOKEN_GOES_HERE  # CHANGEME
    cmd_prefix: m!  # This is a default value. This can also be changed on a per server basis.

mongo:
  host: localhost
  port: 12345

# Superusers are bot admins (usually the owners) and can
# do things like reload plugins globally, etc...
# You should place your UID into here...
# ...Right click your user in Discord and click "Copy ID"... Put that here.
superusers:
    - DISCORD_UID_OF_ADMIN_1  # CHANGEME
```

### Linux
This config probably won't work on some linux builds due to some of the requirements (python 3.6, ffmpeg, etc...)
The below setup was tested on Ubuntu 17.10 x64. Python 3.6 is required.
ffmpeg and libopus are used for voice chat support.

```
~/mBot/: apt-get update -y && apt-get upgrade -y
~/mBot/: apt-get install python3-pip python3-venv libogg0 libopus0 opus-tools ffmpeg mongodb
~/mBot/: shutdown -r now
~/mBot/: python3 -m venv venv
~/mBot/: mongod --dbpath data/mongo/ --port 12345 --fork --logpath log/mongodb.log
~/mBot/: source venv/vin/activate
(venv) ~/mBot/: pip install -r requirements.txt
(venv) ~/mBot/: python -m mbot --config example_config.yaml
```

### Windows
Windows instructions are, for the most part, the same. However you must manually download the mongodb binaries.
That's it! ffmpeg and libopus dll's are provided. Just setup a venv and run.


## To-do
Finish.
