from django.db import models
from django.contrib.auth.models import User
from datetime import date


class PositionChoice(models.TextChoices):
    GK = 'GK', 'Goalkeeper'
    DEF = 'DEF', 'Defender'
    MID = 'MID', 'Midfielder'
    FWD = 'FWD', 'Forward'


class Team(models.Model):
    name = models.CharField(max_length=120, unique=True)
    short_name = models.CharField(max_length=10, blank=True)
    logo = models.ImageField(upload_to='team_logos/', blank=True, null=True)
    manager_name = models.CharField(max_length=120, blank=True)
    contact_phone = models.CharField(max_length=30, blank=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='teams_created')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.short_name:
            words = self.name.split()
            if len(words) == 1:
                self.short_name = words[0][:3].upper()
            else:
                self.short_name = "".join([w[0] for w in words[:3]]).upper()
        super().save(*args, **kwargs)

    def get_logo_url(self):
        if self.logo and hasattr(self.logo, 'url'):
            return self.logo.url
        if hasattr(self, 'logo_url') and self.logo_url:
            return self.logo_url
        return ""


class Player(models.Model):
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='players')
    full_name = models.CharField(max_length=120)
    jersey_number = models.PositiveIntegerField()
    position = models.CharField(max_length=10, choices=PositionChoice.choices, default=PositionChoice.FWD)
    date_of_birth = models.DateField(null=True, blank=True)
    nationality = models.CharField(max_length=60, default="United Kingdom")
    photo = models.ImageField(upload_to='player_photos/', blank=True, null=True)
    photo_url = models.CharField(max_length=500, blank=True)
    is_captain = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['jersey_number', 'full_name']
        unique_together = ('team', 'jersey_number')

    def __str__(self):
        return f"#{self.jersey_number} {self.full_name} ({self.team.name})"

    @property
    def age(self):
        if not self.date_of_birth:
            return None
        today = date.today()
        return today.year - self.date_of_birth.year - (
            (today.month, today.day) < (self.date_of_birth.month, self.date_of_birth.day)
        )

    def get_photo_url(self):
        if self.photo and hasattr(self.photo, 'url'):
            return self.photo.url
        if self.photo_url:
            return self.photo_url
        return "/static/img/players/p1.jpg"

    @property
    def total_goals(self):
        return self.match_events.filter(event_type__in=['GOAL', 'PENALTY']).count()

    @property
    def total_assists(self):
        return self.assist_events.filter(event_type__in=['GOAL', 'PENALTY']).count()

    @property
    def yellow_cards(self):
        return self.match_events.filter(event_type='YELLOW_CARD').count()

    @property
    def red_cards(self):
        return self.match_events.filter(event_type='RED_CARD').count()

    @property
    def appearances(self):
        # Count completed matches of this player's team where player is active
        return self.team.home_matches.filter(status='COMPLETED').count() + \
               self.team.away_matches.filter(status='COMPLETED').count()

    @property
    def clean_sheets(self):
        if self.position != PositionChoice.GK:
            return 0
        home_cs = self.team.home_matches.filter(status='COMPLETED', away_score=0).count()
        away_cs = self.team.away_matches.filter(status='COMPLETED', home_score=0).count()
        return home_cs + away_cs
