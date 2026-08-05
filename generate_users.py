import os
import django
import random

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from api.models import User, UserProfile, UserPhoto, Match

def run():
    target_email = 'jamilhossain3741@gmail.com'
    print(f"Clearing matches for {target_email}...")
    try:
        jamil_user = User.objects.get(email=target_email)
        jamil_profile = UserProfile.objects.get(user=jamil_user)
        deleted, _ = Match.objects.filter(user1=jamil_profile).delete()
        print(f"Cleared {deleted} match records.")
    except User.DoesNotExist:
        print(f"User {target_email} not found!")
    
    print("Generating 100 new realistic users...")
    
    cities = ['Portland', 'London', 'Paris', 'Sydney', 'Melbourne', 'Jakarta', 'New York', 'Tokyo', 'Berlin', 'Toronto']
    countries = ['USA', 'UK', 'France', 'Australia', 'Australia', 'Indonesia', 'USA', 'Japan', 'Germany', 'Canada']
    
    first_names_f = ["Emma", "Olivia", "Ava", "Isabella", "Sophia", "Mia", "Amelia", "Harper", "Evelyn", "Abigail", "Emily", "Elizabeth", "Mila", "Ella", "Avery", "Sofia", "Camila", "Aria", "Scarlett", "Victoria"]
    first_names_m = ["Liam", "Noah", "William", "James", "Oliver", "Benjamin", "Elijah", "Lucas", "Mason", "Logan", "Alexander", "Ethan", "Jacob", "Michael", "Daniel", "Henry", "Jackson", "Sebastian", "Aiden", "Matthew"]
    last_names = ["Smith", "Johnson", "Williams", "Jones", "Brown", "Davis", "Miller", "Wilson", "Moore", "Taylor", "Anderson", "Thomas", "Jackson", "White", "Harris", "Martin", "Thompson", "Garcia", "Martinez", "Robinson"]
    
    looking_for = ['male', 'female', 'everyone']
    neurotypes = ['Autistic', 'ADHD', 'Dyslexic', 'Tourettes', 'OCD', 'Neurotypical']
    
    for i in range(1, 101):
        is_female = random.choice([True, False])
        gender = 'female' if is_female else 'male'
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
            subscription_tier='free',
            neurotype_labels=[random.choice(neurotypes)],
            is_neurodivergent=True
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
        photo.image = avatar_url
        photo.save()
        
        if i % 10 == 0:
            print(f"Generated {i} users...")
            
    print("Done generating users!")

if __name__ == '__main__':
    run()
