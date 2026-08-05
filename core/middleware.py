from channels.middleware import BaseMiddleware
from channels.db import database_sync_to_async
from django.contrib.auth.models import AnonymousUser
import jwt
from django.conf import settings
from api.models import User

@database_sync_to_async
def get_user(token_key):
    try:
        # Decode SimpleJWT access token
        payload = jwt.decode(token_key, settings.SECRET_KEY, algorithms=['HS256'])
        user = User.objects.get(id=payload['user_id'])
        return user
    except Exception as e:
        return AnonymousUser()

class JWTAuthMiddleware(BaseMiddleware):
    async def __call__(self, scope, receive, send):
        query_string = scope.get('query_string', b'').decode()
        query_params = dict(qp.split('=') for qp in query_string.split('&') if '=' in qp)
        token = query_params.get('token')

        if not token:
            headers = {k.decode(): v.decode() for k, v in scope.get('headers', [])}
            auth = headers.get('authorization', '')
            if auth.lower().startswith('bearer '):
                token = auth.split(' ', 1)[1].strip()

        if token:
            scope['user'] = await get_user(token)
        else:
            scope['user'] = AnonymousUser()

        return await super().__call__(scope, receive, send)

def JWTAuthMiddlewareStack(inner):
    return JWTAuthMiddleware(inner)
