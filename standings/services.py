from django.db import transaction
from .models import StandingEntry
from matches.models import Match, MatchStatus
from teams.models import Team


def recalculate_competition_standings(competition):
    """
    Recalculates the league / tournament standings for the given competition.
    Points: Win = 3, Draw = 1, Loss = 0.
    Sorting: Points DESC, Goal Difference DESC, Goals For DESC, Team Name ASC.
    Computes Form (last 5 completed matches).
    """
    with transaction.atomic():
        # Get all registered teams
        comp_teams = competition.competitionteam_set.select_related('team', 'group').all()
        if not comp_teams.exists():
            return []

        # Find distinct groups or None
        groups = list(competition.groups.all())
        if not groups:
            groups = [None]

        updated_entries = []

        for group in groups:
            if group is not None:
                group_teams = [ct.team for ct in comp_teams if ct.group_id == group.id]
                matches_qs = competition.matches.filter(group=group, status=MatchStatus.COMPLETED)
            else:
                group_teams = [ct.team for ct in comp_teams]
                matches_qs = competition.matches.filter(status=MatchStatus.COMPLETED)

            # Pre-populate stats dictionary for each team
            stats = {}
            for team in group_teams:
                stats[team.id] = {
                    'team': team,
                    'played': 0,
                    'won': 0,
                    'drawn': 0,
                    'lost': 0,
                    'gf': 0,
                    'ga': 0,
                    'gd': 0,
                    'points': 0,
                    'match_results': []  # chronological results
                }

            # Process all completed matches ordered by date
            ordered_matches = matches_qs.order_by('match_date', 'kickoff_time')
            for match in ordered_matches:
                if match.home_score is None or match.away_score is None:
                    continue

                ht_id = match.home_team_id
                at_id = match.away_team_id

                if ht_id in stats:
                    stats[ht_id]['played'] += 1
                    stats[ht_id]['gf'] += match.home_score
                    stats[ht_id]['ga'] += match.away_score
                if at_id in stats:
                    stats[at_id]['played'] += 1
                    stats[at_id]['gf'] += match.away_score
                    stats[at_id]['ga'] += match.home_score

                if match.home_score > match.away_score:
                    if ht_id in stats:
                        stats[ht_id]['won'] += 1
                        stats[ht_id]['points'] += 3
                        stats[ht_id]['match_results'].append('W')
                    if at_id in stats:
                        stats[at_id]['lost'] += 1
                        stats[at_id]['match_results'].append('L')
                elif match.away_score > match.home_score:
                    if at_id in stats:
                        stats[at_id]['won'] += 1
                        stats[at_id]['points'] += 3
                        stats[at_id]['match_results'].append('W')
                    if ht_id in stats:
                        stats[ht_id]['lost'] += 1
                        stats[ht_id]['match_results'].append('L')
                else:
                    if ht_id in stats:
                        stats[ht_id]['drawn'] += 1
                        stats[ht_id]['points'] += 1
                        stats[ht_id]['match_results'].append('D')
                    if at_id in stats:
                        stats[at_id]['drawn'] += 1
                        stats[at_id]['points'] += 1
                        stats[at_id]['match_results'].append('D')

            # Calculate goal difference
            for item in stats.values():
                item['gd'] = item['gf'] - item['ga']
                # Take last 5 matches for form (most recent last, or most recent first)
                last_5 = item['match_results'][-5:]
                item['form'] = ",".join(last_5)

            # Sort teams by Points DESC, GD DESC, GF DESC, Team name ASC
            sorted_stats = sorted(
                stats.values(),
                key=lambda x: (-x['points'], -x['gd'], -x['gf'], x['team'].name.lower())
            )

            # Save to StandingEntry
            for pos, data in enumerate(sorted_stats, start=1):
                entry, _ = StandingEntry.objects.update_or_create(
                    competition=competition,
                    group=group,
                    team=data['team'],
                    defaults={
                        'position': pos,
                        'played': data['played'],
                        'won': data['won'],
                        'drawn': data['drawn'],
                        'lost': data['lost'],
                        'goals_for': data['gf'],
                        'goals_against': data['ga'],
                        'goal_difference': data['gd'],
                        'points': data['points'],
                        'form': data['form']
                    }
                )
                updated_entries.append(entry)

        # Automatically update competition status when all scheduled matches are completed
        from leagues.models import CompetitionStatus
        total_matches = competition.matches.count()
        if total_matches > 0 and not competition.matches.exclude(status=MatchStatus.COMPLETED).exists():
            if competition.status != CompetitionStatus.COMPLETED:
                competition.status = CompetitionStatus.COMPLETED
                competition.save(update_fields=['status'])
        else:
            if competition.status == CompetitionStatus.COMPLETED:
                competition.status = CompetitionStatus.ACTIVE
                competition.save(update_fields=['status'])

        return updated_entries

