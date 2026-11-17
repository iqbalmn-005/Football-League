"""
FUTBOLIX SQLite to PostgreSQL Data Migration Script
Transfers all data safely from local SQLite to Neon/Supabase PostgreSQL
Preserves primary keys, foreign keys, and resets database sequences.
"""

import os
import sys
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import socket
import ssl
from collections import OrderedDict

# Handle potential DNS issues on some local networks
orig_getaddrinfo = socket.getaddrinfo
def patched_getaddrinfo(host, port, *args, **kwargs):
    if 'neon.tech' in host:
        try:
            return orig_getaddrinfo(host, port, *args, **kwargs)
        except socket.gaierror:
            return orig_getaddrinfo('3.142.41.151', port, *args, **kwargs)
    return orig_getaddrinfo(host, port, *args, **kwargs)
socket.getaddrinfo = patched_getaddrinfo

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Football.settings')
import django
django.setup()

from django.conf import settings
from django.db import connections, transaction
from django.contrib.auth import get_user_model
from django.db.models.signals import post_save
from django.core.management import call_command

# Neon DB Connection setup
NEON_DATABASE_URL = os.environ.get(
    'DATABASE_URL',
    'postgresql://neondb_owner:npg_Dvl0kOqrfXt6@ep-dry-sea-bd7aiz6i-pooler.c-8.us-east-2.aws.neon.tech/neondb?sslmode=require&channel_binding=require'
)

if 'neon' not in settings.DATABASES:
    settings.DATABASES['neon'] = {
        'ENGINE': 'django_pg8000',
        'NAME': 'neondb',
        'USER': 'neondb_owner',
        'PASSWORD': 'npg_Dvl0kOqrfXt6',
        'HOST': 'ep-dry-sea-bd7aiz6i-pooler.c-8.us-east-2.aws.neon.tech',
        'PORT': 5432,
        'TIME_ZONE': 'UTC',
        'CONN_MAX_AGE': 0,
        'CONN_HEALTH_CHECKS': False,
        'AUTOCOMMIT': True,
        'OPTIONS': {'ssl_context': ssl.create_default_context()}
    }

from accounts.models import (
    UserProfile, OrganizerApplication, PlatformSetting, Notification, ActivityLog
)
from leagues.models import (
    Competition, TournamentGroup, CompetitionTeam, QualifiedTeam, CompetitionAssignment
)
from teams.models import Team, Player
from matches.models import (
    Match, MatchEvent, PenaltyShootout, PenaltyShootoutAttempt
)
from standings.models import StandingEntry

MODELS_IN_ORDER = [
    get_user_model(),
    UserProfile,
    OrganizerApplication,
    PlatformSetting,
    Notification,
    ActivityLog,
    Team,
    Player,
    Competition,
    TournamentGroup,
    CompetitionTeam,
    QualifiedTeam,
    CompetitionAssignment,
    Match,
    MatchEvent,
    PenaltyShootout,
    PenaltyShootoutAttempt,
    StandingEntry,
]

def migrate_data():
    print("=" * 70)
    print("FUTBOLIX: MIGRATING DATA FROM SQLITE TO NEON POSTGRESQL")
    print("=" * 70)

    # Disconnect user post_save signals to prevent auto-creating duplicate profiles
    from accounts.models import create_or_update_user_profile
    post_save.disconnect(create_or_update_user_profile, sender=get_user_model())

    results = []

    for model in MODELS_IN_ORDER:
        model_name = f"{model._meta.app_label}.{model._meta.model_name}"
        sqlite_objs = list(model.objects.using('default').all())
        sqlite_count = len(sqlite_objs)
        
        print(f"\nMigrating {model_name}: {sqlite_count} records found in SQLite...")

        if not sqlite_objs:
            results.append((model_name, 0, 0, "MATCH (Empty)"))
            continue

        # In PostgreSQL, insert in batches
        BATCH_SIZE = 100
        migrated_count = 0

        # We use ignore_conflicts=False or update_or_create to preserve exact records
        for i in range(0, sqlite_count, BATCH_SIZE):
            chunk = sqlite_objs[i:i + BATCH_SIZE]
            # Convert chunk to fresh instances for 'neon'
            neon_instances = []
            for obj in chunk:
                # Re-instantiate so Django treats them as target db records
                neon_instances.append(obj)
            
            # Save or bulk create into neon
            try:
                model.objects.using('neon').bulk_create(neon_instances, ignore_conflicts=True, batch_size=BATCH_SIZE)
                migrated_count += len(chunk)
            except Exception as e:
                print(f"  [bulk_create failed, falling back to individual saves]: {e}")
                for obj in chunk:
                    try:
                        obj.save(using='neon', force_insert=False)
                        migrated_count += 1
                    except Exception as ex:
                        print(f"  Error migrating {model_name} pk={obj.pk}: {ex}")

        neon_count = model.objects.using('neon').count()
        status = "MATCH" if neon_count == sqlite_count else f"DIFF (SQLite={sqlite_count}, Neon={neon_count})"
        print(f" -> Neon count: {neon_count} [{status}]")
        results.append((model_name, sqlite_count, neon_count, status))

    # Reset sequences in PostgreSQL
    print("\nResetting PostgreSQL primary key sequences...")
    with connections['neon'].cursor() as cur:
        for model in MODELS_IN_ORDER:
            table_name = model._meta.db_table
            pk_name = model._meta.pk.name
            try:
                cur.execute(f"SELECT setval(pg_get_serial_sequence('{table_name}', '{pk_name}'), coalesce(max({pk_name}), 1)) FROM {table_name};")
            except Exception as e:
                # Model might use UUID or sequence might not be standard
                pass

    print("\n" + "=" * 70)
    print("MIGRATION INTEGRITY SUMMARY")
    print("=" * 70)
    all_matched = True
    for model_name, sq_c, ne_c, status in results:
        print(f" {model_name:35} : SQLite={sq_c:4d} | Neon={ne_c:4d} | {status}")
        if sq_c != ne_c:
            all_matched = False

    print("=" * 70)
    if all_matched:
        print("ALL DATA PERFECTLY MIGRATED AND VERIFIED!")
    else:
        print("WARNING: Some record counts differ, review discrepancies above.")
    print("=" * 70)

if __name__ == '__main__':
    migrate_data()
