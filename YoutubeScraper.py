from bs4 import BeautifulSoup
import re
import requests
import csv
import time
import json


# version 1.1 added handling of youtube.com/channel/
#  to already handling of youtube.com/user based channels


def tag(t, c):
    return '<{0}>{1}</{0}>'.format(t, c)  # return html tag with content


def link(text, url):  # return a tag with content and link
    return '<a href="{1}">{0}</a>'.format(text, url)


class YoutubeScraper:
    """
        scrape youtube channel to build table of contents html file and
        csv of video information for excel file
        note this code has a slow down delay to meet youtube terms of use
    """
    youtube_base = 'https://www.youtube.com/'
    parent_folder = ''  # users or channel or empty
    channel_name = ''
    # NOTE: url gets to youtube are throttled to 3 seconds between requests
    # this is an ad hoc attempt to look like a human to youtube
    # so youtube does not start limiting access
    wait_between_requests = 3

    def __init__(self, channel_name):
        """set youtube channel name here"""
        self.channel_name = channel_name
        self.process()

    @property
    def channel_section_links(self):
        """return:
           list of
           { 'title': <section title>,
             'link': <url to section play lists>
           }
           """
        soup = self.get_soup('{0}/user/{1}/playlists'.format(self.youtube_base, self.channel_name))
        if soup is None or 'This channel does not exist.' in soup.text:
            url = '{0}/channel/{1}/playlists'.format(self.youtube_base, self.channel_name)
            soup = self.get_soup(url)
            if soup is None or 'This channel does not exist.' in soup.text:
                raise ValueError(
                    'The channel does not exists: ' + self.channel_name)
            self.parent_folder = 'channel/'

        play_list_atags = \
            soup.find_all('a',
                          {'href': re.compile('{0}/playlists'.format(self.channel_name))})
        # filter out non user play lists next
        elements = [{'title': x.text.strip(),
                     'link': self.fix_url(x['href'])} for x in play_list_atags
                    if x.span and
                    ('shelf_id=0' not in x['href'])]

        # no sections, make up no sections section with default link
        if len(elements) == 0:
            url = '{}{}{}/playlists'.format(self.youtube_base, self.parent_folder, self.channel_name)
            elements = [{'title': 'no sections', 'link': url}]
        return elements

    @property
    def process_channel(self):
        sections = self.channel_section_links
        print(sections)
        for section in sections:
            section['playlists'] = self.get_playlists(section)
            for playlist in section['playlists']:
                self.add_videos(playlist)
        return sections

    def get_soup(self, url):
        """open url and return BeautifulSoup object,
           or None if site does not exist"""

        result = requests.get(url)
        if result.status_code != 200:
            return None
        time.sleep(self.wait_between_requests)  # slow down to human speed
        return BeautifulSoup(result.text, 'html.parser')

    def fix_url(self, url):  # correct relative urls back to absolute urls
        if url[0] == '/':
            return self.youtube_base + url
        else:
            return url

    def get_playlists(self, section):
        """returns list of list of
        { 'title': <playlist tile>, <link to all playlist videos> }"""
        self.parent_folder
        print("  getting playlists for section: {}".format(section['title']))

        soup = self.get_soup(section['link'])
        if soup is None:  # no playlist, create dummy with default link
            url = '{}/{}{}/videos'.format(self.youtube_base, self.parent_folder, self.channel_name)
            return [
                {'title': 'No Playlists', 'link': url}]
        atags = soup('a', class_='yt-uix-tile-link')

        playlists = []
        for a in atags:  # find title and link
            title = a.text
            if title != 'Liked videos':  # skip these
                url = self.fix_url(a['href'])
                playlists.append({'title': title, 'link': url})

        if not playlists:  # no playlists
            url = '{}/{}{}/videos'.format(self.youtube_base, self.parent_folder, self.channel_name)
            return [{'title': 'No Playlists', 'link': url}]

        return playlists

    def parse_video(self, vurl):
        # return dict of
        # title, link, views, publication_date,
        # description, short_link, likes, dislikes

        d = {'link': vurl, 'views': None, 'short_link': vurl,
             'likes': None, 'dislikes': None}

        # now get video page and pull information from it
        vsoup = self.get_soup(vurl)

        o = vsoup.find('title')
        vtitle = o.text.strip()
        xending = ' - YouTube'
        d['title'] = vtitle[:-len(xending)] \
            if vtitle.endswith(xending) else vtitle
        print("      processing video '{}'".format(d['title']))

        # o is used in the code following to
        # catch missing data targets for scrapping
        o = vsoup.find('div', class_='watch-view-count')
        if o:
            views = o.text
            d['views'] = ''.join(c for c in views if c in '0123456789')

        o = vsoup.find('strong', class_='watch-time-text')
        d['publication_date'] = \
            o.text[len('Published on ') - 1:] if o else ''

        o = vsoup.find('div', id='watch-description-text')
        d['description'] = o.text if o else ''

        o = vsoup.find('meta', itemprop='videoId')
        if o:
            d['short_link'] = 'https://youtu.be/{0}'.format(o['content'])

        o = vsoup.find('button',
                       class_='like-button-renderer-like-button')
        if o:
            o = o.find('span', class_='yt-uix-button-content')
            d['likes'] = o.text if o else ''

        o = vsoup.find('button',
                       class_='like-button-renderer-dislike-button')
        if o:
            o = o.find('span', class_='yt-uix-button-content')
            d['dislikes'] = o.text if o else ''

        return d

    def add_videos(self, playlist):
        """find videos in playlist[link]
        and add their info as playlist[videos] as list"""
        surl = playlist['link']
        soup = self.get_soup(surl)
        print('    getting videos for playlist: {}'.format(playlist['title']))

        videos = []

        # items are list of video a links from list
        items = soup('a', class_='yt-uix-tile-link')

        # note first part of look get info from playlist page item,
        # and the the last part opens the video and gets more details
        if len(items) > 0:
            for i in items:
                d = dict()
                vurl = self.fix_url(i['href'])
                t = i.find_next('span', {'aria-label': True})
                d['time'] = t.text if t else 'NA'

                d.update(self.parse_video(vurl))
                videos.append(d)

        else:  # must be only one video
            d = {'time': 'NA'}
            d.update(self.parse_video(surl))
            videos.append(d)

        # add new key to this playlist of list of video information
        playlist['videos'] = videos
        print()

    def csv_out(self, sections):
        """ create and output channel_name.csv
        file for import into a spreadsheet or DB"""
        headers = ('channel,section,playlist,video,'
                   'link,time,views,publication date,'
                   'likes,dislikes,description').split(',')

        with open('{0}.csv'.format(self.channel_name), 'w', newline='', encoding='utf-8') as csv_file:
            csvf = csv.writer(csv_file, delimiter=',')
            csvf.writerow(headers)
            for section in sections:
                for playlist in section['playlists']:
                    for video in playlist['videos']:
                        v = video
                        line = [self.channel_name,
                                section['title'],
                                playlist['title'],
                                v['title']]
                        line.extend([v['short_link'],
                                     v['time'], v['views'],
                                     v['publication_date'],
                                     v['likes'], v['dislikes'],
                                     v['description']])
                        csvf.writerow(line)

    def html_out(self, sections):
        title = 'YouTube Channel {0}'.format(self.channel_name)
        f = open('{0}.html'.format(self.channel_name), 'w', newline='', encoding='utf-8')
        template = ('<!doctype html>\n<html lang="en">\n<head>\n'
                    '<meta charset="utf-8">'
                    '<title>{}</title>\n</head>\n'
                    '<body>\n{}\n</body>\n</html>')

        parts = list()
        parts.append(tag('h1', title))

        for s in sections:
            parts.append(tag('h2', link(s['title'], s['link'])))
            for pl in s['playlists']:
                parts.append(tag('h3', link(pl['title'], pl['link'])))
                if len(pl) == 0:
                    parts.append('<p>Empty Playlist</p>')
                else:
                    parts.append('<ol>')
                    for v in pl['videos']:
                        t = '' if v['time'] == 'NA' else " ({})".format(v['time'])
                        parts.append(tag('li', link(v['title'],
                                                    v['short_link']) + t))
                    parts.append('</ol>')
        f.write(template.format(self.channel_name, '\n'.join(parts)))
        f.close()

    def process(self):
        print('finding sections for youtube.com {}'.format(self.channel_name))
        sections = self.process_channel

        # save sections structure to json file
        with open('{}.json'.format(self.channel_name), 'w', encoding='utf-8') as f:
            f.write(json.dumps(sections, sort_keys=True, indent=4))

        #self.html_out(sections.encode('utf8'))  # create web page of channel links

        # create a csv file of video info for import into spreadsheet
        #self.csv_out(sections.encode('utf8'))

        print("Program Complete,\n  '{0}.html' and"
              " '{0}.csv' have been"
              " written to current directory".format(self.channel_name))
