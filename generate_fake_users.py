import os
import django
import random

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from django.contrib.auth.models import User
from api.models import UserProfile, Photo

first_names = ["Alex", "Jordan", "Taylor", "Casey", "Morgan", "Riley", "Jamie", "Skyler", "Cameron", "Quinn", "Avery", "Blake", "Mia", "Leo", "Kai"]
last_names = ["Smith", "Johnson", "Williams", "Jones", "Brown", "Davis", "Miller", "Wilson", "Moore", "Taylor", "Anderson", "Thomas"]
genders = ["male", "female", "non-binary"]
neurotypes = ["ADHD", "Autism", "Dyslexia", "Neurotypical", "Dyspraxia"]
tags = ["Coffee", "Anime", "Gaming", "Hiking", "Reading", "Music", "Art", "Tech", "Cooking", "Sports", "Travel"]

for i in range(50):
    fname = random.choice(first_names)
    lname = random.choice(last_names)
    username = f"{fname.lower()}_{lname.lower()}_{random.randint(1000, 9999)}_{i}"
    email = f"{username}@example.com"
    
    user = User.objects.create_user(username=username, email=email, password="password123")
    
    profile = UserProfile.objects.create(
        user=user,
        username=fname,
        date_of_birth=f"{random.randint(1990, 2003)}-01-01",
        gender=random.choice(genders),
        city="Dhaka",
        country="Bangladesh",
        bio=f"Hello! I'm {fname}. I love exploring new ideas and meeting interesting people.",
        neurotype=random.choice(neurotypes),
        looking_for=random.choice(genders),
        height=random.randint(150, 190),
        tags=random.sample(tags, 3)
    )
    
    print(f"Created user {username}")

print("Done creating 50 users")
