import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from api.models import User
from django.test import RequestFactory
from api.views import PerfectMatchView
from rest_framework.test import force_authenticate

user = User.objects.get(email='jamilhossain3741@gmail.com')
factory = RequestFactory()
request = factory.get('/api/matching/perfect-match/?page_size=10')
force_authenticate(request, user=user)

view = PerfectMatchView.as_view()
response = view(request)
print("Status:", response.status_code)
if response.status_code == 200:
    print("Data count:", len(response.data.get('results', [])))
else:
    print("Error:", response.data)
