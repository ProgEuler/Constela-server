from channels.middleware import BaseMiddleware
from channels.db import database_sync_to_async
from django.contrib.auth.models import AnonymousUser
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import AccessToken
from urllib.parse import parse_qs
from api.models import User

@database_sync_to_async
def get_user(token_key):
    try:
        token = AccessToken(token_key)
        return User.objects.get(id=token['user_id'], is_active=True)
    except (TokenError, KeyError, User.DoesNotExist):
        return AnonymousUser()

class JWTAuthMiddleware(BaseMiddleware):
    async def __call__(self, scope, receive, send):
        query_params = parse_qs(scope.get('query_string', b'').decode())
        token = query_params.get('token', [None])[0]

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
