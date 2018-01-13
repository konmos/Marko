import aiohttp
import discord
from urllib.parse import urlencode

from ..plugin import BasePlugin
from ..command import command


class SearchEngine(BasePlugin):
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
            params = urlencode(kwargs)
        )

        with aiohttp.ClientSession() as client:
            async with client.get(api) as r:
                j = await r.json()

        return j

    @command(regex='^search (.*?)$', cooldown=5, usage='search <term>', description='search the web')
    async def search(self, message, query):
        result = await self.search_ddg(q=query, format='json', no_html=1, skip_disambig=1, no_redirect=1)

        if not result['AbstractText']:
            await self.mbot.send_message(message.channel, 'I couldn\'t find anything matching that query. :cry:')
        else:
            embed = discord.Embed(
                title = result['Heading'],
                description = result['AbstractText'],
                colour = 0xff5722
            )

            embed.set_footer(text='Web search powered by https://duckduckgo.com/')
            embed.set_thumbnail(url=result['Image'])
            embed.add_field(name='source', value=result['AbstractURL'])

            await self.mbot.send_message(message.channel, embed=embed)
