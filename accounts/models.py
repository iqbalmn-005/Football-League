from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver


class UserRole(models.TextChoices):
    SUPER_ADMIN = 'SUPER_ADMIN', 'Super Admin'
    ORGANIZER = 'ORGANIZER', 'League Organizer'
    VIEWER = 'VIEWER', 'Viewer'


class OrganizerStatus(models.TextChoices):
    NOT_APPLIED = 'NOT_APPLIED', 'Not Applied'
    PENDING = 'PENDING', 'Pending Approval'
    APPROVED = 'APPROVED', 'Approved'
    REJECTED = 'REJECTED', 'Rejected'
    SUSPENDED = 'SUSPENDED', 'Suspended'


class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    role = models.CharField(max_length=20, choices=UserRole.choices, default=UserRole.VIEWER)
    phone = models.CharField(max_length=30, blank=True, db_index=True)
    organization_name = models.CharField(max_length=150, blank=True)
    experience_years = models.PositiveIntegerField(default=0)
    bio = models.TextField(blank=True)
    avatar = models.ImageField(upload_to='avatars/', blank=True, null=True)
    organizer_status = models.CharField(
        max_length=20,
        choices=OrganizerStatus.choices,
        default=OrganizerStatus.NOT_APPLIED
    )
    rejection_reason = models.TextField(blank=True)
    is_active_organizer = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.username} ({self.get_role_display()})"

    @property
    def display_name(self):
        if self.user.first_name:
            return f"{self.user.first_name} {self.user.last_name}".strip()
        return self.user.username

    @property
    def is_super_admin(self):
        return self.role == UserRole.SUPER_ADMIN or self.user.is_superuser

    @property
    def is_approved_organizer(self):
        return self.role == UserRole.ORGANIZER and self.organizer_status == OrganizerStatus.APPROVED and self.is_active_organizer


@receiver(post_save, sender=User)
def create_or_update_user_profile(sender, instance, created, **kwargs):
    if created:
        role = UserRole.SUPER_ADMIN if instance.is_superuser else UserRole.VIEWER
        status = OrganizerStatus.APPROVED if instance.is_superuser else OrganizerStatus.NOT_APPLIED
        UserProfile.objects.create(user=instance, role=role, organizer_status=status)
    else:
        if hasattr(instance, 'profile'):
            if instance.is_superuser and instance.profile.role != UserRole.SUPER_ADMIN:
                instance.profile.role = UserRole.SUPER_ADMIN
                instance.profile.organizer_status = OrganizerStatus.APPROVED
                instance.profile.save()


class OrganizerApplication(models.Model):
    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        APPROVED = 'APPROVED', 'Approved'
        REJECTED = 'REJECTED', 'Rejected'

    applicant = models.ForeignKey(User, on_delete=models.CASCADE, related_name='organizer_applications')
    full_name = models.CharField(max_length=150)
    organization_name = models.CharField(max_length=200)
    email = models.EmailField()
    phone = models.CharField(max_length=30)
    city = models.CharField(max_length=100)
    country = models.CharField(max_length=100, default="United Kingdom")
    experience_years = models.PositiveIntegerField(default=1)
    experience_summary = models.TextField(blank=True)
    proposed_leagues = models.TextField(blank=True, help_text="Proposed leagues or tournament formats")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    rejection_reason = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviewed_applications'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.organization_name} - {self.applicant.username} [{self.status}]"


class ActivityLog(models.Model):
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='activity_logs')
    action = models.CharField(max_length=100)
    details = models.TextField()
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        user_name = self.user.username if self.user else "System"
        return f"[{self.created_at.strftime('%Y-%m-%d %H:%M')}] {user_name}: {self.action}"

    @classmethod
    def log(cls, action, details, user=None, ip=None):
        return cls.objects.create(action=action, details=details, user=user, ip_address=ip)


class PlatformSetting(models.Model):
    platform_name = models.CharField(max_length=100, default="TOUCHLINE")
    tagline = models.CharField(max_length=200, default="Your Game. Your League.")
    contact_email = models.EmailField(default="support@touchline.football")
    allow_organizer_registration = models.BooleanField(default=True)
    auto_publish_fixtures = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    @classmethod
    def get_settings(cls):
        obj, _ = cls.objects.get_or_create(id=1)
        return obj

    def __str__(self):
        return self.platform_name


class Notification(models.Model):
    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    title = models.CharField(max_length=150)
    message = models.TextField()
    notification_type = models.CharField(max_length=30, default='INFO')
    is_read = models.BooleanField(default=False)
    link = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"To {self.recipient.username}: {self.title}"
