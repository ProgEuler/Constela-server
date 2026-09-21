from django.db import models
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
import uuid

class User(AbstractUser):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ROLE_CHOICES = (
        ('member', 'Member'),
        ('support', 'Support'),
        ('moderator', 'Moderator'),
        ('admin', 'Admin'),
        ('superadmin', 'Super Admin'),
    )
    email = models.EmailField(unique=True)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='member')
    otp = models.CharField(max_length=6, blank=True, null=True)
    otp_created_at = models.DateTimeField(blank=True, null=True)
    is_verified = models.BooleanField(default=False)
    
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username']

    def __str__(self):
        return f"{self.email} ({self.role})"

class UserProfile(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    GENDER_CHOICES = (
        ('woman', 'Woman'),
        ('man', 'Man'),
        ('non_binary', 'Non-Binary'),
        ('other', 'Other'),
    )
    LOOKING_FOR_CHOICES = (
        ('friendship', 'Friendship'),
        ('serious', 'Serious Relationship'),
        ('undecided', "We'll See"),
        ('casual', 'Going Out'),
    )
    MARITAL_CHOICES = (
        ('single', 'Single'),
        ('widowed', 'Widowed'),
        ('divorced', 'Divorced'),
        ('separated', 'Separated'),
        ('married', 'Married'),
    )
    TIER_CHOICES = (
        ('freemium', 'Freemium'),
        ('light', 'Premium Light'),
        ('plus', 'Premium Plus'),
    )
    
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    username = models.CharField(max_length=150, unique=True)
    age = models.IntegerField(null=True, blank=True)
    height_cm = models.IntegerField(null=True, blank=True)
    weight_kg = models.IntegerField(null=True, blank=True)
    gender = models.CharField(max_length=20, choices=GENDER_CHOICES, null=True, blank=True)
    looking_for = models.CharField(max_length=20, choices=LOOKING_FOR_CHOICES, null=True, blank=True)
    marital_status = models.CharField(max_length=20, choices=MARITAL_CHOICES, null=True, blank=True)
    education_level = models.CharField(max_length=100, null=True, blank=True)
    spoken_languages = models.JSONField(default=list, blank=True)
    city = models.CharField(max_length=100, null=True, blank=True)
    country = models.CharField(max_length=100, null=True, blank=True)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    profile_completion_pct = models.IntegerField(default=0)
    is_verified = models.BooleanField(default=False)
    subscription_tier = models.CharField(max_length=20, choices=TIER_CHOICES, default='freemium')
    subscription_expires = models.DateTimeField(null=True, blank=True)
    has_match_analysis = models.BooleanField(default=False)
    has_advanced_filters = models.BooleanField(default=False)
    has_all_chat_rooms = models.BooleanField(default=False)
    
    # Detailed Subscription Info
    subscription_product_id = models.CharField(max_length=100, null=True, blank=True)
    subscription_store = models.CharField(max_length=50, null=True, blank=True)
    # Neurotype Identity
    neurotype_labels = models.JSONField(default=list, blank=True)  # Autistic, ADHD, etc.
    is_neurodivergent = models.BooleanField(default=False)
    open_to_meet_neurodivergent = models.BooleanField(default=False)
    
    # Predefined lists saved as JSON
    qualities = models.JSONField(default=list, blank=True)  # Exactly 3 items when complete
    interests = models.JSONField(default=list, blank=True)
    
    # Sensory & Recharge Profiles
    recharge_methods = models.JSONField(default=list, blank=True)
    exhaust_triggers = models.JSONField(default=list, blank=True)
    emotional_needs = models.JSONField(default=list, blank=True)
    second_degree_humor = models.BooleanField(default=False)
    soothe_methods = models.JSONField(default=list, blank=True)
    
    # Lifestyle Habits
    smoking = models.BooleanField(default=False)
    alcohol = models.BooleanField(default=False)
    pets = models.BooleanField(default=False)
    sport = models.CharField(max_length=20, default='No Sport')  # Intense, Moderate, No Sport
    eating_habits = models.CharField(max_length=50, default='Balanced')  # Balanced, Fast Food, Vegetarian, Vegan, Other
    
    # Children
    has_children = models.BooleanField(default=False)
    wants_children = models.BooleanField(default=False)
    
    # Flags & Preferences
    likes_push = models.BooleanField(default=True)
    messages_push = models.BooleanField(default=True)
    push_token = models.CharField(max_length=255, blank=True, null=True)
    is_dark_mode = models.BooleanField(default=False)
    preferred_language = models.CharField(max_length=10, default='en')
    is_deactivated = models.BooleanField(default=False)

    # Face Verification
    FACE_VERIFY_STATUS = (
        ('not_submitted', 'Not Submitted'),
        ('skipped', 'Skipped'),
        ('pending', 'Pending Review'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    )
    face_selfie = models.ImageField(upload_to='face_selfies/', null=True, blank=True)
    face_selfie_left = models.ImageField(upload_to='face_selfies/', null=True, blank=True)
    face_selfie_right = models.ImageField(upload_to='face_selfies/', null=True, blank=True)
    face_verification_status = models.CharField(
        max_length=20,
        choices=FACE_VERIFY_STATUS,
        default='not_submitted'
    )
    face_verified_at = models.DateTimeField(null=True, blank=True)
    must_verify_face = models.BooleanField(default=False)
    onboarding_part1_completed = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.username} ({self.user.email})"
        
    @property
    def display_name(self):
        if self.user.first_name:
            return self.user.first_name
        if '@' in self.username:
            return self.username.split('@')[0]
        return self.username

    @property
    def name(self):
        return self.display_name
        
    def clean(self):
        super().clean()


class UserPhoto(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    profile = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name='photos')
    image = models.ImageField(upload_to='profile_photos/')
    is_main = models.BooleanField(default=False)
    is_verified = models.BooleanField(default=False)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Photo {self.id} for {self.profile.username}"

class Match(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    STATUS_CHOICES = (
        ('liked', 'Liked'),
        ('superliked', 'Super Liked'),
        ('disliked', 'Disliked'),
        ('matched', 'Matched'),
    )
    user1 = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name='matches_sent')
    user2 = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name='matches_received')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user1', 'user2')
        indexes = [
            models.Index(fields=['user1', 'status', '-created_at'], name='match_u1_status_created_idx'),
            models.Index(fields=['user2', 'status', '-created_at'], name='match_u2_status_created_idx'),
        ]

    def __str__(self):
        return f"{self.user1.username} -> {self.user2.username} ({self.status})"

class Friendship(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('accepted', 'Accepted'),
        ('declined', 'Declined'),
    )
    sender = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name='friendship_sent')
    receiver = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name='friendship_received')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('sender', 'receiver')
        indexes = [
            models.Index(fields=['sender', 'status'], name='friend_sender_status_idx'),
            models.Index(fields=['receiver', 'status'], name='friend_receiver_status_idx'),
        ]

    def __str__(self):
        return f"Friendship: {self.sender.username} -> {self.receiver.username} ({self.status})"

class DirectMessage(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    sender = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name='dm_sent')
    receiver = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name='dm_received')
    content = models.TextField(blank=True, null=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)
    image_url = models.URLField(max_length=500, blank=True, null=True)
    reply_to = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='replies')
    reaction = models.CharField(max_length=20, blank=True, null=True)

    class Meta:
        indexes = [
            models.Index(fields=['sender', 'receiver', '-timestamp'], name='dm_sender_receiver_time_idx'),
            models.Index(fields=['receiver', 'sender', '-timestamp'], name='dm_receiver_sender_time_idx'),
        ]

    def __str__(self):
        return f"DM: {self.sender.username} -> {self.receiver.username} at {self.timestamp}"

class ChatRoom(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField()
    member_count = models.IntegerField(default=0)
    members = models.ManyToManyField(UserProfile, related_name='chat_rooms', blank=True)
    status = models.CharField(max_length=20, default='active')
    created_at = models.DateTimeField(auto_now_add=True, null=True, blank=True)

    def __str__(self):
        return self.name

class ChatRoomMessage(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    room = models.ForeignKey(ChatRoom, on_delete=models.CASCADE, related_name='messages')
    sender = models.ForeignKey(UserProfile, on_delete=models.CASCADE)
    content = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Room {self.room.name}: {self.sender.username} at {self.timestamp}"

class SupportTicket(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    PRIORITY_CHOICES = (
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
    )
    STATUS_CHOICES = (
        ('received', 'Received'),
        ('in_progress', 'In Progress'),
        ('resolved', 'Resolved'),
    )
    user = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name='tickets')
    email = models.EmailField()
    subject = models.CharField(max_length=255)
    description = models.TextField()
    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, default='medium')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='received')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Ticket #{self.id}: {self.subject} ({self.status})"

class SupportTicketReply(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ticket = models.ForeignKey(SupportTicket, on_delete=models.CASCADE, related_name='replies')
    sender = models.ForeignKey(User, on_delete=models.CASCADE)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Reply to Ticket #{self.ticket.id} by {self.sender.email}"

class Report(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    REASON_CHOICES = (
        ('fake_profile', 'Fake or suspicious profile'),
        ('offensive_language', 'Offensive language'),
        ('harassment', 'Harassment or bullying'),
        ('sexually_explicit_content', 'Sexually explicit content'),
        ('impersonation', 'Impersonation'),
        ('other', 'Other'),
    )
    STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('under_review', 'Under Review'),
        ('resolved', 'Resolved'),
    )
    ACTION_CHOICES = (
        ('ban', 'Banned'),
        ('suspend', 'Suspended'),
        ('dismiss', 'Dismissed'),
        ('warning', 'Warning'),
        ('request_selfie', 'Selfie Requested'),
    )
    PRIORITY_CHOICES = (
        ('Low', 'Low'),
        ('Medium', 'Medium'),
        ('High', 'High'),
    )
    reporter = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name='filed_reports')
    reported_user = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name='reports_received')
    reason = models.CharField(max_length=50, choices=REASON_CHOICES)
    description = models.TextField(blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    action_taken = models.CharField(max_length=20, choices=ACTION_CHOICES, blank=True, null=True)
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default='Medium')
    assign_to = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_reports')
    resolved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='resolved_reports')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Report #{self.id}: {self.reporter.username} -> {self.reported_user.username} ({self.reason})"

class Block(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    blocker = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name='blocking')
    blocked_user = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name='blocked_by')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('blocker', 'blocked_user')

    def __str__(self):
        return f"{self.blocker.username} blocked {self.blocked_user.username}"

class Transaction(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    STATUS_CHOICES = (
        ('paid', 'Paid'),
        ('successful', 'Paid'),
        ('failed', 'Failed'),
        ('disputed', 'Disputed'),
        ('refunded', 'Refunded'),
    )
    user = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name='transactions')
    plan_name = models.CharField(max_length=100)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    stripe_charge_id = models.CharField(max_length=255, blank=True, null=True)
    payment_method = models.CharField(max_length=100, default='Visa **** 4242')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['user', '-created_at'], name='tx_user_created_idx'),
            models.Index(fields=['status', '-created_at'], name='tx_status_created_idx'),
        ]

    def __str__(self):
        return f"TX #{self.id}: {self.plan_name} ({self.status}) for {self.user.username}"


class OTPLog(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ACTION_CHOICES = (
        ('generated', 'Generated'),
        ('verified', 'Verified'),
        ('failed_verification', 'Failed Verification'),
    )
    email = models.EmailField()
    otp = models.CharField(max_length=6)
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.email} - {self.action} at {self.timestamp}"


class SavedMatch(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name='saved_matches_sent')
    target_profile = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name='saved_matches_received')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'target_profile')

    def __str__(self):
        return f"{self.user.username} saved {self.target_profile.username}"

class AdminActionLog(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    admin_user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='actions_performed')
    target_user = models.ForeignKey(UserProfile, on_delete=models.SET_NULL, null=True, blank=True, related_name='actions_received')
    action = models.CharField(max_length=255)
    details = models.TextField(blank=True, null=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        admin_email = self.admin_user.email if self.admin_user else "Unknown Admin"
        target = f" on {self.target_user.username}" if self.target_user else ""
        return f"{admin_email} - {self.action}{target} at {self.timestamp}"


class Notification(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    title = models.CharField(max_length=255)
    body = models.TextField()
    type = models.CharField(max_length=50) # e.g. "match", "message", "super_like", "system"
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['recipient', '-created_at'], name='notif_recipient_created_idx'),
            models.Index(fields=['recipient', 'is_read'], name='notif_recipient_read_idx'),
        ]

    def __str__(self):
        return f"To {self.recipient.email}: {self.title}"
