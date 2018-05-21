import io

import aiohttp
import discord
from urllib.parse import urlencode

from bs4 import BeautifulSoup

from ..plugin import BasePlugin
from ..command import command


USER_AGENT = 'Mozilla/5.0 (Windows NT 6.1; Win64; x64; rv:10.0) Gecko/20100101 Firefox/10.0'


class Search(BasePlugin):
    @staticmethod
    async def search_ddg(**kwargs):
        '''
        Search duckduckgo.com (https://duckduckgo.com/api)

        This uses the official api which only supports instant answers. This means that many
        queries will return blank. BUT this is by far the best search engine at the moment
        as google's search api is (almost) non existent and has ridiculous rate limiting,
        bing is an unknown, startpage requires scraping due to no api at all... etc.

        duckduckgo will have to do *sigh*

        Supported kwargs:
        q: query

        format: output format (json or xml)
            If format=='json', you can also pass:
            callback: function to callback (JSONP format)
            pretty: 1 to make JSON look pretty (like JSONView for Chrome/Firefox)

        no_redirect: 1 to skip HTTP redirects (for !bang commands).

        no_html: 1 to remove HTML from text, e.g. bold and italics.

        skip_disambig: 1 to skip disambiguation (D) Type.
        '''

        api = 'https://api.duckduckgo.com/?{params}'.format(
            params=urlencode(kwargs)
        )

        with aiohttp.ClientSession() as client:
            async with client.get(api) as r:
                j = await r.json()

        return j

    @staticmethod
    async def search_google(query):
        search = 'https://www.google.com/search?{q}'.format(
            q=urlencode({'q': query})
        )

        with aiohttp.ClientSession(headers={'User-Agent': USER_AGENT}) as client:
            async with client.get(search) as r:
                html = await r.text()

        soup, results = BeautifulSoup(html, 'html.parser'), []

        for u in soup.find_all(attrs={'class': 'g'}):
            if u and hasattr(u, 'a'):
                if u.a['href'].startswith('http'):
                    results.append((
                        u.a['href'],
                        u.text
                    ))
                elif u.a['href'].startswith('/url?q='):
                    results.append((
                        u.a['href'][len('/url?q='):].rsplit('&sa', 1)[0],
                        u.text
                    ))

        return results

    @staticmethod
    async def search_youtube(query):
        search = 'https://www.youtube.com/results?{q}'.format(
            q=urlencode({'search_query': query})
        )

        with aiohttp.ClientSession(headers={'User-Agent': USER_AGENT}) as client:
            async with client.get(search) as r:
                html = await r.text()

        soup, results = BeautifulSoup(html, 'html.parser'), []

        for vid in soup.findAll(attrs={'class': 'yt-uix-tile-link'}):
            if vid:
                results.append('https://www.youtube.com' + vid['href'])

        return results

    @staticmethod
    async def search_google_maps(center, api_key, zoom=15, size='640x640', scale=2, download=False):
        args = {
            'center': center,
            'zoom': zoom,
            'key': api_key,
            'size': size,
            'scale': scale
        }

        search = 'https://maps.googleapis.com/maps/api/staticmap?{params}'.format(
            params=urlencode(args)
        )

        if download:
            with aiohttp.ClientSession() as client:
                async with client.get(search) as r:
                    buffer = io.BytesIO(bytes(await r.read()))

            return buffer

        return search

    @command(regex='^map (.*?)$', name='map')
    async def google_maps(self, message, location):
        api_key = self.mbot.config.plugin_data.get('google_maps', {}).get('api_key')

        if not api_key:
            return await self.mbot.send_message(
                message.channel, '*Well... This shouldn\'t happen. I am missing my maps config.* :cry:'
            )

        url = await self.search_google_maps(location, api_key)

        await self.mbot.send_file(message.channel, fp=url, filename='staticmap.png')

    @command(regex='^abstract (.*?)$', cooldown=10, usage='abstract <term>',
             description='search for a query and return abstract info', aliases=['ddg'])
    async def abstract(self, message, query):
        result = await self.search_ddg(q=query, format='json', no_html=1, skip_disambig=1, no_redirect=1)

        if not result['AbstractText']:
            await self.mbot.send_message(message.channel, 'I couldn\'t find anything matching that query. :cry:')
        else:
            embed = discord.Embed(
                title=result['Heading'],
                description=result['AbstractText'],
                colour=0xff5722
            )

            embed.set_footer(text='Web search powered by https://duckduckgo.com/')
            embed.set_thumbnail(url=result['Image'])
            embed.add_field(name='source', value=result['AbstractURL'])

            await self.mbot.send_message(message.channel, embed=embed)

    @command(regex='^google (.*?)$', cooldown=60, aliases=['search'])
    async def google(self, message, query):
        results = await self.search_google(query)

        if results:
            await self.mbot.send_message(
                message.channel, results[0][0]
            )
        else:
            await self.mbot.send_message(message.channel, 'I couldn\'t find anything matching that query. :cry:')

    @command(regex='^youtube (.*?)$', cooldown=60, aliases=['yt'])
    async def youtube(self, message, query):
        results = await self.search_youtube(query)

        if results:
            await self.mbot.send_message(
                message.channel, results[0]
            )
        else:
            await self.mbot.send_message(message.channel, 'I couldn\'t find anything matching that query. :cry:')
