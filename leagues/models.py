from django.db import models
from django.contrib.auth.models import User
from django.utils.text import slugify
from teams.models import Team


class CompetitionType(models.TextChoices):
    LEAGUE = 'LEAGUE', 'League'
    TOURNAMENT = 'TOURNAMENT', 'Tournament'


class TournamentFormat(models.TextChoices):
    ROUND_ROBIN = 'ROUND_ROBIN', 'Round Robin / League'
    GROUP_KNOCKOUT = 'GROUP_KNOCKOUT', 'Group Stage + Knockout'
    SINGLE_ELIMINATION = 'SINGLE_ELIMINATION', 'Single Elimination / Knockout'


class CompetitionCategory(models.TextChoices):
    ELEVEN_A_SIDE = '11-a-side', '11-a-side'
    SEVEN_A_SIDE = '7-a-side', '7-a-side'
    FIVE_A_SIDE = '5-a-side', '5-a-side'
    YOUTH = 'youth', 'Youth'


class CompetitionStatus(models.TextChoices):
    PENDING = 'PENDING', 'Under Review'
    UPCOMING = 'UPCOMING', 'Upcoming / Registration Open'
    ACTIVE = 'ACTIVE', 'Active / Ongoing'
    COMPLETED = 'COMPLETED', 'Completed'
    ARCHIVED = 'ARCHIVED', 'Archived'


class Competition(models.Model):
    name = models.CharField(max_length=150)
    slug = models.SlugField(max_length=160, blank=True)
    competition_type = models.CharField(
        max_length=20, choices=CompetitionType.choices, default=CompetitionType.LEAGUE
    )
    tournament_format = models.CharField(
        max_length=30, choices=TournamentFormat.choices, default=TournamentFormat.ROUND_ROBIN
    )
    category = models.CharField(
        max_length=30, choices=CompetitionCategory.choices, default=CompetitionCategory.ELEVEN_A_SIDE
    )
    description = models.TextField(blank=True)
    season = models.CharField(max_length=50, default="2026/2027")
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    max_teams = models.PositiveIntegerField(default=8)
    location = models.CharField(max_length=150, default="London, UK")
    logo = models.ImageField(upload_to='competition_logos/', blank=True, null=True)
    logo_url = models.CharField(max_length=500, blank=True)
    status = models.CharField(
        max_length=20, choices=CompetitionStatus.choices, default=CompetitionStatus.ACTIVE
    )
    is_published = models.BooleanField(default=True)
    primary_organizer = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='organized_competitions'
    )
    teams = models.ManyToManyField(Team, through='CompetitionTeam', related_name='competitions', blank=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_competitions'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} ({self.season})"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(f"{self.name}-{self.season}")
        super().save(*args, **kwargs)

    def get_logo_url(self):
        if self.logo and hasattr(self.logo, 'url'):
            return self.logo.url
        if self.logo_url:
            return self.logo_url
        return ""

    @property
    def total_teams_count(self):
        return self.teams.count()

    @property
    def spots_left(self):
        left = self.max_teams - self.total_teams_count
        return max(0, left)


class TournamentGroup(models.Model):
    competition = models.ForeignKey(Competition, on_delete=models.CASCADE, related_name='groups')
    name = models.CharField(max_length=50)

    class Meta:
        ordering = ['name']
        unique_together = ('competition', 'name')

    def __str__(self):
        return f"{self.competition.name} - {self.name}"


class CompetitionTeam(models.Model):
    competition = models.ForeignKey(Competition, on_delete=models.CASCADE)
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    group = models.ForeignKey(TournamentGroup, on_delete=models.SET_NULL, null=True, blank=True, related_name='group_teams')
    seed = models.PositiveIntegerField(null=True, blank=True)
    registered_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('competition', 'team')

    def __str__(self):
        return f"{self.team.name} in {self.competition.name}"


class CompetitionAssignment(models.Model):
    class Role(models.TextChoices):
        PRIMARY = 'PRIMARY', 'Primary Organizer'
        CO_ORGANIZER = 'CO_ORGANIZER', 'Co-Organizer'

    competition = models.ForeignKey(Competition, on_delete=models.CASCADE, related_name='assignments')
    organizer = models.ForeignKey(User, on_delete=models.CASCADE, related_name='competition_assignments')
    assigned_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='assignments_made')
    role = models.CharField(max_length=30, choices=Role.choices, default=Role.PRIMARY)
    can_edit_fixtures = models.BooleanField(default=True)
    can_enter_results = models.BooleanField(default=True)
    can_manage_teams = models.BooleanField(default=True)
    can_invite_organizers = models.BooleanField(default=False)
    assigned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('competition', 'organizer')

    def __str__(self):
        return f"{self.organizer.username} -> {self.competition.name} ({self.role})"
