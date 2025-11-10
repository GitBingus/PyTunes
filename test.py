import requests as rq
from dotenv import load_dotenv as lenv # type: ignore
import os
import json

lenv('.env')

API_KEY = os.getenv('API_KEY')
API_SEC = os.getenv('API_SEC')

api_token = rq.request('get', f'https://ws.audioscrobbler.com/2.0/?method=auth.gettoken&api_key={API_KEY}&format=json').json()['token']

request = rq.request('get', f'http://ws.audioscrobbler.com/2.0/?method=artist.getinfo&artist=Urban Hype&api_key={API_KEY}&format=json').json()['artist']

for image in request['image']:
    for link, size in image.items():
        if size == 'large':
            print(image['#text'])