from django.db import models
from leagues.models import Competition, TournamentGroup
from teams.models import Team


class StandingEntry(models.Model):
    competition = models.ForeignKey(Competition, on_delete=models.CASCADE, related_name='standings')
    group = models.ForeignKey(
        TournamentGroup, on_delete=models.SET_NULL, null=True, blank=True, related_name='standings'
    )
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='standing_entries')
    played = models.PositiveIntegerField(default=0)
    won = models.PositiveIntegerField(default=0)
    drawn = models.PositiveIntegerField(default=0)
    lost = models.PositiveIntegerField(default=0)
    goals_for = models.PositiveIntegerField(default=0)
    goals_against = models.PositiveIntegerField(default=0)
    goal_difference = models.IntegerField(default=0)
    points = models.IntegerField(default=0)
    position = models.PositiveIntegerField(default=1)
    form = models.CharField(max_length=50, blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['position', '-points', '-goal_difference', '-goals_for']
        unique_together = ('competition', 'group', 'team')

    def __str__(self):
        return f"{self.position}. {self.team.name} - {self.points} pts ({self.competition.name})"

    @property
    def form_list(self):
        if not self.form:
            return []
        return [f.strip() for f in self.form.split(',') if f.strip()]
