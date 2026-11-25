from django.db import models
from django.contrib.auth.models import User
from leagues.models import Competition


class ScheduleGenerationLog(models.Model):
    """
    Tracks fixture schedule generation attempts, configurations, and validation outcomes.
    """
    competition = models.ForeignKey(Competition, on_delete=models.CASCADE, related_name='schedule_logs')
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='schedule_logs')
    strategy = models.CharField(max_length=30, default='optimized')
    config_snapshot = models.JSONField(default=dict)
    total_matches = models.PositiveIntegerField(default=0)
    dates_used = models.PositiveIntegerField(default=0)
    is_valid = models.BooleanField(default=True)
    validation_errors = models.JSONField(default=list)
    validation_warnings = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        status = "Valid" if self.is_valid else "Invalid"
        return f"{self.competition.name} - {self.strategy} ({self.total_matches} matches, {status})"
