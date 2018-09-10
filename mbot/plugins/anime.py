import json
import random
from datetime import datetime, timezone

import aiohttp
from discord import Embed
from bs4 import BeautifulSoup

from ..plugin import BasePlugin
from ..command import command

ANILIST_API = 'https://graphql.anilist.co'


# TODO: take rate limits into consideration
# TODO: filter NSFW results


class Anime(BasePlugin):
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

            while current_page != last_page:
                j = await self._do_anilist_query(ANILIST_API, query, {**variables, 'page': current_page + 1})
                results.append(j)
                current_page += 1

        return results

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
            query ($search: String, $id: Int, $mal: Int, $type: MediaType) {
              Page(perPage: 1) {
                media(search: $search, id: $id, idMal: $mal, type: $type) {
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

    async def get_media_embed(self, query, media_type):
        variables = {'type': media_type}

        if query == 'random':
            media_id = await self._get_random_media(media_type)
            variables['id'] = media_id
        elif query.startswith('title:'):
            variables['search'] = query[6:].strip()
        elif query.startswith('id:'):
            variables['id'] = query[3:].strip()
        elif query.startswith('mal:'):
            variables['mal'] = query[4:].strip()
        else:
            variables['search'] = query

        return await self._get_media_embed(variables)

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
