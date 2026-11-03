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


class Match(models.Model):
    competition = models.ForeignKey(Competition, on_delete=models.CASCADE, related_name='matches')
    tournament_round = models.CharField(max_length=60, default="Matchweek 1")
    round_number = models.PositiveIntegerField(default=1)
    group = models.ForeignKey(TournamentGroup, on_delete=models.SET_NULL, null=True, blank=True, related_name='matches')
    home_team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='home_matches')
    away_team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='away_matches')
    match_date = models.DateField()
    kickoff_time = models.TimeField()
    venue = models.CharField(max_length=150, default="Central Stadium")
    status = models.CharField(max_length=20, choices=MatchStatus.choices, default=MatchStatus.SCHEDULED)
    home_score = models.IntegerField(null=True, blank=True, default=None)
    away_score = models.IntegerField(null=True, blank=True, default=None)
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

    def __str__(self):
        score = f"{self.home_score} - {self.away_score}" if self.home_score is not None and self.away_score is not None else "vs"
        return f"{self.home_team.name} {score} {self.away_team.name} ({self.tournament_round})"

    @property
    def is_finished(self):
        return self.status == MatchStatus.COMPLETED

    @property
    def display_score(self):
        if self.home_score is not None and self.away_score is not None:
            return f"{self.home_score} : {self.away_score}"
        return "VS"

    @property
    def winner(self):
        if not self.is_finished or self.home_score is None or self.away_score is None:
            return None
        if self.home_score > self.away_score:
            return self.home_team
        elif self.away_score > self.home_score:
            return self.away_team
        return None  # Draw

    def _get_team_highlights(self, team):
        """Returns grouped goal scorers and red cards (no yellow cards, no assists)."""
        valid_types = [MatchEventType.GOAL, MatchEventType.PENALTY, MatchEventType.OWN_GOAL, MatchEventType.RED_CARD]
        events = self.events.filter(team=team, event_type__in=valid_types).order_by('minute', 'extra_minute')
        
        highlights = []
        goal_map = {}
        for e in events:
            p_name = e.player.full_name if e.player else "Unknown"
            p_id = e.player_id or p_name
            if e.event_type in [MatchEventType.GOAL, MatchEventType.PENALTY, MatchEventType.OWN_GOAL]:
                min_str = f"{e.minute}'"
                if e.event_type == MatchEventType.PENALTY:
                    min_str += " P"
                elif e.event_type == MatchEventType.OWN_GOAL:
                    min_str += " OG"
                if p_id not in goal_map:
                    item = {
                        'icon': '⚽',
                        'player_name': p_name,
                        'minutes': [min_str]
                    }
                    goal_map[p_id] = item
                    highlights.append(item)
                else:
                    goal_map[p_id]['minutes'].append(min_str)
            elif e.event_type == MatchEventType.RED_CARD:
                highlights.append({
                    'icon': '🟥',
                    'player_name': p_name,
                    'minutes': [f"{e.minute}'"]
                })
        
        for h in highlights:
            h['text'] = f"{h['player_name']} ({', '.join(h['minutes'])})"
        return highlights

    @property
    def home_highlights(self):
        return self._get_team_highlights(self.home_team)

    @property
    def away_highlights(self):
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
