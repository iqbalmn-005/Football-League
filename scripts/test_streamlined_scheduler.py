import sys, os
from datetime import date, timedelta, time

sys.path.insert(0, os.path.abspath('.'))
sys.stdout.reconfigure(encoding='utf-8')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Football.settings')
import django
django.setup()

from teams.models import Team
from leagues.models import Competition, TournamentFormat

teams = list(Team.objects.all()[:8])
print(f"Loaded {len(teams)} teams.")

def sample_daily_slots(count):
    presets = {
        1: ["15:00"],
        2: ["15:00", "17:30"],
        3: ["14:00", "16:30", "19:00"],
        4: ["11:00", "13:30", "16:00", "18:30"],
        5: ["10:00", "12:15", "14:30", "16:45", "19:00"],
        6: ["09:30", "11:30", "13:30", "15:30", "17:30", "19:30"],
    }
    return presets.get(count, [f"{10 + i * 2}:00" for i in range(count)])

print("Preset for 2 matches a day:", sample_daily_slots(2))
print("Preset for 3 matches a day:", sample_daily_slots(3))
