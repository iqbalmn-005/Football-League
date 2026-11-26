from django.db import transaction
from .models import StandingEntry
from matches.models import Match, MatchStatus
from teams.models import Team
from leagues.models import CompetitionTeam


def recalculate_competition_standings(competition):
    """
    Recalculates the league / tournament standings for the given competition.
    Points: Win = 3, Draw = 1, Loss = 0.
    Sorting: Points DESC, Goal Difference DESC, Goals For DESC, Team Name ASC.
    Computes Form (last 5 completed matches).
    Knockout tournaments do not have a points table; standings entries are cleared.
    """
    if getattr(competition, 'is_pure_knockout', False):
        StandingEntry.objects.filter(competition=competition).delete()
        return []

    with transaction.atomic():
        # Ensure CompetitionTeam.group is kept synchronized with actual group matches
        group_matches = competition.matches.filter(group__isnull=False)
        if group_matches.exists():
            for gm in group_matches.select_related('home_team', 'away_team', 'group'):
                if gm.group_id:
                    if gm.home_team_id:
                        CompetitionTeam.objects.filter(competition=competition, team_id=gm.home_team_id).exclude(group_id=gm.group_id).update(group_id=gm.group_id)
                    if gm.away_team_id:
                        CompetitionTeam.objects.filter(competition=competition, team_id=gm.away_team_id).exclude(group_id=gm.group_id).update(group_id=gm.group_id)

        # Get all registered teams
        comp_teams = competition.competitionteam_set.select_related('team', 'group').all()
        if not comp_teams.exists():
            return []

        # Only treat competition as group-staged if it is GROUP_KNOCKOUT or actually has group-linked matches
        groups = list(competition.groups.all())
        use_groups = bool(
            groups
            and (
                getattr(competition, 'is_group_stage', False)
                or competition.matches.filter(group__isnull=False).exists()
            )
        )
        if use_groups:
            # Clean up stale entries:
            # 1. Any entry where group is None when groups exist
            StandingEntry.objects.filter(competition=competition, group__isnull=True).delete()
            # 2. Any entry where group does not belong to this competition's current groups
            StandingEntry.objects.filter(competition=competition).exclude(group__in=groups).delete()
            # 3. For each group, delete any StandingEntry for teams not currently assigned to that group
            for grp in groups:
                grp_team_ids = [ct.team_id for ct in comp_teams if ct.group_id == grp.id]
                StandingEntry.objects.filter(competition=competition, group=grp).exclude(team_id__in=grp_team_ids).delete()
        else:
            groups = [None]
            # Clean up stale entries with a group when competition is single-table
            StandingEntry.objects.filter(competition=competition, group__isnull=False).delete()
            reg_team_ids = [ct.team_id for ct in comp_teams]
            StandingEntry.objects.filter(competition=competition).exclude(team_id__in=reg_team_ids).delete()

        updated_entries = []

        for group in groups:
            if group is not None:
                group_teams = [ct.team for ct in comp_teams if ct.group_id == group.id]
                matches_qs = competition.matches.filter(group=group, status=MatchStatus.COMPLETED)
                # Safeguard: ensure all teams that have completed matches in this group are included in group_teams
                match_team_ids = set(matches_qs.values_list('home_team_id', flat=True)) | set(matches_qs.values_list('away_team_id', flat=True))
                match_team_ids.discard(None)
                existing_team_ids = {t.id for t in group_teams}
                missing_team_ids = match_team_ids - existing_team_ids
                if missing_team_ids:
                    missing_teams = list(Team.objects.filter(id__in=missing_team_ids))
                    group_teams.extend(missing_teams)
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
            is_league_ko = (getattr(competition, 'tournament_format', '') == 'LEAGUE_KNOCKOUT')
            for match in ordered_matches:
                if group is None and is_league_ko and match.is_knockout:
                    continue
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

