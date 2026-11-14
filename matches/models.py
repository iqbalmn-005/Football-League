from django.db import models
from django.contrib.auth.models import User
from leagues.models import Competition, TournamentGroup
from teams.models import Team, Player


class MatchStatus(models.TextChoices):
    SCHEDULED = 'SCHEDULED', 'Scheduled'
    LIVE = 'LIVE', 'Live'
    COMPLETED = 'COMPLETED', 'Completed'
    POSTPONED = 'POSTPONED', 'Postponed'
    CANCELLED = 'CANCELLED', 'Cancelled'


class MatchEventType(models.TextChoices):
    GOAL = 'GOAL', 'Goal'
    PENALTY = 'PENALTY', 'Penalty Goal'
    OWN_GOAL = 'OWN_GOAL', 'Own Goal'
    YELLOW_CARD = 'YELLOW_CARD', 'Yellow Card'
    RED_CARD = 'RED_CARD', 'Red Card'
    SUB_ON = 'SUB_ON', 'Substituted On'
    CLEAN_SHEET = 'CLEAN_SHEET', 'Clean Sheet'


class Match(models.Model):
    competition = models.ForeignKey(Competition, on_delete=models.CASCADE, related_name='matches')
    tournament_round = models.CharField(max_length=60, default="Matchweek 1")
    round_number = models.PositiveIntegerField(default=1)
    group = models.ForeignKey(TournamentGroup, on_delete=models.SET_NULL, null=True, blank=True, related_name='matches')
    home_team = models.ForeignKey(Team, on_delete=models.CASCADE, null=True, blank=True, related_name='home_matches')
    away_team = models.ForeignKey(Team, on_delete=models.CASCADE, null=True, blank=True, related_name='away_matches')
    placeholder_home = models.CharField(max_length=150, blank=True, default='')
    placeholder_away = models.CharField(max_length=150, blank=True, default='')
    match_date = models.DateField()
    kickoff_time = models.TimeField()
    venue = models.CharField(max_length=150, default="Central Stadium")
    status = models.CharField(max_length=20, choices=MatchStatus.choices, default=MatchStatus.SCHEDULED)
    home_score = models.IntegerField(null=True, blank=True, default=None)
    away_score = models.IntegerField(null=True, blank=True, default=None)
    home_regular_score = models.IntegerField(null=True, blank=True, default=None)
    away_regular_score = models.IntegerField(null=True, blank=True, default=None)
    home_extra_time_score = models.IntegerField(null=True, blank=True, default=None)
    away_extra_time_score = models.IntegerField(null=True, blank=True, default=None)
    extra_time = models.BooleanField(default=False)
    penalties = models.BooleanField(default=False)
    home_penalties = models.IntegerField(null=True, blank=True)
    away_penalties = models.IntegerField(null=True, blank=True)
    recorded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='recorded_matches')
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['match_date', 'kickoff_time']

    @property
    def home_display_name(self):
        if self.home_team:
            return self.home_team.name
        return self.placeholder_home or "TBD"

    @property
    def away_display_name(self):
        if self.away_team:
            return self.away_team.name
        return self.placeholder_away or "TBD"

    def __str__(self):
        score = f"{self.home_score} - {self.away_score}" if self.home_score is not None and self.away_score is not None else "vs"
        h = self.home_team.name if self.home_team else (self.placeholder_home or "TBD")
        a = self.away_team.name if self.away_team else (self.placeholder_away or "TBD")
        return f"{h} {score} {a} ({self.tournament_round})"

    @property
    def is_finished(self):
        return self.status == MatchStatus.COMPLETED

    @property
    def is_knockout(self):
        if self.competition and self.competition.is_pure_knockout:
            return True
        r = (self.tournament_round or '').lower()
        keywords = [
            'final', 'semi', 'quarter', 'round of', 'playoff',
            'elimination', 'qualifying', 'play-in', 'knockout', 'preliminary'
        ]
        return any(kw in r for kw in keywords)

    @property
    def display_score(self):
        if self.home_score is not None and self.away_score is not None:
            if self.penalties and self.home_penalties is not None and self.away_penalties is not None:
                return f"{self.home_score} : {self.away_score} ({self.home_penalties}–{self.away_penalties} pens)"
            return f"{self.home_score} : {self.away_score}"
        return "VS"

    @property
    def winner(self):
        if not self.is_finished or self.home_score is None or self.away_score is None:
            return None
        if self.penalties and self.home_penalties is not None and self.away_penalties is not None:
            if self.home_penalties > self.away_penalties:
                return self.home_team
            elif self.away_penalties > self.home_penalties:
                return self.away_team
        if self.home_score > self.away_score:
            return self.home_team
        elif self.away_score > self.home_score:
            return self.away_team
        return None  # Draw

    @property
    def round_byes(self):
        """
        Returns list of team names that received BYEs in this match's tournament round,
        parsed from the notes field (e.g. {"byes": ["Team A", "Team B"]}).
        """
        if not self.notes:
            return []
        try:
            import json
            data = json.loads(self.notes)
            if isinstance(data, dict) and 'byes' in data:
                return data['byes']
        except Exception:
            pass
        if self.notes.startswith('BYE:'):
            return [b.strip() for b in self.notes[4:].split(',') if b.strip()]
        return []

    def _get_team_highlights(self, team):
        """Returns grouped goal scorers and red cards (no yellow cards, no assists)."""
        valid_types = [MatchEventType.GOAL, MatchEventType.PENALTY, MatchEventType.OWN_GOAL, MatchEventType.RED_CARD]
        if hasattr(self, '_prefetched_objects_cache') and 'events' in self._prefetched_objects_cache:
            events = [
                e for e in self.events.all()
                if (e.team_id == team.id or e.team == team) and e.event_type in valid_types
            ]
            events.sort(key=lambda e: (e.minute or 0, e.extra_minute or 0))
        else:
            events = self.events.filter(team=team, event_type__in=valid_types).order_by('minute', 'extra_minute')
        
        highlights = []
        goal_map = {}
        for e in events:
            p_name = e.player.full_name if e.player else "Unknown"
            p_id = e.player_id or p_name
            if e.event_type in [MatchEventType.GOAL, MatchEventType.PENALTY, MatchEventType.OWN_GOAL]:
                min_str = f"{e.minute}'" if (e.minute and e.minute > 0) else ""
                if e.event_type == MatchEventType.PENALTY:
                    min_str = (min_str + " P").strip()
                elif e.event_type == MatchEventType.OWN_GOAL:
                    min_str = (min_str + " OG").strip()
                if p_id not in goal_map:
                    item = {
                        'icon': '⚽',
                        'player_name': p_name,
                        'minutes': [min_str] if min_str else [],
                        'count': 1
                    }
                    goal_map[p_id] = item
                    highlights.append(item)
                else:
                    goal_map[p_id]['count'] += 1
                    if min_str:
                        goal_map[p_id]['minutes'].append(min_str)
            elif e.event_type == MatchEventType.RED_CARD:
                min_str = f"{e.minute}'" if (e.minute and e.minute > 0) else ""
                highlights.append({
                    'icon': '🟥',
                    'player_name': p_name,
                    'minutes': [min_str] if min_str else [],
                    'count': 1
                })
        
        for h in highlights:
            if h.get('minutes'):
                h['text'] = f"{h['player_name']} ({', '.join(h['minutes'])})"
            elif h.get('count', 1) > 1:
                h['text'] = f"{h['player_name']} (x{h['count']})"
            else:
                h['text'] = h['player_name']
        return highlights

    @property
    def home_highlights(self):
        if not self.home_team:
            return []
        return self._get_team_highlights(self.home_team)

    @property
    def away_highlights(self):
        if not self.away_team:
            return []
        return self._get_team_highlights(self.away_team)


class MatchEvent(models.Model):
    match = models.ForeignKey(Match, on_delete=models.CASCADE, related_name='events')
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name='match_events')
    assist_player = models.ForeignKey(Player, on_delete=models.SET_NULL, null=True, blank=True, related_name='assist_events')
    event_type = models.CharField(max_length=20, choices=MatchEventType.choices)
    minute = models.PositiveIntegerField()
    extra_minute = models.PositiveIntegerField(default=0)
    description = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['minute', 'extra_minute']

    def __str__(self):
        return f"{self.minute}' {self.get_event_type_display()} - {self.player.full_name} ({self.team.name})"


class ShootoutPhase(models.TextChoices):
    INITIAL_FIVE = 'INITIAL_FIVE', 'Initial Five'
    SUDDEN_DEATH = 'SUDDEN_DEATH', 'Sudden Death'


class ShootoutOutcome(models.TextChoices):
    GOAL = 'GOAL', 'Goal'
    MISS = 'MISS', 'Miss'
    SAVED = 'SAVED', 'Saved'
    POST = 'POST', 'Post / Crossbar'


class ShootoutStatus(models.TextChoices):
    IN_PROGRESS = 'IN_PROGRESS', 'In Progress'
    COMPLETED = 'COMPLETED', 'Completed'


class PenaltyShootout(models.Model):
    match = models.OneToOneField(Match, on_delete=models.CASCADE, related_name='penalty_shootout')
    status = models.CharField(max_length=20, choices=ShootoutStatus.choices, default=ShootoutStatus.IN_PROGRESS)
    home_score = models.PositiveIntegerField(default=0)
    away_score = models.PositiveIntegerField(default=0)
    winner = models.ForeignKey(Team, on_delete=models.SET_NULL, null=True, blank=True, related_name='shootouts_won')
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-started_at']

    def __str__(self):
        return f"Shootout: {self.match} ({self.home_score} - {self.away_score})"

    @property
    def is_completed(self):
        return self.status == ShootoutStatus.COMPLETED


class PenaltyShootoutAttempt(models.Model):
    shootout = models.ForeignKey(PenaltyShootout, on_delete=models.CASCADE, related_name='attempts')
    match = models.ForeignKey(Match, on_delete=models.CASCADE, related_name='penalty_attempts')
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='penalty_attempts')
    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name='penalty_attempts')
    attempt_order = models.PositiveIntegerField()
    attempt_number = models.PositiveIntegerField()
    shootout_round = models.PositiveIntegerField(default=1)
    shootout_phase = models.CharField(max_length=20, choices=ShootoutPhase.choices, default=ShootoutPhase.INITIAL_FIVE)
    outcome = models.CharField(max_length=20, choices=ShootoutOutcome.choices)
    is_successful = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['attempt_order']
        unique_together = [('shootout', 'attempt_order')]

    def __str__(self):
        return f"Attempt #{self.attempt_order} (R{self.shootout_round}) {self.team.name}: {self.player.full_name} ({self.outcome})"
