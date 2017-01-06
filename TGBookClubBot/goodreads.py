import requests
import xmltodict
import json
import collections

class GoodReadsClient:
    """ Implement internal Goodreads client to keep network calls to a minimum and focus on speed. """

    base_url = "https://www.goodreads.com"

    def __init__(self, key, secret):
        self.key = key
        self.secret = secret

        self.base_url = "https://www.goodreads.com"

    def search_books(self, q, page=1, field='all'):
        resp = self.make_request(
            url='/search/index.xml',
            data={
                'q': q,
                'page': page,
                'field': field
            }
        )

        works = resp['search']['results']['work']
        # If there's only one work returned, put it in a list.
        if type(works) == collections.OrderedDict:
            works = [works]

        return works

    def get_book(self, goodreads_id):
        resp = self.make_request(
            url='/book/show.xml',
            data={
                'id': goodreads_id,
            }
        )
        return resp['book']

    def make_request(self, url, data, req_format='xml'):
        data.update({
            'key': self.key
        })
        resp = requests.get(self.base_url + url, params=data)
        if resp.status_code != 200:
            raise Exception(resp.reason)
        if req_format == 'xml':
            data_dict = xmltodict.parse(resp.content)
            return data_dict['GoodreadsResponse']
        elif req_format == 'json':
            return json.loads(resp.content)
        else:
            raise Exception("Invalid format")
