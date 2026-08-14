import os
import django
import random
import requests
from django.core.files.base import ContentFile

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from api.models import User, UserProfile, UserPhoto, Match

def run():
    target_email = 'jamilhossain3741@gmail.com'
    print(f"Clearing old demo data (excluding {target_email} and superusers)...")
    
    users_to_delete = User.objects.exclude(email=target_email).exclude(is_superuser=True)
    deleted_count, _ = users_to_delete.delete()
    print(f"Cleared {deleted_count} old users.")
    
    try:
        jamil_user = User.objects.get(email=target_email)
        jamil_profile = UserProfile.objects.get(user=jamil_user)
        deleted_matches, _ = Match.objects.filter(user1=jamil_profile).delete()
        print(f"Cleared {deleted_matches} match records for {target_email}.")
    except User.DoesNotExist:
        print(f"User {target_email} not found!")
    
    print("Generating 100 new realistic users...")
    
    cities = ['Portland', 'London', 'Paris', 'Sydney', 'Melbourne', 'Jakarta', 'New York', 'Tokyo', 'Berlin', 'Toronto']
    countries = ['USA', 'UK', 'France', 'Australia', 'Australia', 'Indonesia', 'USA', 'Japan', 'Germany', 'Canada']
    
    first_names_f = ["Emma", "Olivia", "Ava", "Isabella", "Sophia", "Mia", "Amelia", "Harper", "Evelyn", "Abigail", "Emily", "Elizabeth", "Mila", "Ella", "Avery", "Sofia", "Camila", "Aria", "Scarlett", "Victoria"]
    first_names_m = ["Liam", "Noah", "William", "James", "Oliver", "Benjamin", "Elijah", "Lucas", "Mason", "Logan", "Alexander", "Ethan", "Jacob", "Michael", "Daniel", "Henry", "Jackson", "Sebastian", "Aiden", "Matthew"]
    last_names = ["Smith", "Johnson", "Williams", "Jones", "Brown", "Davis", "Miller", "Wilson", "Moore", "Taylor", "Anderson", "Thomas", "Jackson", "White", "Harris", "Martin", "Thompson", "Garcia", "Martinez", "Robinson"]
    
    looking_for = ['friendship', 'serious', 'undecided', 'casual']
    marital_statuses = ['single', 'widowed', 'divorced', 'separated', 'married']
    education_levels = ['bachelor', 'master', 'phd', 'below']
    sports = ['No Sport', 'Moderate', 'Intense']
    eating_habits = ['Balanced', 'Fast Food', 'Vegetarian', 'Vegan', 'Other']
    
    neurotypes = ['Autistic', 'ADHD', 'Dyslexic', 'Tourettes', 'OCD', 'Neurotypical']
    interests_pool = ["Gaming", "Reading", "Music", "Art", "Sports", "Cooking", "Travel", "Photography", "Movies", "Dancing", "Tech"]
    recharge_pool = ["Silence or soft sounds", "Dim light", "Massage", "Sensory objects", "Chosen solitude", "Comforting routines", "Predictability", "Clear Communication", "Hyperfocus on an interest"]
    exhaust_pool = ["Unexpected changes", "Loud noises", "Bright lights", "Crowds", "Small talk", "Interrupting routines", "Sarcasm", "Unpleasant textures"]
    needs_pool = ["Predictability", "Consistency in behavior", "Absence of judgement", "Clear communication", "Deep talk", "Need to be alone sometimes"]
    
    for i in range(1, 101):
        is_female = random.choice([True, False])
        gender = 'woman' if is_female else 'man'
        fname = random.choice(first_names_f) if is_female else random.choice(first_names_m)
        lname = random.choice(last_names)
        
        username = f"{fname}{lname}_{random.randint(100, 999)}_{i}".lower()
        email = f"{username}@example.com"
        
        # Avoid unique constraint errors
        if User.objects.filter(email=email).exists():
            continue
            
        user = User.objects.create_user(
            email=email,
            username=username,
            password='password123',
            role='member',
            is_verified=True
        )
        
        city_idx = random.randint(0, len(cities)-1)
        
        profile = UserProfile.objects.create(
            user=user,
            username=f"{fname} {lname} {i}",
            age=random.randint(20, 38),
            gender=gender,
            looking_for=random.choice(looking_for),
            city=cities[city_idx],
            country=countries[city_idx],
            marital_status=random.choice(marital_statuses),
            education_level=random.choice(education_levels),
            smoking=random.choice([True, False]),
            alcohol=random.choice([True, False]),
            pets=random.choice([True, False]),
            sport=random.choice(sports),
            eating_habits=random.choice(eating_habits),
            interests=random.sample(interests_pool, 3),
            recharge_methods=random.sample(recharge_pool, 2),
            exhaust_triggers=random.sample(exhaust_pool, 2),
            emotional_needs=random.sample(needs_pool, 2),
            soothe_methods=random.sample(recharge_pool, 2),
            second_degree_humor=random.choice([True, False]),
            subscription_tier='free',
            neurotype_labels=[random.choice(neurotypes)],
            is_neurodivergent=True,
            is_verified=True
        )
        
        # Add realistic photo based on gender
        photo_id = random.randint(1, 99)
        gender_str = 'women' if is_female else 'men'
        avatar_url = f"https://randomuser.me/api/portraits/{gender_str}/{photo_id}.jpg"
        
        photo = UserPhoto(
            profile=profile,
            is_main=True,
            is_verified=True
        )
        
        # Download the image and save to Django (which uploads to R2)
        try:
            resp = requests.get(avatar_url, timeout=10)
            if resp.status_code == 200:
                # Save without committing to DB yet
                photo.image.save(f"demo_user_{i}.jpg", ContentFile(resp.content), save=False)
                photo.save()
            else:
                print(f"Failed to download image for user {i}")
        except Exception as e:
            print(f"Error downloading image for user {i}: {e}")
        
        if i % 10 == 0:
            print(f"Generated {i} users...")
            
    print("Done generating users!")

if __name__ == '__main__':
    run()
