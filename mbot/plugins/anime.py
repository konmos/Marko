import json
import random
import logging
import asyncio
from datetime import datetime, timezone

import aiohttp
from pymongo import UpdateOne
from discord import Embed, NotFound, HTTPException
from bs4 import BeautifulSoup

from ..plugin import BasePlugin
from ..command import command


log = logging.getLogger(__name__)

USER_AGENT = 'Mozilla/5.0 (Windows NT 6.1; Win64; x64; rv:10.0) Gecko/20100101 Firefox/10.0'
ANILIST_API = 'https://graphql.anilist.co'
MAX_PAGE_LIMIT = 6


# TODO: take rate limits into consideration
# TODO: filter NSFW results


class Anime(BasePlugin):
    def __init__(self, mbot):
        super().__init__(mbot)

        self.subs_db = self.mbot.mongo.plugin_data.anime_subs
        self.acc_db = self.mbot.mongo.plugin_data.anime_accounts

        self.mbot.loop.create_task(self.subscriber_loop())
        self.mbot.loop.create_task(self.account_sync_loop())

    async def _do_anilist_query(self, url, query, variables):
        with aiohttp.ClientSession() as client:
            async with client.post(
                    url,
                    data=json.dumps({'query': query, 'variables': variables}),
                    headers={'Content-Type': 'application/json'}
            ) as r:
                j = await r.json()

        return j

    async def anilist_query(self, query, variables, all_pages=True):
        results = [await self._do_anilist_query(ANILIST_API, query, variables)]

        if all_pages:
            current_page = results[0]['data']['Page']['pageInfo']['currentPage']
            last_page = results[0]['data']['Page']['pageInfo']['lastPage']

            while current_page < last_page and current_page <= MAX_PAGE_LIMIT:
                j = await self._do_anilist_query(ANILIST_API, query, {**variables, 'page': current_page + 1})
                results.append(j)
                current_page += 1

            if current_page != last_page:
                log.error(
                    f'failed to get all anilist pages [{query} {variables} {current_page} {last_page}]'
                )

        return results or [{'data': None}]

    @staticmethod
    def calc_day_distance(start_weekday, human_day):
        days_map = {'monday': 0, 'tuesday': 1, 'wednesday': 2, 'thursday': 3, 'friday': 4, 'saturday': 5, 'sunday': 6}

        if human_day == 'tomorrow':
            return 1
        elif human_day == 'today':
            return 0

        if start_weekday < days_map[human_day]:
            return days_map[human_day] - start_weekday
        else:
            return 7 - (start_weekday - days_map[human_day])

    @command(regex='^airing (today|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday)$')
    async def airing(self, message, when):
        now = datetime.now(timezone.utc)
        day_diff = self.calc_day_distance(now.weekday(), when)

        query = '''
            query ($page: Int, $start: Int, $end: Int) {
              Page(page: $page, perPage: 25) {
                pageInfo {
                  currentPage
                  lastPage
                }

                airingSchedules(airingAt_greater: $start, airingAt_lesser: $end, sort: TIME) {
                  episode
                  airingAt
                  media {
                    id
                    title {
                      romaji
                      english
                    }
                  }
                }
              }
            }'''

        start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc).timestamp() + (day_diff * 24 * 60 * 60)

        variables = {
            'page': 1,
            'start': start - 1,
            'end': start + (24 * 60 * 60)
        }

        results, s = await self.anilist_query(query, variables), ''

        for result in results:
            for anime in result['data']['Page']['airingSchedules']:
                airing = datetime.utcfromtimestamp(anime['airingAt']).strftime('%H:%M')
                s += f'{airing} - {anime["media"]["title"]["english"] or anime["media"]["title"]["romaji"]}' \
                     f' #{anime["episode"]}\n'

        if s:
            return await self.mbot.send_message(
                message.channel, f'**Anime airings for `{when}`.** All times are UTC.\n```{s}```'
            )

        await self.mbot.send_message(
            message.channel, 'I could not find any anime airings.'
        )

    async def _get_media_embed(self, variables):
        query = '''
            query ($search: String, $id: Int, $idMal: Int, $type: MediaType) {
              Page(perPage: 1) {
                media(search: $search, id: $id, idMal: $idMal, type: $type) {
                  id format idMal description status genres hashtag
                  synonyms averageScore episodes duration source
                  chapters volumes type
                  startDate {
                    year
                    month
                    day
                  }
                  endDate {
                    year
                    month
                    day
                  }
                  coverImage {
                    medium
                  }
                  title {
                    romaji
                    english
                    native
                  }
                }
              }
            }'''

        results = await self.anilist_query(query, variables, False)

        if not results[0]['data'] or not results[0]['data']['Page']['media']:
            return None

        media = results[0]['data']['Page']['media'][0]

        e = Embed(
            title=f'{media["title"]["english"] or media["title"]["romaji"]} ({media["title"]["native"]})',
            description=f'{BeautifulSoup(media["description"], "html.parser").get_text()}',
            color=0x984e3 if media['type'] == 'ANIME' else 0x00b894
        )

        try:
            start_date = datetime(
                media['startDate']['year'], media['startDate']['month'], media['startDate']['day']
            )
        except (ValueError, TypeError):
            start_date = ''

        try:
            end_date = datetime(
                media['endDate']['year'], media['endDate']['month'], media['endDate']['day']
            )
        except (ValueError, TypeError):
            end_date = ''

        date_string = ''

        if start_date:
            date_string = start_date.strftime('%d %B %Y')

            if end_date:
                date_string += f' - {end_date.strftime("%d %B %Y")}'

        e.set_thumbnail(url=media['coverImage']['medium'])

        e.add_field(
            name='Status',
            value=f'{media["status"].capitalize().replace("_", " ")}'
                  f'{(" [" + date_string + "]") if date_string else ""}'
        )

        if media['source']:
            e.add_field(name='Source', value=media['source'].capitalize().replace('_', ' '))

        if media['synonyms']:
            e.add_field(name='AKA', value=', '.join(media['synonyms']))

        e.add_field(name='Format', value=media['format'])

        if media['genres']:
            e.add_field(name='Genres', value=', '.join(media['genres']))

        if media['type'] == 'ANIME':
            e.add_field(name='Episodes', value=f'{media["episodes"] or "~"} ({media["duration"] or "~"} minutes/ep)')
        else:
            e.add_field(name='Volumes', value=f'{media["volumes"] or "~"} ({media["chapters"] or "~"} chapters)')

        e.add_field(name='Average Score', value=f'{media["averageScore"] or "0"}%')

        e.add_field(
            name='Links',
            value=f'[AniList](https://anilist.co/{"anime" if media["type"] == "ANIME" else "manga"}/{media["id"]}) - '
                  f'[MAL](https://myanimelist.net/{"anime" if media["type"] == "ANIME" else "manga"}/{media["idMal"]})',
            inline=False
        )

        if media['hashtag']:
            e.set_footer(text=media['hashtag'])

        return e

    async def parse_query(self, query, media_type):
        if query == 'random':
            return {'id': await self._get_random_media(media_type)}
        elif query.startswith('title:'):
            return {'search': query[6:].strip()}
        elif query.startswith('id:'):
            return {'id': query[3:].strip()}
        elif query.startswith('mal:'):
            return {'idMal': query[4:].strip()}
        else:
            return {'search': query}

    async def get_media_embed(self, query, media_type):
        q = await self.parse_query(query, media_type)
        return await self._get_media_embed({**q, 'type': media_type})

    async def _get_random_media(self, media_type):
        query = '''
            query ($type: MediaType, $page: Int) {
              Page(page: $page, perPage: 1) {
                pageInfo {
                  currentPage
                  lastPage
                }

                media(type: $type) {
                  id
                }
              }
            }'''

        q = await self.anilist_query(query, {'type': media_type}, False)
        page = random.randint(1, q[0]['data']['Page']['pageInfo']['lastPage'])

        result = await self.anilist_query(query, {'type': media_type, 'page': page}, False)
        return result[0]['data']['Page']['media'][0]['id']

    @command(regex='^anime (.*?)$')
    async def anime(self, message, query):
        e = await self.get_media_embed(query, 'ANIME')

        if not e:
            return await self.mbot.send_message(
                message.channel, '**I could not find any media matching that query...** :cry:'
            )

        await self.mbot.send_message(
            message.channel, embed=e
        )

    @command(regex='^manga (.*?)$')
    async def manga(self, message, query):
        e = await self.get_media_embed(query, 'MANGA')

        if not e:
            return await self.mbot.send_message(
                message.channel, '**I could not find any media matching that query...** :cry:'
            )

        await self.mbot.send_message(
            message.channel, embed=e
        )

    async def _update_episode(self, anilist_id):
        await asyncio.sleep(60 * 5)

        query = '''
           query ($id: Int, $type: MediaType=ANIME) {
             Page(perPage: 1){
               media(id: $id, type: $type){
                 nextAiringEpisode {
                   episode airingAt
                 }
               }
             }
           }'''

        result = await self.anilist_query(query, {'id': anilist_id}, False)

        _data = result[0]['data']

        if not _data or not _data['Page']['media'] or not _data['Page']['media'][0]['nextAiringEpisode']:
            await self.subs_db.delete_one(
                {'anilist_id': anilist_id}
            )
        else:
            await self.subs_db.update_one(
                {'anilist_id': anilist_id},
                {'$set': {
                    'next_ep': {
                        'episode': _data['Page']['media'][0]['nextAiringEpisode']['episode'],
                        'airing_at': _data['Page']['media'][0]['nextAiringEpisode']['airingAt']
                    },
                    'notified': False
                }}
            )

    async def subscriber_loop(self):
        await self.mbot.wait_until_ready()

        while not self.mbot.is_closed:
            tstamp = datetime.now(timezone.utc).timestamp()

            async for document in self.subs_db.find({'next_ep.airing_at': {'$lte': tstamp + 60}, 'notified': False}):
                for user in document['subs']:
                    try:
                        u = await self.mbot.get_user_info(user)
                        e = Embed(
                            description=f'Episode `{document["next_ep"]["episode"]}/{document["episodes"]}` of '
                                        f'`{document["title"]["english"] or document["title"]["romaji"]}` is '
                                        f'now airing!\n\n**Duration:** {document["duration"]} minutes.\n\n'
                                        f'[AniList](https://anilist.co/anime/{document["anilist_id"]}) - '
                                        f'[MAL](https://myanimelist.net/anime/{document["mal_id"]})'
                            ,
                            title=f'{document["title"]["english"] or document["title"]["romaji"]} '
                                  f'({document["title"]["native"]})',
                            color=0x984e3
                            )

                        if document['image']:
                            e.set_thumbnail(url=document['image'])

                        e.timestamp = datetime.now(timezone.utc)
                        self.mbot.loop.create_task(self.mbot.send_message(u, embed=e))
                    except (NotFound, HTTPException):
                        pass

                    await self.subs_db.update_one(
                        {'anilist_id': document['anilist_id']},
                        {'$set': {'notified': True}}
                    )

                    self.mbot.loop.create_task(self._update_episode(document['anilist_id']))

            await asyncio.sleep(60)

    async def _sync(self, account, user_id):
        if account.startswith('anilist/'):
            source, anime = 'anilist', await self.get_user_anime_anilist(account[8:])
        else:
            source, anime = 'mal', await self.get_user_anime_mal(account[4:])

        if anime:
            await self._bulk_subscribe(anime, source, user_id)

    async def account_sync_loop(self):
        await self.mbot.wait_until_ready()

        while not self.mbot.is_closed:
            async for doc in self.acc_db.find():
                for account in doc['linked_accounts']:
                    self.mbot.loop.create_task(
                        self._sync(account, doc['user_id'])
                    )

            await asyncio.sleep(24 * 60 * 60)

    async def _bulk_subscribe(self, id_list, source, user_id):
        # NOTE: `id_list` should not be a mix of anilist ID's and MAL ID's. It should be one or the other!!!
        to_sub = []

        for id_ in id_list:
            _doc = await self.subs_db.find_one(
                {'anilist_id' if source == 'anilist' else 'mal_id': id_}
            )

            if not _doc or user_id not in _doc['subs']:
                to_sub.append(id_)

        if not to_sub:
            return

        q = '''
            query ($id_in: [Int], $idMal_in: [Int], $page: Int, $type: MediaType=ANIME) {
              Page(page: $page, perPage: 25){
                pageInfo {
                  currentPage
                  lastPage
                }
                media(id_in: $id_in, idMal_in: $idMal_in, type: $type){
                  id episodes idMal duration
                  nextAiringEpisode {
                    episode airingAt
                  }
                  title {
                    romaji english native
                  }
                  coverImage {
                    medium
                  }
                }
              }
            }'''

        variables = {'id_in' if source == 'anilist' else 'idMal_in': to_sub}
        results = await self.anilist_query(q, variables)

        if not results[0]['data'] or not results[0]['data']['Page']['media']:
            return

        bulk = []

        for media in results[0]['data']['Page']['media']:
            if media['nextAiringEpisode']:
                bulk.append(UpdateOne(
                    {'anilist_id': media['id']},
                    {
                        '$setOnInsert': {
                            'mal_id': media['idMal'],
                            'notified': False,
                            'image': media['coverImage']['medium'],
                            'duration': media['duration'],
                            'title': {
                                'romaji': media['title']['romaji'],
                                'english': media['title']['english'],
                                'native': media['title']['native']
                            },
                            'next_ep': {
                                'episode': media['nextAiringEpisode']['episode'],
                                'airing_at': media['nextAiringEpisode']['airingAt']
                            },
                            'episodes': media['episodes']
                        },
                        '$addToSet': {'subs': user_id}
                    },
                    upsert=True
                ))

        if bulk:
            await self.subs_db.bulk_write(bulk)

    async def _subscribe_to_anime(self, query, user_id):
        variables = await self.parse_query(query, 'ANIME')

        q = '''
            query ($search: String, $id: Int, $idMal: Int, $type: MediaType=ANIME) {
              Page(perPage: 1){
                media(search: $search, id: $id, idMal: $idMal, type: $type){
                  id episodes idMal duration
                  nextAiringEpisode {
                    episode airingAt
                  }
                  title {
                    romaji english native
                  }
                  coverImage {
                    medium
                  }
                }
              }
            }'''

        results = await self.anilist_query(q, variables, False)

        if not results[0]['data'] or not results[0]['data']['Page']['media']:
            return

        media = results[0]['data']['Page']['media'][0]

        if not media['nextAiringEpisode']:
            return

        ret = await self.subs_db.update_one(
            {'anilist_id': media['id']},
            {
                '$setOnInsert': {
                    'mal_id': media['idMal'],
                    'notified': False,
                    'image': media['coverImage']['medium'],
                    'duration': media['duration'],
                    'title': {
                        'romaji': media['title']['romaji'],
                        'english': media['title']['english'],
                        'native': media['title']['native']
                    },
                    'next_ep': {
                        'episode': media['nextAiringEpisode']['episode'],
                        'airing_at': media['nextAiringEpisode']['airingAt']
                    },
                    'episodes': media['episodes']
                },
                '$addToSet': {'subs': user_id}
            },
            upsert=True
        )

        if ret.modified_count == 1 or ret.upserted_id is not None:
            return media

    @command(regex='^subscribe (.*?)$')
    async def subscribe(self, message, query):
        media = await self._subscribe_to_anime(query, message.author.id)

        if media is None:
            return await self.mbot.send_message(
                message.channel,
                '**Could not subscribe to this anime.**'
            )

        await self.mbot.send_message(
            message.channel,
            f'**Successfully subscribed to `{media["title"]["english"] or media["title"]["romaji"]}`!**\n'
            'You will be notified when new episodes of this anime air.'
        )

    async def _fetch_user_subs(self, user_id, page):
        subs = []

        async for sub in self.subs_db.find({'subs': user_id}).skip(page * 12).limit(12):
            subs.append(sub)

        return subs

    @command()
    async def mysubs(self, message):
        page = 0

        while True:
            subs = await self._fetch_user_subs(message.author.id, page)
            next_page = await self._fetch_user_subs(message.author.id, page + 1)

            # noinspection PyUnresolvedReferences
            m = '\n'.join(
                [f'{sub["title"]["english"] or sub ["title"]["romaji"]} ({sub["title"]["native"]})' for sub in subs]
            )

            if not next_page and page == 0:
                return await self.mbot.send_message(
                    message.channel, f'```{m}```'
                )

            option = await self.mbot.option_selector(
                message, f'```{m}```', {}, timeout=30, pp=page != 0, np=bool(next_page)
            )

            if not option:
                return await self.mbot.send_message(
                    message.channel, '**Closing menu.**'
                )

            if option == 'np':
                page += 1
            elif option == 'pp':
                page -= 1

    async def get_user_anime_anilist(self, username):
        query = '''
            query ($page: Int, $userName: String) {
              Page(page: $page, perPage:25){
                pageInfo {
                  currentPage
                  lastPage
                }
                
                mediaList(userName: $userName, status: CURRENT){
                  media{
                    id  
                  }
                }
              }
            }
            '''

        anime_list = []
        results = await self.anilist_query(query, {'page': 1, 'userName': username})

        for page in results:
            if not page['data'] or not page['data']['Page']['mediaList']:
                continue

            anime_list.extend(
                x["media"]["id"] for x in page['data']['Page']['mediaList']
            )

        return anime_list

    async def get_user_anime_mal(self, username):
        with aiohttp.ClientSession(headers={'User-Agent': USER_AGENT}) as client:
            async with client.get(f'https://myanimelist.net/animelist/{username}?status=1') as r:
                html = await r.text()

        soup = BeautifulSoup(html, 'html.parser')

        try:
            j = json.loads(soup.find(attrs={'class': 'list-table'})['data-items'])

            return [entry["anime_id"] for entry in j]
        except TypeError:
            return []

    @command(regex='^anime-link (.*?)$', name='anime-link')
    async def account_link(self, message, uri):
        await self.acc_db.update_one(
            {'user_id': message.author.id},
            {'$addToSet': {'linked_accounts': uri}},
            upsert=True
        )

        await self._sync(uri, message.author.id)
