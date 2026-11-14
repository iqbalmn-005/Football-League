from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.models import User
from django.utils import timezone
from django.db.models import Q
from datetime import datetime, date, time

from accounts.decorators import approved_organizer_required
from accounts.models import ActivityLog, Notification, UserProfile, UserRole, OrganizerStatus, OrganizerApplication
from leagues.models import Competition, CompetitionAssignment, CompetitionTeam, TournamentGroup, CompetitionStatus
from teams.models import Team, Player, PositionChoice
from matches.models import Match, MatchEvent, MatchEventType, MatchStatus
from standings.models import StandingEntry
from standings.services import recalculate_competition_standings
from fixtures.services import generate_round_robin_fixtures, advance_knockout_bracket
from matches.services import get_competition_statistics
from teams.views import delete_team_view


def get_organizer_competitions(user):
    """
    Returns all competitions this organizer is assigned to or created.
    Super admins see all competitions.
    """
    if user.is_superuser or (hasattr(user, 'profile') and user.profile.is_super_admin):
        return Competition.objects.all().order_by('-created_at')

    assigned_comp_ids = CompetitionAssignment.objects.filter(organizer=user).values_list('competition_id', flat=True)
    return Competition.objects.filter(
        Q(id__in=assigned_comp_ids) | Q(primary_organizer=user) | Q(created_by=user)
    ).distinct().order_by('-created_at')


@approved_organizer_required
def organizer_dashboard(request, comp_id=None):
    if request.user.is_superuser or (hasattr(request.user, 'profile') and request.user.profile.is_super_admin):
        if comp_id:
            messages.info(request, "Administrators have oversight access only and cannot edit tournament fixtures, teams, or players.")
            return redirect(f"/competition/{comp_id}/")
        return redirect('/super-admin/?tab=leagues')

    user_competitions = get_organizer_competitions(request.user)

    if comp_id:
        active_competition = get_object_or_404(Competition, id=comp_id)
        # Check permission unless super admin
        if not (request.user.is_superuser or (hasattr(request.user, 'profile') and request.user.profile.is_super_admin)):
            if active_competition not in user_competitions:
                messages.error(request, "You do not have permission to manage this competition.")
                return redirect('organizer_dashboard')
            if active_competition.status == CompetitionStatus.PENDING:
                messages.warning(request, f"'{active_competition.name}' is currently under review by platform administrators. Management tools will unlock once approved.")
                return redirect('organizer_dashboard')

        if request.method == 'POST':
            return update_competition_view(request, comp_id)

        tab = request.GET.get('tab', 'overview')

        # Data for the active competition
        comp_teams = active_competition.teams.all().prefetch_related('players')
        upcoming_matches = active_competition.matches.filter(
            status__in=[MatchStatus.SCHEDULED, MatchStatus.LIVE, MatchStatus.POSTPONED]
        ).select_related('home_team', 'away_team', 'group').order_by('match_date', 'kickoff_time')
        completed_matches = active_competition.matches.filter(
            status=MatchStatus.COMPLETED
        ).select_related('home_team', 'away_team', 'group').prefetch_related(
            'events', 'events__player', 'events__team'
        ).order_by('-match_date', '-kickoff_time')
        all_matches = active_competition.matches.all().select_related('home_team', 'away_team', 'group').order_by('round_number', 'match_date', 'kickoff_time')
        next_match = upcoming_matches.first()
        last_match = completed_matches.first()

        if active_competition.is_pure_knockout:
            standings = []
            if tab == 'standings':
                tab = 'fixtures'
        else:
            standings = StandingEntry.objects.filter(competition=active_competition).select_related('team').order_by('position')
        stats = get_competition_statistics(active_competition)
        all_players = Player.objects.filter(team__in=comp_teams).select_related('team')
        groups = active_competition.groups.all()

        # Eligible co-organizers to invite
        co_organizers = User.objects.filter(
            profile__role=UserRole.ORGANIZER,
            profile__organizer_status=OrganizerStatus.APPROVED
        ).exclude(id=request.user.id)

        # Activity logs for this competition
        logs = ActivityLog.objects.filter(details__icontains=active_competition.name).order_by('-created_at')[:20]

        context = {
            'has_competitions': True,
            'user_competitions': user_competitions,
            'active_competition': active_competition,
            'active_tab': tab,
            'comp_teams': comp_teams,
            'upcoming_matches': upcoming_matches,
            'completed_matches': completed_matches,
            'all_matches': all_matches,
            'next_match': next_match,
            'last_match': last_match,
            'standings': standings,
            'stats': stats,
            'all_players': all_players,
            'groups': groups,
            'co_organizers': co_organizers,
            'logs': logs,
        }
        return render(request, 'organizer_index.html', context)

    # Hub view: Render organizer.html when organizer logs in or accesses /organizer/
    search_q = request.GET.get('q', '').strip()
    status_f = request.GET.get('status', 'all').strip()

    filtered_competitions = user_competitions
    if search_q:
        filtered_competitions = filtered_competitions.filter(
            Q(name__icontains=search_q) | Q(location__icontains=search_q) | Q(season__icontains=search_q)
        )
    if status_f and status_f != 'all':
        filtered_competitions = filtered_competitions.filter(status=status_f)

    total_count = user_competitions.count()
    active_count = user_competitions.filter(status=CompetitionStatus.ACTIVE).count()
    upcoming_count = user_competitions.filter(status=CompetitionStatus.UPCOMING).count()
    completed_count = user_competitions.filter(status=CompetitionStatus.COMPLETED).count()
    pending_count = user_competitions.filter(status=CompetitionStatus.PENDING).count()
    total_teams = sum(c.teams.count() for c in user_competitions)

    context = {
        'user_competitions': filtered_competitions,
        'search_query': search_q,
        'status_filter': status_f,
        'total_count': total_count,
        'active_count': active_count,
        'ongoing_count': active_count,
        'completed_count': completed_count,
        'upcoming_count': upcoming_count,
        'pending_count': pending_count,
        'total_teams': total_teams,
    }
    return render(request, 'organizer.html', context)


@approved_organizer_required
def organizer_create_competition(request):
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        comp_type = request.POST.get('competition_type', 'LEAGUE')
        tourn_format = request.POST.get('tournament_format', 'ROUND_ROBIN')
        category = request.POST.get('category', '11-a-side')
        season = request.POST.get('season', '2026/2027').strip()
        location = request.POST.get('location', 'London, UK').strip()
        max_teams_raw = request.POST.get('max_teams', '8')
        if max_teams_raw == 'custom':
            max_teams_raw = request.POST.get('custom_teams', '8')
        try:
            max_teams = int(max_teams_raw or 8)
        except (ValueError, TypeError):
            max_teams = 8

        description = request.POST.get('description', '').strip()
        organization_name = request.POST.get('organization_name', '').strip()
        start_date = request.POST.get('start_date') or None
        end_date = request.POST.get('end_date') or None
        logo_url = request.POST.get('logo_url', '').strip()
        et_raw = request.POST.get('extra_time_before_penalties', '0')
        extra_time_before_penalties = et_raw in ['1', 'on', 'true', 'True', 'enabled', 'ENABLED']

        if not name:
            messages.error(request, "Competition name is required.")
            return redirect('organizer_dashboard')

        # Super admin creations are active immediately; organizer creations go under review
        is_admin = request.user.is_superuser or (hasattr(request.user, 'profile') and request.user.profile.is_super_admin)
        comp_status = CompetitionStatus.ACTIVE if is_admin else CompetitionStatus.PENDING
        is_published = True if is_admin else False

        comp = Competition.objects.create(
            name=name,
            competition_type=comp_type,
            tournament_format=tourn_format,
            category=category,
            season=season,
            location=location,
            max_teams=max_teams,
            description=description,
            primary_organizer=request.user,
            created_by=request.user,
            start_date=start_date,
            end_date=end_date,
            logo_url=logo_url,
            extra_time_before_penalties=extra_time_before_penalties,
            status=comp_status,
            is_published=is_published
        )

        if 'logo' in request.FILES:
            comp.logo = request.FILES['logo']
            comp.save()

        CompetitionAssignment.objects.create(
            competition=comp,
            organizer=request.user,
            assigned_by=request.user,
            role=CompetitionAssignment.Role.PRIMARY,
            can_edit_fixtures=True,
            can_enter_results=True,
            can_manage_teams=True,
            can_invite_organizers=True
        )

        # Create or update organizer application for Super Admin review
        org_name = organization_name or getattr(request.user.profile, 'organization_name', '') or f"{name} Committee"
        app = OrganizerApplication.objects.filter(applicant=request.user, status=OrganizerApplication.Status.PENDING).first()
        if not app:
            OrganizerApplication.objects.create(
                applicant=request.user,
                full_name=request.user.get_full_name() or request.user.username,
                organization_name=org_name,
                email=request.user.email or f"{request.user.username}@touchline.local",
                phone=getattr(request.user.profile, 'phone', '') or request.user.username,
                city=location,
                country="United Kingdom",
                experience_years=getattr(request.user.profile, 'experience_years', 1) or 1,
                experience_summary=description or f"Organizer for {name}",
                proposed_leagues=f"League: {name} ({category}, {max_teams} teams, Venue: {location})",
                status=OrganizerApplication.Status.PENDING
            )
        else:
            app.organization_name = org_name
            app.proposed_leagues = (app.proposed_leagues + f"\nLeague: {name} ({category}, {max_teams} teams)").strip()
            app.save()

        if hasattr(request.user, 'profile'):
            profile = request.user.profile
            if profile.organizer_status != OrganizerStatus.APPROVED:
                profile.organization_name = org_name
                profile.organizer_status = OrganizerStatus.PENDING
                profile.save()

        ActivityLog.log('LEAGUE_SUBMITTED', f"Organizer {request.user.username} submitted league '{name}' for review.", user=request.user)

        if comp_status == CompetitionStatus.PENDING:
            messages.success(request, f"League '{name}' submitted successfully! It is now under review by platform administrators. You can track its status on your dashboard.")
            return redirect('organizer_dashboard')
        else:
            messages.success(request, f"Competition '{name}' created and activated successfully!")
            return redirect(f"/organizer/{comp.id}/")
    return redirect('organizer_dashboard')


@approved_organizer_required
def generate_fixtures_view(request, comp_id):
    if request.user.is_superuser or (hasattr(request.user, 'profile') and request.user.profile.is_super_admin):
        messages.error(request, "Administrators have oversight access only and cannot edit tournament fixtures, teams, or players.")
        return redirect(f"/competition/{comp_id}/")
    if request.method == 'POST':
        competition = get_object_or_404(Competition, id=comp_id)
        teams_count = competition.teams.count()
        if teams_count < 2:
            messages.error(request, "Need at least 2 teams registered to generate fixtures.")
            return redirect(f"/organizer/{comp_id}/?tab=fixtures")

        double_round = 'double_round' in request.POST
        created_matches = generate_round_robin_fixtures(competition, double_round=double_round)

        # Initial standings table creation with 0s
        recalculate_competition_standings(competition)

        ActivityLog.log(
            'FIXTURES_GENERATED',
            f"Generated {len(created_matches)} fixtures for '{competition.name}'.",
            user=request.user
        )
        messages.success(request, f"Generated {len(created_matches)} fixtures successfully!")
    return redirect(f"/organizer/{comp_id}/?tab=fixtures")


@approved_organizer_required
def add_fixture_view(request, comp_id):
    if request.user.is_superuser or (hasattr(request.user, 'profile') and request.user.profile.is_super_admin):
        messages.error(request, "Administrators have oversight access only and cannot edit tournament fixtures, teams, or players.")
        return redirect(f"/competition/{comp_id}/")
    if request.method == 'POST':
        competition = get_object_or_404(Competition, id=comp_id)
        home_team_id = request.POST.get('home_team_id')
        away_team_id = request.POST.get('away_team_id')
        match_date_str = request.POST.get('match_date')
        kickoff_time_str = request.POST.get('kickoff_time', '15:00')
        venue = request.POST.get('venue', 'Central Stadium').strip()
        round_name = request.POST.get('tournament_round', 'Matchweek 1').strip()
        round_number = int(request.POST.get('round_number', 1) or 1)

        if home_team_id == away_team_id:
            messages.error(request, "Home team and Away team cannot be the same.")
            return redirect(f"/organizer/{comp_id}/?tab=fixtures")

        home_team = get_object_or_404(Team, id=home_team_id)
        away_team = get_object_or_404(Team, id=away_team_id)

        try:
            m_date = datetime.strptime(match_date_str, '%Y-%m-%d').date()
        except Exception:
            m_date = date.today()

        try:
            k_time = datetime.strptime(kickoff_time_str, '%H:%M').time()
        except Exception:
            k_time = time(15, 0)

        match_obj = Match.objects.create(
            competition=competition,
            tournament_round=round_name,
            round_number=round_number,
            home_team=home_team,
            away_team=away_team,
            match_date=m_date,
            kickoff_time=k_time,
            venue=venue or getattr(home_team, 'home_venue', '') or "Central Stadium",
            status=MatchStatus.SCHEDULED
        )

        ActivityLog.log('FIXTURE_ADDED', f"Added fixture: {home_team.name} vs {away_team.name} ({round_name}).", user=request.user)
        messages.success(request, f"Fixture {home_team.short_name} vs {away_team.short_name} added!")
    return redirect(f"/organizer/{comp_id}/?tab=fixtures")


@approved_organizer_required
def update_match_view(request, match_id):
    match_obj = get_object_or_404(Match, id=match_id)
    comp_id = match_obj.competition_id
    if request.user.is_superuser or (hasattr(request.user, 'profile') and request.user.profile.is_super_admin):
        messages.error(request, "Administrators have oversight access only and cannot edit tournament fixtures, teams, or players.")
        return redirect(f"/competition/{comp_id}/")
    if request.method == 'POST':
        comp_id = match_obj.competition_id

        match_date_str = request.POST.get('match_date')
        kickoff_time_str = request.POST.get('kickoff_time')
        venue = request.POST.get('venue', '').strip()
        status = request.POST.get('status', match_obj.status)
        tournament_round = request.POST.get('tournament_round', match_obj.tournament_round)

        if match_date_str:
            try:
                match_obj.match_date = datetime.strptime(match_date_str, '%Y-%m-%d').date()
            except Exception:
                pass

        if kickoff_time_str:
            try:
                match_obj.kickoff_time = datetime.strptime(kickoff_time_str, '%H:%M').time()
            except Exception:
                pass

        if venue:
            match_obj.venue = venue

        match_obj.status = status
        match_obj.tournament_round = tournament_round
        match_obj.save()

        # Recalculate standings in case status changed
        recalculate_competition_standings(match_obj.competition)

        ActivityLog.log('MATCH_UPDATED', f"Updated match {match_obj}.", user=request.user)
        messages.success(request, f"Match {match_obj} updated successfully!")
        return redirect(f"/organizer/{comp_id}/?tab=fixtures")
    return redirect('organizer_dashboard')


@approved_organizer_required
def enter_match_result_view(request, match_id):
    match_obj = get_object_or_404(Match, id=match_id)
    comp_id = match_obj.competition_id
    if request.user.is_superuser or (hasattr(request.user, 'profile') and request.user.profile.is_super_admin):
        messages.error(request, "Administrators have oversight access only and cannot edit tournament fixtures, teams, or players.")
        return redirect(f"/competition/{comp_id}/")

    if not match_obj.home_team or not match_obj.away_team:
        messages.error(request, "Cannot record results for a match where participating teams are not yet determined.")
        return redirect(f"/organizer/{comp_id}/?tab=fixtures")

    if request.method == 'POST':
        comp_id = match_obj.competition_id

        home_score = int(request.POST.get('home_score', 0))
        away_score = int(request.POST.get('away_score', 0))
        status = request.POST.get('status', MatchStatus.COMPLETED)

        match_obj.home_score = home_score
        match_obj.away_score = away_score
        match_obj.status = status
        match_obj.recorded_by = request.user
        match_obj.save()

        # Goal events recording
        home_scorers_text = request.POST.get('home_scorers', '').strip()
        away_scorers_text = request.POST.get('away_scorers', '').strip()

        # Parse and save goals if specified
        # Format example: "John Doe 12', Alex Smith 45'(P)"
        def parse_and_record_scorers(scorers_str, team, opp_team):
            if not scorers_str:
                return
            items = [item.strip() for item in scorers_str.split(',') if item.strip()]
            for item in items:
                # e.g. "Brooks 14'"
                parts = item.split()
                if not parts:
                    continue
                min_part = parts[-1].replace("'", "").replace("min", "")
                name_part = " ".join(parts[:-1]) if len(parts) > 1 else parts[0]

                is_pen = '(P)' in item.upper() or '(PEN)' in item.upper()
                name_part = name_part.replace('(P)', '').replace('(p)', '').replace('(PEN)', '').replace('(pen)', '').strip()

                try:
                    minute = int("".join(filter(str.isdigit, min_part))) or 45
                except Exception:
                    minute = 45

                # Find player or create
                player = Player.objects.filter(team=team, full_name__icontains=name_part).first()
                if not player:
                    player = Player.objects.filter(team=team).first()

                if player:
                    MatchEvent.objects.create(
                        match=match_obj,
                        team=team,
                        player=player,
                        event_type=MatchEventType.PENALTY if is_pen else MatchEventType.GOAL,
                        minute=min(minute, 120),
                        description=f"Goal by {player.full_name}"
                    )

        # Clear existing goal events for this match before re-populating if requested
        if 'reset_events' in request.POST:
            match_obj.events.all().delete()

        parse_and_record_scorers(home_scorers_text, match_obj.home_team, match_obj.away_team)
        parse_and_record_scorers(away_scorers_text, match_obj.away_team, match_obj.home_team)

        # Clean sheet events recording
        if away_score == 0:
            home_gks = list(match_obj.home_team.players.filter(position=PositionChoice.GK))
            home_cs_keeper_id = request.POST.get('home_clean_sheet_keeper')
            keeper = None
            if home_cs_keeper_id:
                try:
                    keeper = match_obj.home_team.players.get(id=int(home_cs_keeper_id))
                except (ValueError, Player.DoesNotExist):
                    keeper = None
            if not keeper and len(home_gks) == 1:
                keeper = home_gks[0]
            if keeper:
                MatchEvent.objects.create(
                    match=match_obj,
                    team=match_obj.home_team,
                    player=keeper,
                    event_type=MatchEventType.CLEAN_SHEET,
                    minute=90,
                    description=f"Clean sheet kept by {keeper.full_name}"
                )

        if home_score == 0:
            away_gks = list(match_obj.away_team.players.filter(position=PositionChoice.GK))
            away_cs_keeper_id = request.POST.get('away_clean_sheet_keeper')
            keeper = None
            if away_cs_keeper_id:
                try:
                    keeper = match_obj.away_team.players.get(id=int(away_cs_keeper_id))
                except (ValueError, Player.DoesNotExist):
                    keeper = None
            if not keeper and len(away_gks) == 1:
                keeper = away_gks[0]
            if keeper:
                MatchEvent.objects.create(
                    match=match_obj,
                    team=match_obj.away_team,
                    player=keeper,
                    event_type=MatchEventType.CLEAN_SHEET,
                    minute=90,
                    description=f"Clean sheet kept by {keeper.full_name}"
                )

        # Automatically recalculate standings!
        recalculate_competition_standings(match_obj.competition)

        # Automatically advance knockout brackets
        advance_knockout_bracket(match_obj.competition)

        ActivityLog.log(
            'MATCH_RESULT_ENTERED',
            f"Entered result: {match_obj.home_display_name} {home_score}-{away_score} {match_obj.away_display_name}.",
            user=request.user
        )

        messages.success(request, f"Result recorded: {match_obj.home_display_name} {home_score} - {away_score} {match_obj.away_display_name}. Points table updated!")
        return redirect(f"/organizer/{comp_id}/?tab=fixtures")
    return redirect('organizer_dashboard')


@approved_organizer_required
def add_team_view(request, comp_id):
    if request.user.is_superuser or (hasattr(request.user, 'profile') and request.user.profile.is_super_admin):
        messages.error(request, "Administrators have oversight access only and cannot edit tournament fixtures, teams, or players.")
        return redirect(f"/competition/{comp_id}/")
    if request.method == 'POST':
        competition = get_object_or_404(Competition, id=comp_id)

        team_name = request.POST.get('name', '').strip()
        short_name = request.POST.get('short_name', '').strip()
        manager_name = request.POST.get('manager_name', '').strip()
        contact_email = request.POST.get('contact_email', '').strip()
        contact_phone = request.POST.get('contact_phone', '').strip()
        home_venue = request.POST.get('home_venue', '').strip()
        city = request.POST.get('city', 'London').strip()
        group_id = request.POST.get('group_id')
        logo_url = request.POST.get('logo_url', '').strip()

        if not team_name:
            messages.error(request, "Team name is required.")
            return redirect(f"/organizer/{comp_id}/?tab=teams")

        # Get or create team using valid Team model fields
        team = Team.objects.filter(name__iexact=team_name).first()
        created = False
        if not team:
            create_kwargs = {
                'name': team_name,
                'short_name': short_name or team_name[:3].upper(),
                'manager_name': manager_name,
                'created_by': request.user
            }
            if contact_phone:
                create_kwargs['contact_phone'] = contact_phone
            team = Team.objects.create(**create_kwargs)
            created = True

        if 'logo' in request.FILES and request.FILES['logo']:
            team.logo = request.FILES['logo']
            team.save()

        # Associate team to this competition
        group_obj = None
        if group_id:
            group_obj = TournamentGroup.objects.filter(id=group_id, competition=competition).first()

        ct, ct_created = CompetitionTeam.objects.get_or_create(
            competition=competition,
            team=team,
            defaults={'group': group_obj}
        )

        # Add default squad players if this is a newly created team
        if created:
            default_players = [
                ("Oliver Smith", 1, "GK"),
                ("Harry Jones", 4, "DEF"),
                ("Liam Taylor", 5, "DEF"),
                ("Jack Davies", 3, "DEF"),
                ("Noah Brown", 6, "MID"),
                ("James Wilson", 8, "MID"),
                ("Leo Evans", 10, "MID"),
                ("Ethan Brooks", 9, "FWD"),
                ("Lucas Thomas", 11, "FWD"),
                ("Mason Roberts", 7, "FWD"),
                ("Logan Walker", 2, "DEF"),
            ]
            for pname, pnum, ppos in default_players:
                Player.objects.create(
                    team=team,
                    full_name=pname,
                    jersey_number=pnum,
                    position=ppos,
                    photo_url=f"/static/img/players/p{(pnum % 6) + 1}.jpg"
                )

        # Recalculate standings so team appears in table
        recalculate_competition_standings(competition)

        ActivityLog.log('TEAM_ADDED', f"Added team '{team.name}' to competition '{competition.name}'.", user=request.user)
        messages.success(request, f"Team '{team.name}' added to {competition.name}!")
    return redirect(f"/organizer/{comp_id}/?tab=teams")


@approved_organizer_required
def add_player_view(request, team_id):
    comp_id = request.POST.get('comp_id')
    if request.user.is_superuser or (hasattr(request.user, 'profile') and request.user.profile.is_super_admin):
        messages.error(request, "Administrators have oversight access only and cannot edit tournament fixtures, teams, or players.")
        return redirect(f"/competition/{comp_id}/" if comp_id else '/super-admin/?tab=leagues')
    if request.method == 'POST':
        team = get_object_or_404(Team, id=team_id)
        comp_id = request.POST.get('comp_id')

        full_name = request.POST.get('full_name', '').strip()
        jersey_number = int(request.POST.get('jersey_number', 0))
        position = request.POST.get('position', '').strip()
        dob_str = request.POST.get('date_of_birth')
        nationality = request.POST.get('nationality', 'United Kingdom').strip()
        photo_url = request.POST.get('photo_url', '').strip()

        if not full_name or jersey_number <= 0:
            messages.error(request, "Player name and positive jersey number are required.")
            return redirect(f"/organizer/{comp_id}/?tab=teams" if comp_id else 'organizer_dashboard')

        if not position:
            messages.error(request, "Please select a player position.")
            return redirect(f"/organizer/{comp_id}/?tab=teams" if comp_id else 'organizer_dashboard')

        if Player.objects.filter(team=team, jersey_number=jersey_number).exists():
            messages.error(request, f"Jersey #{jersey_number} is already taken in {team.name}. Player not submitted.")
            return redirect(f"/organizer/{comp_id}/?tab=teams" if comp_id else 'organizer_dashboard')

        dob = None
        if dob_str:
            try:
                dob = datetime.strptime(dob_str, '%Y-%m-%d').date()
            except Exception:
                pass

        player = Player.objects.create(
            team=team,
            full_name=full_name,
            jersey_number=jersey_number,
            position=position,
            date_of_birth=dob,
            nationality=nationality,
            photo_url=photo_url or f"/static/img/players/p{(jersey_number % 6) + 1}.jpg"
        )

        if 'photo' in request.FILES:
            player.photo = request.FILES['photo']
            player.save()

        ActivityLog.log('PLAYER_ADDED', f"Added player #{jersey_number} {full_name} to {team.name}.", user=request.user)
        messages.success(request, f"Player #{jersey_number} {full_name} added to {team.name}!")
        return redirect(f"/organizer/{comp_id}/?tab=teams" if comp_id else 'organizer_dashboard')
    return redirect('organizer_dashboard')


@approved_organizer_required
def recalculate_standings_view(request, comp_id):
    competition = get_object_or_404(Competition, id=comp_id)
    if competition.is_pure_knockout:
        StandingEntry.objects.filter(competition=competition).delete()
        messages.info(request, f"{competition.name} is a knockout tournament; points table is not applicable.")
        return redirect(f"/organizer/{comp_id}/?tab=fixtures")
    if request.method == 'POST':
        recalculate_competition_standings(competition)
        messages.success(request, f"Points table and goal difference recalculated for {competition.name}!")
    return redirect(f"/organizer/{comp_id}/?tab=standings")


@approved_organizer_required
def invite_co_organizer_view(request, comp_id):
    if request.method == 'POST':
        competition = get_object_or_404(Competition, id=comp_id)
        organizer_id = request.POST.get('organizer_id')
        co_organizer = get_object_or_404(User, id=organizer_id)

        CompetitionAssignment.objects.update_or_create(
            competition=competition,
            organizer=co_organizer,
            defaults={
                'assigned_by': request.user,
                'role': CompetitionAssignment.Role.CO_ORGANIZER,
                'can_edit_fixtures': True,
                'can_enter_results': True,
                'can_manage_teams': True,
                'can_invite_organizers': False
            }
        )

        ActivityLog.log(
            'ORGANIZER_INVITED',
            f"{request.user.username} invited {co_organizer.username} to co-organize '{competition.name}'.",
            user=request.user
        )

        Notification.objects.create(
            recipient=co_organizer,
            title="Co-Organizer Invitation",
            message=f"{request.user.username} added you as a Co-Organizer for '{competition.name}'.",
            notification_type="COMPETITION",
            link=f"/organizer/{competition.id}/"
        )

        messages.success(request, f"{co_organizer.username} added as co-organizer for {competition.name}!")
    return redirect(f"/organizer/{comp_id}/?tab=overview")


@approved_organizer_required
def update_competition_view(request, comp_id):
    if request.user.is_superuser or (hasattr(request.user, 'profile') and request.user.profile.is_super_admin):
        messages.error(request, "Administrators have oversight access only and cannot edit league details directly.")
        return redirect(f"/competition/{comp_id}/")
    competition = get_object_or_404(Competition, id=comp_id)
    user_comps = get_organizer_competitions(request.user)
    if not (request.user.is_superuser or competition in user_comps):
        messages.error(request, "Permission denied to update this competition.")
        return redirect('organizer_dashboard')

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        location = request.POST.get('location', '').strip()
        season = request.POST.get('season', '').strip()
        category = request.POST.get('category', '').strip()
        description = request.POST.get('description', '').strip()
        logo_url = request.POST.get('logo_url', '').strip()

        if name:
            competition.name = name
        if location:
            competition.location = location
        if season:
            competition.season = season
        if category:
            competition.category = category
        if description is not None:
            competition.description = description
        if 'extra_time_before_penalties' in request.POST:
            et_val = request.POST.get('extra_time_before_penalties')
            competition.extra_time_before_penalties = et_val in ['1', 'on', 'true', 'True', 'enabled', 'ENABLED']

        if 'logo' in request.FILES:
            competition.logo = request.FILES['logo']
            competition.logo_url = ""
        elif logo_url:
            competition.logo_url = logo_url

        competition.save()

        # Also update organizer user/profile fields if provided in request
        org_user = competition.primary_organizer or competition.created_by
        if org_user:
            profile = getattr(org_user, 'profile', None)
            if 'organization_name' in request.POST and profile:
                profile.organization_name = request.POST.get('organization_name', '').strip()
                profile.save()
            if 'phone' in request.POST and profile:
                profile.phone = request.POST.get('phone', '').strip()
                profile.save()
            if 'email' in request.POST:
                org_user.email = request.POST.get('email', '').strip()
                org_user.save()
            if 'full_name' in request.POST or 'organizer_name' in request.POST:
                fname = (request.POST.get('full_name') or request.POST.get('organizer_name') or '').strip()
                if fname:
                    parts = fname.split(None, 1)
                    org_user.first_name = parts[0]
                    org_user.last_name = parts[1] if len(parts) > 1 else ""
                    org_user.save()

        ActivityLog.log('LEAGUE_UPDATED', f"Organizer {request.user.username} updated league '{competition.name}'.", user=request.user)
        messages.success(request, "Organizer details updated successfully!")
        return redirect('/organizer/')
    return redirect('/organizer/')


