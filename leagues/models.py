from django.db import models
from django.contrib.auth.models import User
from django.utils.text import slugify
from teams.models import Team


class CompetitionType(models.TextChoices):
    LEAGUE = 'LEAGUE', 'League'
    TOURNAMENT = 'TOURNAMENT', 'Tournament'


class TournamentFormat(models.TextChoices):
    ROUND_ROBIN = 'ROUND_ROBIN', 'Round Robin (League)'
    LEAGUE_KNOCKOUT = 'LEAGUE_KNOCKOUT', 'League + Tournament'
    GROUP_KNOCKOUT = 'GROUP_KNOCKOUT', 'Group Mode + Tournament'
    SINGLE_ELIMINATION = 'SINGLE_ELIMINATION', 'Tournament / Knockout'
    PAGE_MCINTYRE = 'PAGE_MCINTYRE', 'Page–McIntyre System (Final 4)'


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
    def is_pure_knockout(self):
        if self.tournament_format in [
            TournamentFormat.SINGLE_ELIMINATION,
            TournamentFormat.PAGE_MCINTYRE,
            'SINGLE_ELIMINATION',
            'PAGE_MCINTYRE',
            'KNOCKOUT'
        ]:
            return True
        if self.tournament_format in [
            TournamentFormat.ROUND_ROBIN,
            TournamentFormat.LEAGUE_KNOCKOUT,
            TournamentFormat.GROUP_KNOCKOUT,
            'ROUND_ROBIN',
            'LEAGUE_KNOCKOUT',
            'GROUP_KNOCKOUT'
        ]:
            return False
        # Fallback for legacy competitions where tournament_format was not explicitly set
        if self.matches.exists() and not self.groups.exists():
            rounds = list(self.matches.values_list('tournament_round', flat=True))
            if rounds and all(any(kw in (r or '').lower() for kw in ['final', 'semi', 'quarter', 'round of', 'playoff', 'elimination', 'qualifying']) for r in rounds):
                return True
        return False

    @property
    def spots_left(self):
        left = self.max_teams - self.total_teams_count
        return max(0, left)

    @property
    def is_completed(self):
        if self.status == CompetitionStatus.COMPLETED:
            return True
        total = self.matches.count()
        return total > 0 and not self.matches.exclude(status='COMPLETED').exists()

    @property
    def winner_entry(self):
        if not self.is_completed:
            return None
        w_team = self.winner
        if w_team:
            entry = self.standings.filter(team=w_team).first()
            if entry:
                return entry
        return self.standings.order_by('position').first()

    @property
    def winner(self):
        if not self.is_completed:
            return None
        final_match = self.matches.filter(
            models.Q(tournament_round__iexact='Final') |
            models.Q(tournament_round__iexact='Grand Final') |
            models.Q(tournament_round__iexact='Grand Championship Final') |
            models.Q(tournament_round__icontains='Grand Final') |
            (models.Q(tournament_round__iendswith='Final') & ~models.Q(tournament_round__icontains='Semi') & ~models.Q(tournament_round__icontains='Preliminary') & ~models.Q(tournament_round__icontains='Elimination') & ~models.Q(tournament_round__icontains='Qualifying')),
            status='COMPLETED'
        ).order_by('-round_number', '-match_date').first()
        if final_match and final_match.winner:
            return final_match.winner

        top_entry = self.standings.order_by('position').first()
        if top_entry:
            return top_entry.team
        return None


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
