import json
from datetime import datetime, timezone

import aiohttp

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
              Page(page: $page, perPage:25){
                pageInfo {
                  currentPage
                  lastPage
                }

                airingSchedules(airingAt_greater:$start, airingAt_lesser:$end, sort:TIME){
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
