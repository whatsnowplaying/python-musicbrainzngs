#!/usr/bin/env python3

import pathlib

import requests
import time

BASEDIR = 'test/data'
BASEURL = 'https://musicbrainz.org/ws/2'

XMLDATALIST = {
    'artist': [
        '0e43fe9d-c472-4b62-be9e-55f971a023e1?inc=aliases',
        '2736bad5-6280-4c8f-92c8-27a5e63bbab2?inc=aliases',
        'b3785a55-2cf6-497d-b8e3-cfa21a36f997?inc=artist-rels',
    ],
    'collection': [
        '0b15c97c-8eb8-4b4f-81c3-0eb24266a2ac/releases',
        '20562e36-c7cc-44fb-96b4-486d51a1174b/events',
        '2326c2e8-be4b-4300-acc6-dbd0adf5645b/works',
        '29611d8b-b3ad-4ffb-acb5-27f77342a5b0/artists',
        '855b134e-9a3b-4717-8df8-8c4838d89924/places',
        'a91320b2-fd2f-4a93-9e4e-603d16d514b6/recordings',
    ],
    'discid': [
        'f7agNZK1HMQ2WUWq9bwDymw9aHA-',
        'xp5tz6rE4OHrBafj0bLfDRMGK48-',
    ],
    'event': [
        '770fb0b4-0ad8-4774-9275-099b66627355?inc=place-rels',
        'e921686d-ba86-4122-bc3b-777aec90d231?inc=tags+artist-rels',
    ],
    'instrument': [
        '01ba56a2-4306-493d-8088-c7e9b671c74e?inc=instrument-rels',
        '6505f98c-f698-4406-8bf4-8ca43d05c36f?inc=aliases',
        '6505f98c-f698-4406-8bf4-8ca43d05c36f?inc=tags',
        '9447c0af-5569-48f2-b4c5-241105d58c91',
        '10ee2ae4-d9b6-46af-9250-6d853af7051e?inc=annotation',
        'd00cec5f-f9bc-4235-a54f-6639a02d4e4c?inc=url-rels',
        'dabdeb41-560f-4d84-aa6a-cf22349326fe',
    ],
    'label': [
        '022fe361-596c-43a0-8e22-bad712bb9548?inc=aliases',
        'e72fabf2-74a3-4444-a9a5-316296cbfc8d?inc=aliases',
    ],
    'place': [
        '0c79cdbb-acd6-4e30-aaa3-a5c8d6b36a48?inc=aliases+tags',
        '?area=f1724242-d9e8-40bd-a1d6-2add4b0c24ec&inc=annotation',
    ],
    'recording': [
        '58169b2c-e31a-4a46-8741-71c672a089ac?inc=tags+genres',
        'f606f733-c1eb-43f3-93c1-71994ea611e3?inc=artist-rels',
    ],
    'release-group': [
        'f52bc6a1-c848-49e6-85de-f8f53459a624',
    ],
    'release': [
        '212895ca-ee36-439a-a824-d2620cd10461?inc=recordings',
        '833d4c3a-2635-4b7a-83c4-4e560588f23a?inc=recordings+artist-credits',
        '8eb2b179-643d-3507-b64c-29fcc6745156?inc=recordings',
        '9ce41d09-40e4-4d33-af0c-7fed1e558dba?inc=recordings',
        'a81f3c15-2f36-47c7-9b0f-f684a8b0530f?inc=recordings',
        'fbe4490e-e366-4da2-a37a-82162d2f41a9?inc=recordings+artist-credits',
        'fe29e7f0-eb46-44ba-9348-694166f47885?inc=recordings',
    ],
    'work': [
        '3d7c7cd2-da79-37f4-98b8-ccfb1a4ac6c4?inc=aliases',
        '72c9aad2-3c95-4e3e-8a01-3974f8fef8eb?inc=series-rels',
        '80737426-8ef3-3a9c-a3a6-9507afb93e93?inc=aliases',
        '8e134b32-99b8-4e96-ae5c-426f3be85f4c/attributes',
    ]
}

with requests.Session() as session:
    for topic, identifiers in XMLDATALIST.items():
        for obj in identifiers:
            url = f'{BASEURL}/{topic}/{obj}'
            filename = obj.replace('?', '_').replace('+', '_').replace('/', '_')
            filedir = pathlib.Path(BASEDIR).joinpath(topic)
            filedir.mkdir(exist_ok=True, parents=True)
            filepath = filedir.joinpath(filename).with_suffix('.xml')
            print(f'Fetching {url}')
            response = session.get(url)
            print(f'Writing {str(filepath)}')
            with open(filepath, 'wb') as fhout:
                fhout.write(response.content)
            time.sleep(2)
