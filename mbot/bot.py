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

    # This helps us find ffmpeg for the voice player.
    if os.name in ['nt', 'ct']:
        os.environ['PATH'] += f';bin{os.sep}'
    else:
        os.environ['PATH'] += f':bin/'  # The ffmpeg binary must be copied here manually...

    logging.config.dictConfig(log_conf)
    log = logging.getLogger(__name__)

    parser = argparse.ArgumentParser()
    parser.add_argument('--config', help='path to bot config (default: mbot.yaml)', type=str, default='mbot.yaml')

    subparsers = parser.add_subparsers()

    shard_mode = subparsers.add_parser('shardmode', help='run the bot in shard mode')
    shard_mode.add_argument('--shard-id', type=int, required=True)
    shard_mode.add_argument('--shard-num', type=int, required=True)

    args = vars(parser.parse_args())

    # Set config.
    config = Config(args['config'])
    os.environ['mbot_config'] = args['config']

    log.debug(f'starting bot instance on shard {args.get("shard_id", 0)}/{args.get("shard_num", 1)}')
    mBot(config, shard_id=args.get('shard_id', 0), shard_count=args.get('shard_num', 1)).run()


if __name__ == '__main__':
    main()
