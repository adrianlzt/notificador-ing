import requests
import json

def send(token, titulo, url=None, body=None):
    headers = {
            'Content-Type': 'application/json',
            'Access-Token': token
    }

    data = {
            "type": "link",
            "title": titulo,
            "url": url,
            "body": body
    }

    if token:
        r = requests.post('https://api.pushbullet.com/v2/pushes', headers=headers, data=json.dumps(data))
    else:
        return "Pushbullet no configurado, hace falta definir el token"

    return r.content
