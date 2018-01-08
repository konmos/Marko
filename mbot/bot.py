import os
import sys
import argparse
import logging.config

import yaml

from .mbot import mBot
from .config import Config


def main():
    try:
        with open(os.path.join('log', 'logging.yaml')) as fd:
            log_conf = yaml.load(fd)
    except (IOError, WindowsError):
        sys.exit(0)

    if os.name in ['nt', 'ct']:
        os.environ['PATH'] += f';bin{os.sep}'  # This is required on Windows to load the ffmpeg binary.

    logging.config.dictConfig(log_conf)
    log = logging.getLogger(__name__)

    parser = argparse.ArgumentParser()
    parser.add_argument('--config', help='path to bot config (default: mbot.yaml)', type=str, default='mbot.yaml')

    subparsers = parser.add_subparsers()

    shard_mode = subparsers.add_parser('shardmode', help='run the bot in shard mode')
    shard_mode.add_argument('--shard-id', type=int, required=True)
    shard_mode.add_argument('--shard-num', type=int, required=True)

    args = vars(parser.parse_args())

    config = Config(args['config'])

    log.debug(f'starting bot instance on shard {args.get("shard_id", 0)}/{args.get("shard_num", 1)}')
    mBot(config, shard_id=args.get('shard_id', 0), shard_count=args.get('shard_num', 1)).run()


if __name__ == '__main__':
    main()
