# -*- coding: utf-8 -*-
# Copyright 2012 Nicolas Wack <wackou@gmail.com>
#
# This file is part of subliminal.
#
# subliminal is free software; you can redistribute it and/or modify it under
# the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# subliminal is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with subliminal.  If not, see <http://www.gnu.org/licenses/>.
from . import ServiceBase
from ..subtitles import get_subtitle_path, ResultSubtitle
from ..videos import Episode
from subliminal.utils import get_keywords, split_keyword
from ..bs4wrapper import BeautifulSoup
from ..cache import cachedmethod
import guessit
import logging
import re
import unicodedata
import urllib


logger = logging.getLogger(__name__)

def match(pattern, string):
    try:
        return re.search(pattern, string).group(1)
    except AttributeError:
        logger.debug("Could not match '%s' on '%s'" % (pattern, string))
        return None

class TvSubtitles(ServiceBase):
    server_url = 'http://www.tvsubtitles.net'
    api_based = False
    languages = {u'English (US)': 'en', u'English (UK)': 'en', u'English': 'en', u'French': 'fr', u'Brazilian': 'po',
                 u'Portuguese': 'pt', u'Español (Latinoamérica)': 'es', u'Español (España)': 'es', u'Español': 'es',
                 u'Italian': 'it', u'Català': 'ca',
                 # exceptions
                 u'Portuguese(br)': 'pt', 'Greek': 'gre'
                 }
    reverted_languages = True
    videos = [Episode]
    require_video = False

    def guess_language(self, lang):
        if lang in TvSubtitles.languages:
            return guessit.Language(TvSubtitles.languages[lang])
        return guessit.Language(lang)

    @cachedmethod
    def get_likely_series_id(self, name):
        r = self.session.post('%s/search.php' % self.server_url, data = { 'q': name })
        soup = BeautifulSoup(r.content, 'lxml')
        maindiv = soup.find('div', 'left')
        results = []
        for elem in maindiv.find_all('li'):
            sid = int(match('tvshow-([0-9]+)\.html', elem.a['href']))
            show_name = match('(.*) \(', elem.a.text)
            results.append((show_name, sid))

        # TODO: pick up the best one in a smart way
        result = results[0]

        return result[1]

    @cachedmethod
    def get_episode_id(self, series_id, season, number):
        """Get the TvSubtitles id for the given episode. Raises KeyError if none
        could be found."""
        # download the page of the season, contains ids for all episodes
        episode_id = None
        subtitle_ids = []
        r = self.session.get('%s/tvshow-%d-%d.html' % (self.server_url, series_id, season))
        soup = BeautifulSoup(r.content, 'lxml')
        table = soup.find('table', id = 'table5')
        for row in table.find_all('tr'):
            cells = row.find_all('td')
            if not cells:
                continue

            episode_number = match('x([0-9]+)', cells[0].text)
            if not episode_number:
                continue

            episode_number = int(episode_number)
            episode_id = int(match('episode-([0-9]+)', cells[1].a['href']))
            # we could just return the id of the queried episode, but as we
            # already downloaded the whole page we might as well fill in the
            # information for all the episodes of the season
            self.cache_for(self.get_episode_id,
                           args = (series_id, season, episode_number),
                           result = episode_id)

        # raises KeyError if not found
        return self.cached_value(self.get_episode_id, args = (series_id, season, number))

    # Do not cache this method in order to always check for the most recent
    # subtitles
    def get_sub_ids(self, episode_id):
        subids = []
        r = self.session.get('%s/episode-%d.html' % (self.server_url, episode_id))
        epsoup = BeautifulSoup(r.content, 'lxml')
        for subdiv in epsoup.find_all('a'):
            if 'href' not in subdiv.attrs or not subdiv['href'].startswith('/subtitle'):
                continue

            subid = int(match('([0-9]+)', subdiv['href']))
            lang = subdiv.div['title'].split(' ')[1]
            result = { 'subid': subid, 'language': lang }
            for p in subdiv.find_all('p'):
                if 'alt' in p.attrs and p['alt'] == 'rip':
                    result['rip'] = p.text.strip()
                if 'alt' in p.attrs and p['alt'] == 'release':
                    result['release'] = p.text.strip()

            subids.append(result)

        return subids


    def list(self, video, languages):
        if not self.check_validity(video, languages):
            return []
        results = self.query(video.path or video.release, languages, get_keywords(video.guess), video.series, video.season, video.episode)
        return results


    def download(self, subtitle):
        """Download a subtitle"""
        self.download_zip_file(subtitle.link, subtitle.path)


    def query(self, filepath, languages, keywords, series, season, episode):
        logger.debug(u'Getting subtitles for %s season %d episode %d with languages %r' % (series, season, episode, languages))
        self.init_cache()
        sid = self.get_likely_series_id(series.lower())
        try:
            ep_id = self.get_episode_id(sid, season, episode)
        except KeyError:
            logger.debug('Could not find episode id for %s season %d epnumber %d' % (series, season, episode))
            return []
        subids = self.get_sub_ids(ep_id)

        # filter the subtitles with our queried languages
        languages = set(guessit.Language(l) for l in languages)
        subtitles = []
        for subid in subids:
            language = self.guess_language(subid['language'])
            if language not in languages:
                continue

            path = get_subtitle_path(filepath, language.lng2(), self.config.multi)
            subtitle = ResultSubtitle(path, language.lng2(), self.__class__.__name__.lower(),
                                      '%s/download-%d.html' % (self.server_url, subid['subid']),
                                      keywords=[ subid['rip'], subid['release'] ])
            subtitles.append(subtitle)

        return subtitles

Service = TvSubtitles
