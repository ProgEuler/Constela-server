import os
import json

async def app(scope, receive, send):
    env_creds = os.environ.get("FIREBASE_CREDENTIALS_JSON")
    print("ENV CREDS:", repr(env_creds))
    try:
        json.loads(env_creds)
        print("JSON LOADS SUCCESS")
    except Exception as e:
        print("JSON LOADS FAILED:", e)
    
    assert scope['type'] == 'http'
    await send({
        'type': 'http.response.start',
        'status': 200,
        'headers': [
            [b'content-type', b'text/plain'],
        ],
    })
    await send({
        'type': 'http.response.body',
        'body': b'Hello, world!',
    })
