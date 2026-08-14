import os
import django
from django.utils import timezone

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from api.models import (
    User, UserProfile, ChatRoom, ChatRoomMessage, 
    SupportTicket, SupportTicketReply, Report, DirectMessage
)

def seed():
    print("Seeding Atypical Connection database...")

    # Clear existing data
    User.objects.all().delete()
    ChatRoom.objects.all().delete()
    SupportTicket.objects.all().delete()
    Report.objects.all().delete()

    # 1. Create Admins and Staff
    superadmin_user = User.objects.create_superuser(
        email='admin@hoodlink.au',
        username='admin',
        password='AdminPassword123!',
        role='superadmin',
        is_verified=True
    )
    # Initialize profile for superadmin
    UserProfile.objects.create(
        user=superadmin_user,
        username='Admin User',
        is_verified=True,
        profile_completion_pct=100
    )

    # Primary admin account (easy access)
    primary_admin = User.objects.create_superuser(
        email='admin@gmail.com',
        username='primary_admin',
        password='admin',
        role='superadmin',
        is_verified=True
    )
    UserProfile.objects.create(
        user=primary_admin,
        username='Primary Admin',
        is_verified=True,
        profile_completion_pct=100
    )


    support_user = User.objects.create_user(
        email='support@hoodlink.au',
        username='support_agent',
        password='SupportPassword123!',
        role='support',
        is_verified=True
    )
    UserProfile.objects.create(
        user=support_user,
        username='Support Agent',
        is_verified=True
    )

    mod_user = User.objects.create_user(
        email='moderator@hoodlink.au',
        username='moderator_agent',
        password='ModeratorPassword123!',
        role='moderator',
        is_verified=True
    )
    UserProfile.objects.create(
        user=mod_user,
        username='Moderator Agent',
        is_verified=True
    )

    print("Created staff accounts.")

    # 2. Create Members
    users_data = [
        {
            'email': 'alex@example.com', 'username': 'Alex Chen', 'password': 'UserPassword123!',
            'age': 28, 'height_cm': 175, 'weight_kg': 70, 'gender': 'non_binary',
            'looking_for': 'serious', 'marital_status': 'single', 'education_level': 'Bachelors Degree',
            'city': 'Portland', 'country': 'USA', 'subscription_tier': 'plus',
            'neurotype_labels': ['Autistic', 'ADHD'], 'is_neurodivergent': True, 'open_to_meet_neurodivergent': True,
            'qualities': ['Authenticity', 'Loyalty', 'Reliability'],
            'interests': ['Coding', 'Design', 'Sci-Fi'],
            'recharge_methods': ['Silence', 'Cocoon Spaces'],
            'exhaust_triggers': ['Loud or unpredictable noises', 'Bright lights'],
            'emotional_needs': ['Predictability', 'Clear communication'],
            'soothe_methods': ['Silence or soft sounds', 'Dim light']
        },
        {
            'email': 'sam@example.com', 'username': 'Sam', 'password': 'UserPassword123!',
            'age': 28, 'height_cm': 180, 'weight_kg': 75, 'gender': 'man',
            'looking_for': 'friendship', 'marital_status': 'single', 'education_level': 'Bachelors Degree',
            'city': 'London', 'country': 'UK', 'subscription_tier': 'light',
            'neurotype_labels': ['Autistic'], 'is_neurodivergent': True, 'open_to_meet_neurodivergent': True,
            'qualities': ['Introvert', 'Honest', 'Handsome'],
            'interests': ['Gaming', 'Space', 'Coffee'],
            'recharge_methods': ['Cocoon Spaces', 'Silence'],
            'exhaust_triggers': ['Loud or unpredictable noises'],
            'emotional_needs': ['Absence of judgement', 'Clear communication'],
            'soothe_methods': ['Chosen solitude', 'Sensory objects']
        },
        {
            'email': 'nico@example.com', 'username': 'Nico Alexis', 'password': 'UserPassword123!',
            'age': 30, 'height_cm': 182, 'weight_kg': 80, 'gender': 'man',
            'looking_for': 'undecided', 'marital_status': 'single', 'education_level': 'Masters',
            'city': 'Paris', 'country': 'France', 'subscription_tier': 'freemium',
            'neurotype_labels': ['ADHD'], 'is_neurodivergent': True, 'open_to_meet_neurodivergent': True,
            'qualities': ['Creativity', 'Intense Curiosity', 'Originality'],
            'interests': ['Coding', 'Lore', 'Yoga'],
            'recharge_methods': ['Reduced Stimulation'],
            'exhaust_triggers': ['Bright lights'],
            'emotional_needs': ['Deep talk', 'Predictability'],
            'soothe_methods': ['Hyperfocus on an interest']
        },
        {
            'email': 'elena@example.com', 'username': 'Elena Rodriguez', 'password': 'UserPassword123!',
            'age': 26, 'height_cm': 168, 'weight_kg': 58, 'gender': 'woman',
            'looking_for': 'serious', 'marital_status': 'single', 'education_level': 'Bachelors Degree',
            'city': 'North Bondi', 'country': 'Australia', 'subscription_tier': 'freemium',
            'neurotype_labels': ['Dyslexic'], 'is_neurodivergent': True, 'open_to_meet_neurodivergent': False,
            'qualities': ['Emotional Sensitivity', 'Kindness', 'Deep Empathy'],
            'interests': ['Design', 'Yoga', 'Botany'],
            'recharge_methods': ['Cocoon Spaces'],
            'exhaust_triggers': ['Absorbs other people’s moods'],
            'emotional_needs': ['Absence of judgement'],
            'soothe_methods': ['Dim light', 'Massage']
        },
        {
            'email': 'marcus@example.com', 'username': 'Marcus Chen', 'password': 'UserPassword123!',
            'age': 32, 'height_cm': 178, 'weight_kg': 72, 'gender': 'man',
            'looking_for': 'casual', 'marital_status': 'separated', 'education_level': 'PhD',
            'city': 'Banani East', 'country': 'Bangladesh', 'subscription_tier': 'freemium',
            'neurotype_labels': ['ADHD', 'Questioning'], 'is_neurodivergent': True, 'open_to_meet_neurodivergent': True,
            'qualities': ['Strong Memory', 'Loyalty', 'Kindness'],
            'interests': ['Math', 'Sci-Fi', 'Engines'],
            'recharge_methods': ['Reduced Stimulation'],
            'exhaust_triggers': ['Bright lights'],
            'emotional_needs': ['Consistency in behavior'],
            'soothe_methods': ['Sensory objects']
        },
        {
            'email': 'sophie.m@email.com', 'username': 'Sophie Martin', 'password': 'UserPassword123!',
            'age': 28, 'height_cm': 165, 'weight_kg': 55, 'gender': 'woman',
            'looking_for': 'serious', 'marital_status': 'single', 'education_level': 'Bachelors Degree',
            'city': 'Paris', 'country': 'France', 'subscription_tier': 'plus',
            'neurotype_labels': ['AuDHD'], 'is_neurodivergent': True, 'open_to_meet_neurodivergent': True,
            'qualities': ['Authenticity', 'Attention to Detail', 'Strong Memory'],
            'interests': ['Photography', 'Design', 'Pets'],
            'recharge_methods': ['Cocoon Spaces', 'Silence'],
            'exhaust_triggers': ['Absorbs other people’s moods', 'Loud or unpredictable noises'],
            'emotional_needs': ['Clear communication', 'Absence of judgement'],
            'soothe_methods': ['Silence or soft sounds', 'Chosen solitude']
        },
        {
            'email': 'mike@example.com', 'username': 'Mike Johnson', 'password': 'UserPassword123!',
            'age': 29, 'height_cm': 176, 'weight_kg': 78, 'gender': 'man',
            'looking_for': 'casual', 'marital_status': 'single', 'education_level': 'Bachelors Degree',
            'city': 'Sydney', 'country': 'Australia', 'subscription_tier': 'freemium',
            'neurotype_labels': ['Questioning'], 'is_neurodivergent': False, 'open_to_meet_neurodivergent': True,
            'qualities': ['Honesty', 'Kindness', 'Originality'],
            'interests': ['D&D', 'Biology'],
            'recharge_methods': ['Silence'],
            'exhaust_triggers': ['Bright lights'],
            'emotional_needs': ['Absence of judgement'],
            'soothe_methods': ['Sensory objects']
        },
        {
            'email': 'lisa@example.com', 'username': 'Lisa Chen', 'password': 'UserPassword123!',
            'age': 24, 'height_cm': 162, 'weight_kg': 50, 'gender': 'woman',
            'looking_for': 'friendship', 'marital_status': 'single', 'education_level': 'Bachelors Degree',
            'city': 'Melbourne', 'country': 'Australia', 'subscription_tier': 'freemium',
            'neurotype_labels': ['Dyslexic'], 'is_neurodivergent': True, 'open_to_meet_neurodivergent': True,
            'qualities': ['Loyalty', 'Reliability', 'Aesthetic Sense'],
            'interests': ['Design', 'Colors'],
            'recharge_methods': ['Cocoon Spaces'],
            'exhaust_triggers': ['Bright lights'],
            'emotional_needs': ['Consistency in behavior'],
            'soothe_methods': ['Dim light']
        },
        {
            'email': 'bima@example.com', 'username': 'Bima Algifari', 'password': 'UserPassword123!',
            'age': 27, 'height_cm': 174, 'weight_kg': 68, 'gender': 'man',
            'looking_for': 'friendship', 'marital_status': 'single', 'education_level': 'Masters',
            'city': 'Jakarta', 'country': 'Indonesia', 'subscription_tier': 'freemium',
            'neurotype_labels': ['Autistic'], 'is_neurodivergent': True, 'open_to_meet_neurodivergent': True,
            'qualities': ['Authenticity', 'Loyalty', 'Honesty'],
            'interests': ['Design', 'Patterns'],
            'recharge_methods': ['Silence'],
            'exhaust_triggers': ['Loud or unpredictable noises'],
            'emotional_needs': ['Clear communication'],
            'soothe_methods': ['Chosen solitude']
        }
    ]

    profiles = {}
    for u in users_data:
        user = User.objects.create_user(
            email=u['email'],
            username=u['username'].lower().replace(' ', '_'),
            password=u['password'],
            role='member',
            is_verified=True
        )
        # Coordinates mapping based on City/Country for seeded test users
        city_coords = {
            'portland': (45.5152, -122.6784),
            'london': (51.5074, -0.1278),
            'paris': (48.8566, 2.3522),
            'north bondi': (-33.8963, 151.2783),
            'sydney': (-33.8688, 151.2093),
            'melbourne': (-37.8136, 144.9631),
            'jakarta': (-6.2088, 106.8456),
            'banani east': (23.7937, 90.4066)
        }
        city_key = u['city'].lower().strip()
        lat, lon = city_coords.get(city_key, (None, None))

        profile = UserProfile.objects.create(
            user=user,
            username=u['username'],
            latitude=lat,
            longitude=lon,
            age=u['age'],
            height_cm=u['height_cm'],
            weight_kg=u['weight_kg'],
            gender=u['gender'],
            looking_for=u['looking_for'],
            marital_status=u['marital_status'],
            education_level=u['education_level'],
            city=u['city'],
            country=u['country'],
            subscription_tier=u['subscription_tier'],
            neurotype_labels=u['neurotype_labels'],
            is_neurodivergent=u['is_neurodivergent'],
            open_to_meet_neurodivergent=u['open_to_meet_neurodivergent'],
            qualities=u['qualities'],
            interests=u['interests'],
            recharge_methods=u['recharge_methods'],
            exhaust_triggers=u['exhaust_triggers'],
            emotional_needs=u['emotional_needs'],
            soothe_methods=u['soothe_methods'],
            smoking=u.get('smoking', False),
            alcohol=u.get('alcohol', False),
            pets=u.get('pets', False),
            sport=u.get('sport', 'No Sport'),
            eating_habits=u.get('eating_habits', 'Balanced'),
            has_children=u.get('has_children', False),
            wants_children=u.get('wants_children', False),
            profile_completion_pct=90,
            is_verified=True
        )
        profiles[u['username']] = profile

    print(f"Created {len(profiles)} member profiles.")

    # Upload placeholder avatars to Cloudinary for each profile
    print("Uploading placeholder profile photos to Cloudinary...")
    import cloudinary
    import cloudinary.uploader
    from api.models import UserPhoto
    from django.core.files.base import ContentFile
    import urllib.request

    cloud_name = os.environ.get('CLOUDINARY_CLOUD_NAME')
    api_key = os.environ.get('CLOUDINARY_API_KEY')
    api_secret = os.environ.get('CLOUDINARY_API_SECRET')

    if cloud_name and api_key and api_secret:
        cloudinary.config(
            cloud_name=cloud_name,
            api_key=api_key,
            api_secret=api_secret,
        )
    else:
        print("⚠️ Cloudinary credentials not found. Skipping photo uploads.")

    # Map username -> gender for avatar style
    gender_map = {
        'Alex Chen': 'male', 'Sam': 'male', 'Nico Alexis': 'male',
        'Elena Rodriguez': 'female', 'Marcus Chen': 'male',
        'Sophie Martin': 'female', 'Mike Johnson': 'male',
        'Lisa Chen': 'female', 'Bima Algifari': 'male',
    }

    for username, profile in profiles.items():
        # Skip if already has a photo or if Cloudinary is not configured
        if not cloud_name or UserPhoto.objects.filter(profile=profile).exists():
            continue
        try:
            # Use DiceBear Notionists-Neutral avatar as deterministic placeholder
            seed_str = username.lower().replace(' ', '-')
            avatar_url = f"https://api.dicebear.com/8.x/notionists-neutral/png?seed={seed_str}&size=400"

            result = cloudinary.uploader.upload(
                avatar_url,
                folder='profile_photos',
                public_id=f"seed_{seed_str}",
                overwrite=True,
                resource_type='image',
            )
            cloudinary_url = result['secure_url']

            # Store only the Cloudinary public_id path (django-cloudinary-storage convention)
            photo = UserPhoto(profile=profile, is_main=True, is_verified=True)
            photo.image = result['public_id']
            photo.save()
            print(f"  ✅ {username}: {cloudinary_url}")
        except Exception as e:
            print(f"  ⚠️  {username}: upload failed — {e}")


    # 3. Create Community Rooms
    rooms = [
        {'name': 'ADHD Hub', 'description': 'A high-energy, low-filter space to connect with other ADHDers.'},
        {'name': 'Sanctuary', 'description': 'A low-stimulation, quiet environment for calming conversations.'},
        {'name': 'HPI Thinkers', 'description': 'For deep-dive topics, hyperfocus discussions, and puzzle-solving.'},
        {'name': 'HSP Calm', 'description': 'A gentle discussion room for highly sensitive personalities.'}
    ]

    room_objs = {}
    for r in rooms:
        room = ChatRoom.objects.create(
            name=r['name'],
            description=r['description'],
            member_count=3
        )
        room_objs[r['name']] = room
        
    print("Created community chat rooms.")

    # 4. Create Support Ticket
    ticket = SupportTicket.objects.create(
        user=profiles['Sophie Martin'],
        email='sophie.m@email.com',
        subject='Cannot access premium features after payment',
        description='Hi, I just paid for Premium Plus but my account still shows as free. The payment went through on my bank statement. Please help!',
        priority='high',
        status='received'
    )
    print("Created support tickets.")

    # 5. Create Reports
    Report.objects.create(
        reporter=profiles['Alex Chen'],
        reported_user=profiles['Mike Johnson'],
        reason='inappropriate_behavior',
        description='Sent highly inappropriate messages demanding personal information during first interaction.',
        status='pending'
    )
    Report.objects.create(
        reporter=profiles['Sam'],
        reported_user=profiles['Lisa Chen'],
        reason='fake_profile',
        description='Profile uses photos of a famous influencer. Suspicious account behavior.',
        status='pending'
    )
    
    print("Created moderation reports.")

    # 6. Create room chat messages
    adhd_hub = room_objs['ADHD Hub']
    ChatRoomMessage.objects.create(
        room=adhd_hub,
        sender=profiles['Samantha' if 'Samantha' in profiles else 'Sam'],
        content="Hi @Nico Alexis I'm very excited to start working on this project. Can we begin by discussing the main goals and objectives of the design?",
        timestamp=timezone.now()
    )
    ChatRoomMessage.objects.create(
        room=adhd_hub,
        sender=profiles['Nico Alexis'],
        content="Of course, thank you for joining :)",
        timestamp=timezone.now()
    )
    ChatRoomMessage.objects.create(
        room=adhd_hub,
        sender=profiles['Samantha' if 'Samantha' in profiles else 'Sam'],
        content="That sounds great. Do we have any data on how users currently interact with our site?",
        timestamp=timezone.now()
    )
    ChatRoomMessage.objects.create(
        room=adhd_hub,
        sender=profiles['Bima Algifari'],
        content="Thank you. Based on this data, we can start creating user personas",
        timestamp=timezone.now()
    )

    print("Created chat message history.")

    # 7. Create direct messages (1-on-1 chats)
    alex_p = profiles['Alex Chen']
    sam_p = profiles['Sam']
    
    DirectMessage.objects.create(
        sender=alex_p,
        receiver=sam_p,
        content="Hi Sam! I saw you value parallel play and quiet environments. I'm exactly the same way.",
        timestamp=timezone.now()
    )
    DirectMessage.objects.create(
        sender=sam_p,
        receiver=alex_p,
        content="Hey Alex! That's awesome to hear. I usually recharge by setting up a cocoon blanket corner.",
        timestamp=timezone.now()
    )

    print("Created direct messages.")
    print("Database seeding completed successfully.")

if __name__ == '__main__':
    seed()
