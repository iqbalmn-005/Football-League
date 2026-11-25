import json
from datetime import date, time, timedelta
from collections import Counter
from django.test import TestCase, Client
from django.contrib.auth.models import User
from leagues.models import Competition, CompetitionTeam, TournamentFormat, CompetitionStatus
from teams.models import Team
from matches.models import Match, MatchStatus
from fixtures.models import ScheduleGenerationLog
from fixtures.services import generate_smart_fixtures, commit_generated_fixtures
from fixtures.scheduling_engine import validate_complete_schedule


class ConstraintBasedFixtureSchedulerTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='org_test', password='pw', is_staff=True)
        # Ensure organizer profile if required by decorator
        try:
            from accounts.models import UserProfile
            UserProfile.objects.get_or_create(
                user=self.user,
                defaults={'role': 'ORGANIZER', 'is_approved': True}
            )
        except Exception:
            pass

        self.comp = Competition.objects.create(
            name='Constraint Test League',
            season='2026/27',
            status=CompetitionStatus.ACTIVE,
            primary_organizer=self.user,
            start_date=date(2026, 12, 1),
            end_date=date(2027, 2, 28),
        )
        self.teams = []
        for i in range(1, 11):
            t = Team.objects.create(name=f'Test Club {i}', short_name=f'TC{i}')
            CompetitionTeam.objects.create(competition=self.comp, team=t)
            self.teams.append(t)

    def _run_gen(self, team_count, fmt=TournamentFormat.ROUND_ROBIN, **kwargs):
        cfg = {
            'tournament_format': fmt,
            'round_robin_type': kwargs.get('round_robin_type', 'single'),
            'start_date': kwargs.get('start_date', '2026-12-01'),
            'end_date': kwargs.get('end_date', '2026-12-30'),
            'preferred_days': kwargs.get('preferred_days', ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']),
            'matches_per_day': kwargs.get('matches_per_day', 2),
            'min_rest_days': kwargs.get('min_rest_days', 0),
            'excluded_dates': kwargs.get('excluded_dates', []),
            'daily_kickoff_times': kwargs.get('daily_kickoff_times', ['14:00', '16:30', '19:00']),
            'venues': kwargs.get('venues', ['Stadium X', 'Stadium Y']),
            'num_groups': kwargs.get('num_groups', 2),
            'qualifiers_per_group': kwargs.get('qualifiers_per_group', 2),
            'sf_preference': kwargs.get('sf_preference', 'same_day'),
            'scheduling_strategy': kwargs.get('scheduling_strategy', 'optimized'),
            'selected_team_ids': [t.id for t in self.teams[:team_count]],
        }
        return generate_smart_fixtures(self.comp, cfg)

    def test_optimized_date_distribution_minimizes_dates_without_2_plus_1(self):
        # 6 teams single RR = 15 matches, 2 matches/day -> optimal = 8 dates (7x2 + 1x1)
        res = self._run_gen(6, matches_per_day=2, end_date='2026-12-20')
        self.assertTrue(res['success'], res.get('errors'))
        self.assertTrue(res['validation']['is_valid'])
        matches = res['matches']
        self.assertEqual(len(matches), 15)
        dates = Counter(m['match_date'] for m in matches)
        self.assertEqual(len(dates), 8)
        self.assertLessEqual(max(dates.values()), 2)
        # Verify matchweeks share dates cleanly while preserving round_number
        shared_dates = [d for d in dates if len(set(m['round_number'] for m in matches if m['match_date'] == d)) > 1]
        self.assertGreater(len(shared_dates), 0)

    def test_double_round_robin_preserves_legs_and_reversed_home_away(self):
        res = self._run_gen(4, round_robin_type='double', matches_per_day=2, end_date='2026-12-20')
        self.assertTrue(res['success'], res.get('errors'))
        matches = res['matches']
        self.assertEqual(len(matches), 12)
        leg1 = [m for m in matches if m['leg'] == 1]
        leg2 = [m for m in matches if m['leg'] == 2]
        self.assertEqual(len(leg1), 6)
        self.assertEqual(len(leg2), 6)
        # Every pair appears once in leg 1 and reversed in leg 2
        leg1_pairs = {(m['home_team_id'], m['away_team_id']) for m in leg1}
        leg2_pairs = {(m['home_team_id'], m['away_team_id']) for m in leg2}
        for h, a in leg1_pairs:
            self.assertIn((a, h), leg2_pairs)

    def test_min_rest_days_constraint_enforced(self):
        # 6 teams, min_rest_days=1 (at least 2 calendar days between any team's matches)
        res = self._run_gen(6, matches_per_day=2, min_rest_days=1, end_date='2026-12-30')
        self.assertTrue(res['success'], res.get('errors'))
        self.assertTrue(res['validation']['is_valid'])
        team_dates = {}
        for m in res['matches']:
            d = date.fromisoformat(m['match_date'])
            for tid in (m['home_team_id'], m['away_team_id']):
                team_dates.setdefault(tid, []).append(d)
        for tid, d_list in team_dates.items():
            d_sorted = sorted(d_list)
            for i in range(1, len(d_sorted)):
                self.assertGreaterEqual((d_sorted[i] - d_sorted[i - 1]).days, 2)

    def test_excluded_dates_never_scheduled(self):
        excl = ['2026-12-03', '2026-12-05']
        res = self._run_gen(6, matches_per_day=2, excluded_dates=excl, end_date='2026-12-20')
        self.assertTrue(res['success'], res.get('errors'))
        scheduled_dates = {m['match_date'] for m in res['matches']}
        for ed in excl:
            self.assertNotIn(ed, scheduled_dates)

    def test_impossible_schedule_rejected_with_explanation(self):
        # 6 teams = 15 matches, at 2/day needs 8 days; give only 4 days
        res = self._run_gen(6, matches_per_day=2, start_date='2026-12-01', end_date='2026-12-04')
        self.assertFalse(res['success'])
        self.assertFalse(res['is_feasible'])
        self.assertGreater(len(res['errors']), 0)

    def test_group_knockout_stages_and_final_separation(self):
        # 8 teams, 2 groups of 4, top 2 qualify -> 12 group + 2 SF + 1 Final = 15 matches
        res = self._run_gen(
            8,
            fmt=TournamentFormat.GROUP_KNOCKOUT,
            num_groups=2,
            qualifiers_per_group=2,
            matches_per_day=2,
            end_date='2026-12-20'
        )
        self.assertTrue(res['success'], res.get('errors'))
        self.assertTrue(res['validation']['is_valid'])
        matches = res['matches']
        self.assertEqual(len(matches), 15)
        group_dates = [m['match_date'] for m in matches if not m['is_knockout']]
        sf_dates = [m['match_date'] for m in matches if m['is_knockout'] and 'Semi' in m['round_name']]
        final_dates = [m['match_date'] for m in matches if m['is_knockout'] and 'Final' in m['round_name'] and 'Semi' not in m['round_name']]
        self.assertEqual(len(sf_dates), 2)
        self.assertEqual(len(final_dates), 1)
        self.assertGreater(min(sf_dates), max(group_dates))
        self.assertGreater(final_dates[0], max(sf_dates))

    def test_manual_edit_revalidation_detects_conflict(self):
        res = self._run_gen(4, matches_per_day=1, end_date='2026-12-20')
        self.assertTrue(res['success'])
        matches = res['matches']
        # Force two matches onto the same date when matches_per_day=1
        matches[1]['match_date'] = matches[0]['match_date']
        report = validate_complete_schedule(matches, {
            'start_date': date(2026, 12, 1),
            'end_date': date(2026, 12, 20),
            'matches_per_day': 1,
            'min_rest_days': 0,
        })
        self.assertFalse(report['is_valid'])
        self.assertGreater(len(report['errors']), 0)

    def test_commit_preserves_locked_and_completed_matches_and_logs_history(self):
        t1, t2, t3, t4 = self.teams[:4]
        # Create one completed match and one locked scheduled match
        completed = Match.objects.create(
            competition=self.comp,
            home_team=t1, away_team=t2,
            match_date=date(2026, 12, 1), kickoff_time=time(15, 0),
            venue='Stadium X', tournament_round='Matchweek 01', round_number=1, leg=1,
            status=MatchStatus.COMPLETED, home_score=2, away_score=1
        )
        locked = Match.objects.create(
            competition=self.comp,
            home_team=t3, away_team=t4,
            match_date=date(2026, 12, 1), kickoff_time=time(17, 30),
            venue='Stadium Y', tournament_round='Matchweek 01', round_number=1, leg=1,
            status=MatchStatus.SCHEDULED, is_locked=True
        )
        res = self._run_gen(4, matches_per_day=2, end_date='2026-12-20')
        self.assertTrue(res['success'], res.get('errors'))
        created = commit_generated_fixtures(
            competition=self.comp,
            matches_data=res['matches'],
            groups_data=res['groups'],
            user=self.user,
            strategy='optimized',
        )
        # Completed and locked matches must still exist!
        self.assertTrue(Match.objects.filter(id=completed.id).exists())
        self.assertTrue(Match.objects.filter(id=locked.id).exists())
        # ScheduleGenerationLog must be recorded
        self.assertEqual(ScheduleGenerationLog.objects.filter(competition=self.comp, is_valid=True).count(), 1)
        self.assertGreater(len(created), 0)
