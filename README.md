# MarkoBot

```
~/mBot/: apt-get update -y && apt-get upgrade -y
~/mBot/: apt-get install python3-pip python3-venv libogg0 libopus0 opus-tools ffmpeg mongodb
~/mBot/: shutdown -r now
~/mBot/: python3 -m venv venv
~/mBot/: mongod --dbpath data/mongo/ --port 12345 --fork --logpath log/mongodb.log
~/mBot/: source venv/vin/activate
(venv) ~/mBot/: pip install -r requirements.txt
(venv) ~/mBot/: python -m mbot
```
