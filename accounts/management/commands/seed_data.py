from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from datetime import date, time, timedelta
from accounts.models import (
    UserProfile, UserRole, OrganizerStatus, OrganizerApplication,
    ActivityLog, Notification, PlatformSetting
)
from leagues.models import (
    Competition, CompetitionType, TournamentFormat,
    CompetitionCategory, CompetitionStatus, CompetitionTeam, CompetitionAssignment
)
from teams.models import Team, Player, PositionChoice
from matches.models import Match, MatchStatus, MatchEvent, MatchEventType
from standings.services import recalculate_competition_standings
from fixtures.services import generate_round_robin_fixtures


class Command(BaseCommand):
    help = "Populate the database with complete demonstration data for TOUCHLINE."

    def handle(self, *args, **options):
        self.stdout.write("Seeding TOUCHLINE platform database...")

        # 1. Platform Settings
        settings_obj = PlatformSetting.get_settings()
        settings_obj.platform_name = "TOUCHLINE"
        settings_obj.tagline = "Your Game. Your League."
        settings_obj.contact_email = "admin@touchline.football"
        settings_obj.allow_organizer_registration = True
        settings_obj.auto_publish_fixtures = True
        settings_obj.save()

        # 2. Users & Roles
        # Super Admin
        admin_user, created = User.objects.get_or_create(username="admin", defaults={
            "email": "admin@touchline.football",
            "first_name": "Super",
            "last_name": "Administrator",
            "is_staff": True,
            "is_superuser": True,
        })
        admin_user.set_password("adminpassword123")
        admin_user.save()
        admin_user.profile.role = UserRole.SUPER_ADMIN
        admin_user.profile.organizer_status = OrganizerStatus.APPROVED
        admin_user.profile.phone = "07700900000"
        admin_user.profile.save()

        # Approved Organizer 1: Sarah Jenkins
        sarah, _ = User.objects.get_or_create(username="sarah.jenkins", defaults={
            "email": "sarah.jenkins@metropolis-fa.org",
            "first_name": "Sarah",
            "last_name": "Jenkins",
        })
        sarah.set_password("organizer123")
        sarah.save()
        sarah.profile.role = UserRole.ORGANIZER
        sarah.profile.organizer_status = OrganizerStatus.APPROVED
        sarah.profile.is_active_organizer = True
        sarah.profile.organization_name = "Metropolis Football Association"
        sarah.profile.experience_years = 6
        sarah.profile.phone = "07700900001"
        sarah.profile.bio = "Senior FA-certified tournament director with over 6 years of community football experience."
        sarah.profile.save()

        # Approved Organizer 2: Viktor Chen
        viktor, _ = User.objects.get_or_create(username="viktor.chen", defaults={
            "email": "viktor@londonyouthsports.co.uk",
            "first_name": "Viktor",
            "last_name": "Chen",
        })
        viktor.set_password("organizer123")
        viktor.save()
        viktor.profile.role = UserRole.ORGANIZER
        viktor.profile.organizer_status = OrganizerStatus.APPROVED
        viktor.profile.is_active_organizer = True
        viktor.profile.organization_name = "London Youth Sports Union"
        viktor.profile.experience_years = 4
        viktor.profile.phone = "07700900002"
        viktor.profile.save()

        # Pending Organizer 3: Marcus Vance
        marcus, _ = User.objects.get_or_create(username="marcus.vance", defaults={
            "email": "m.vance@apexfootball.com",
            "first_name": "Marcus",
            "last_name": "Vance",
        })
        marcus.set_password("organizer123")
        marcus.save()
        marcus.profile.role = UserRole.ORGANIZER
        marcus.profile.organizer_status = OrganizerStatus.PENDING
        marcus.profile.organization_name = "Apex Football Events"
        marcus.profile.experience_years = 3
        marcus.profile.phone = "07700900003"
        marcus.profile.save()

        # Create Pending Organizer Application for Marcus
        OrganizerApplication.objects.get_or_create(
            applicant=marcus,
            defaults={
                "full_name": "Marcus Vance",
                "organization_name": "Apex Football Events",
                "email": "m.vance@apexfootball.com",
                "phone": "07700900003",
                "city": "Manchester",
                "country": "United Kingdom",
                "experience_years": 3,
                "experience_summary": "Managed local corporate weekend leagues and 7-a-side cups for 3 years across Greater Manchester.",
                "proposed_leagues": "Northern Corporate Trophy (12 teams, 7-a-side) and Saturday Autumn Shield.",
                "status": OrganizerApplication.Status.PENDING
            }
        )

        # Rejected Organizer 4: Clara Oswald
        clara, _ = User.objects.get_or_create(username="clara.oswald", defaults={
            "email": "clara@oswaldfc.org",
            "first_name": "Clara",
            "last_name": "Oswald",
        })
        clara.set_password("organizer123")
        clara.save()
        clara.profile.role = UserRole.ORGANIZER
        clara.profile.organizer_status = OrganizerStatus.REJECTED
        clara.profile.organization_name = "Oswald Sports Trust"
        clara.profile.experience_years = 1
        clara.profile.phone = "07700900004"
        clara.profile.rejection_reason = "Insurance liability policy expired and verified venue confirmation not provided."
        clara.profile.save()

        # Create Rejected Application
        OrganizerApplication.objects.get_or_create(
            applicant=clara,
            defaults={
                "full_name": "Clara Oswald",
                "organization_name": "Oswald Sports Trust",
                "email": "clara@oswaldfc.org",
                "phone": "07700900004",
                "city": "Birmingham",
                "country": "United Kingdom",
                "experience_years": 1,
                "experience_summary": "Intending to organize first regional cup.",
                "proposed_leagues": "Midlands Open Cup.",
                "status": OrganizerApplication.Status.REJECTED,
                "rejection_reason": "Insurance liability policy expired and verified venue confirmation not provided.",
                "reviewed_by": admin_user,
            }
        )

        # Viewer User: John Doe
        viewer_user, _ = User.objects.get_or_create(username="viewer", defaults={
            "email": "viewer@touchline.football",
            "first_name": "Alex",
            "last_name": "Taylor",
        })
        viewer_user.set_password("viewer123")
        viewer_user.save()
        viewer_user.profile.role = UserRole.VIEWER
        viewer_user.profile.phone = "07700900099"
        viewer_user.profile.save()

        # 3. Teams and Players
        team_data = [
            {
                "name": "Greenfield FC", "short": "GFC", "manager": "Marcus Bennett",
                "venue": "Greenfield Sports Ground", "email": "contact@greenfieldfc.com", "year": 2018,
                "color": "#17251E",
                "players": [
                    ("Oliver Smith", 1, PositionChoice.GK),
                    ("Harry Jones", 4, PositionChoice.DEF),
                    ("Liam Taylor", 5, PositionChoice.DEF),
                    ("Jack Davies", 3, PositionChoice.DEF),
                    ("Logan Walker", 2, PositionChoice.DEF),
                    ("Noah Brown", 6, PositionChoice.MID),
                    ("James Wilson", 8, PositionChoice.MID),
                    ("Leo Evans", 10, PositionChoice.MID),
                    ("Ethan Brooks", 9, PositionChoice.FWD),
                    ("Lucas Thomas", 11, PositionChoice.FWD),
                    ("Mason Roberts", 7, PositionChoice.FWD),
                ]
            },
            {
                "name": "Riverside FC", "short": "RFC", "manager": "Dominic Vance",
                "venue": "Riverside Arena", "email": "admin@riversidefc.co.uk", "year": 2015,
                "color": "#1F3A2B",
                "players": [
                    ("Daniel Craig", 1, PositionChoice.GK),
                    ("Adam Cole", 4, PositionChoice.DEF),
                    ("Benjamin Hall", 5, PositionChoice.DEF),
                    ("Charles Green", 3, PositionChoice.DEF),
                    ("George Baker", 2, PositionChoice.DEF),
                    ("Henry Young", 6, PositionChoice.MID),
                    ("Samuel King", 8, PositionChoice.MID),
                    ("Matthew Wright", 10, PositionChoice.MID),
                    ("Kai Sterling", 9, PositionChoice.FWD),
                    ("Julian Alvarez", 11, PositionChoice.FWD),
                    ("Tariq Lamptey", 7, PositionChoice.FWD),
                ]
            },
            {
                "name": "United SC", "short": "USC", "manager": "David Miller",
                "venue": "City Park Complex", "email": "info@unitedsc.com", "year": 2020,
                "color": "#2A4736",
                "players": [
                    ("Jordan Pick", 1, PositionChoice.GK),
                    ("Kyle Walker", 2, PositionChoice.DEF),
                    ("John Stones", 5, PositionChoice.DEF),
                    ("Harry Maguire", 6, PositionChoice.DEF),
                    ("Luke Shaw", 3, PositionChoice.DEF),
                    ("Declan Rice", 4, PositionChoice.MID),
                    ("Jude Bellingham", 10, PositionChoice.MID),
                    ("Phil Foden", 8, PositionChoice.MID),
                    ("Bukayo Saka", 7, PositionChoice.FWD),
                    ("Harry Kane", 9, PositionChoice.FWD),
                    ("Marcus Rashford", 11, PositionChoice.FWD),
                ]
            },
            {
                "name": "Falcons FC", "short": "FFC", "manager": "Patrick Vieira",
                "venue": "Falcon Nest Stadium", "email": "team@falconsfc.org", "year": 2019,
                "color": "#14221A",
                "players": [
                    ("Aaron Ramsdale", 1, PositionChoice.GK),
                    ("Ben White", 4, PositionChoice.DEF),
                    ("Gabriel Magalhaes", 6, PositionChoice.DEF),
                    ("William Saliba", 2, PositionChoice.DEF),
                    ("Oleksandr Zinchenko", 3, PositionChoice.DEF),
                    ("Thomas Partey", 5, PositionChoice.MID),
                    ("Martin Odegaard", 8, PositionChoice.MID),
                    ("Emile Smith Rowe", 10, PositionChoice.MID),
                    ("Gabriel Martinelli", 11, PositionChoice.FWD),
                    ("Gabriel Jesus", 9, PositionChoice.FWD),
                    ("Leandro Trossard", 7, PositionChoice.FWD),
                ]
            },
            {
                "name": "City Athletic", "short": "CAT", "manager": "Pep Guardiola",
                "venue": "Etihad Campus Field", "email": "athletics@cityfc.com", "year": 2021,
                "color": "#213629",
                "players": [
                    ("Ederson Moraes", 31, PositionChoice.GK),
                    ("Manuel Akanji", 25, PositionChoice.DEF),
                    ("Ruben Dias", 3, PositionChoice.DEF),
                    ("Nathan Ake", 6, PositionChoice.DEF),
                    ("Josko Gvardiol", 24, PositionChoice.DEF),
                    ("Rodri Hernandez", 16, PositionChoice.MID),
                    ("Kevin De Bruyne", 17, PositionChoice.MID),
                    ("Bernardo Silva", 20, PositionChoice.MID),
                    ("Jack Grealish", 10, PositionChoice.FWD),
                    ("Erling Haaland", 9, PositionChoice.FWD),
                    ("Jeremy Doku", 11, PositionChoice.FWD),
                ]
            },
            {
                "name": "West End Rovers", "short": "WER", "manager": "Unai Emery",
                "venue": "West End Recreation Park", "email": "rovers@westend.co.uk", "year": 2017,
                "color": "#1A2E22",
                "players": [
                    ("Emi Martinez", 1, PositionChoice.GK),
                    ("Ezri Konsa", 4, PositionChoice.DEF),
                    ("Pau Torres", 14, PositionChoice.DEF),
                    ("Lucas Digne", 12, PositionChoice.DEF),
                    ("Matty Cash", 2, PositionChoice.DEF),
                    ("Douglas Luiz", 6, PositionChoice.MID),
                    ("John McGinn", 7, PositionChoice.MID),
                    ("Youri Tielemans", 8, PositionChoice.MID),
                    ("Moussa Diaby", 19, PositionChoice.FWD),
                    ("Ollie Watkins", 11, PositionChoice.FWD),
                    ("Leon Bailey", 31, PositionChoice.FWD),
                ]
            },
            {
                "name": "Apex United", "short": "APX", "manager": "Roberto De Zerbi",
                "venue": "Apex Ground 1", "email": "squad@apexunited.com", "year": 2022,
                "color": "#182C20",
                "players": [
                    ("Bart Verbruggen", 1, PositionChoice.GK),
                    ("Lewis Dunk", 5, PositionChoice.DEF),
                    ("Jan Paul van Hecke", 29, PositionChoice.DEF),
                    ("Pervis Estupinan", 30, PositionChoice.DEF),
                    ("Joel Veltman", 34, PositionChoice.DEF),
                    ("Billy Gilmour", 11, PositionChoice.MID),
                    ("Pascal Gross", 13, PositionChoice.MID),
                    ("Simon Adingra", 24, PositionChoice.MID),
                    ("Kaoru Mitoma", 22, PositionChoice.FWD),
                    ("Danny Welbeck", 18, PositionChoice.FWD),
                    ("Evan Ferguson", 28, PositionChoice.FWD),
                ]
            },
            {
                "name": "Northern Strikers", "short": "NST", "manager": "Eddie Howe",
                "venue": "St. James Pavilion", "email": "strikers@northfc.com", "year": 2016,
                "color": "#253E2F",
                "players": [
                    ("Nick Pope", 22, PositionChoice.GK),
                    ("Kieran Trippier", 2, PositionChoice.DEF),
                    ("Fabian Schar", 5, PositionChoice.DEF),
                    ("Sven Botman", 4, PositionChoice.DEF),
                    ("Dan Burn", 33, PositionChoice.DEF),
                    ("Bruno Guimaraes", 39, PositionChoice.MID),
                    ("Sean Longstaff", 36, PositionChoice.MID),
                    ("Joelinton Cassio", 7, PositionChoice.MID),
                    ("Anthony Gordon", 10, PositionChoice.FWD),
                    ("Alexander Isak", 14, PositionChoice.FWD),
                    ("Callum Wilson", 9, PositionChoice.FWD),
                ]
            },
        ]

        created_teams = []
        for t_info in team_data:
            team, _ = Team.objects.get_or_create(
                name=t_info["name"],
                defaults={
                    "short_name": t_info["short"],
                    "manager_name": t_info["manager"],
                    "home_venue": t_info["venue"],
                    "contact_email": t_info["email"],
                    "contact_phone": "020 7946 0912",
                    "city": "London",
                    "founded_year": t_info["year"],
                    "logo_url": "/static/img/mfl.jpeg",
                    "created_by": sarah
                }
            )
            created_teams.append(team)

            # Players
            for idx, (p_name, p_num, p_pos) in enumerate(t_info["players"], start=1):
                photo_file = f"/static/img/players/p{((idx - 1) % 6) + 1}.jpg"
                player, _ = Player.objects.get_or_create(
                    team=team,
                    jersey_number=p_num,
                    defaults={
                        "full_name": p_name,
                        "position": p_pos,
                        "date_of_birth": date(1998, (idx % 12) + 1, (idx * 2 % 28) + 1),
                        "nationality": "United Kingdom",
                        "photo_url": photo_file,
                        "is_captain": (p_num in [4, 6, 8, 10]),
                    }
                )

        # 4. Competitions
        # Main League: Metropolis Premier League (MFL)
        mfl, _ = Competition.objects.get_or_create(
            name="Metropolis Premier League",
            season="2026/2027",
            defaults={
                "competition_type": CompetitionType.LEAGUE,
                "tournament_format": TournamentFormat.ROUND_ROBIN,
                "category": CompetitionCategory.ELEVEN_A_SIDE,
                "description": "The premier 11-a-side community football division in Greater London.",
                "location": "London, UK",
                "max_teams": 8,
                "primary_organizer": sarah,
                "created_by": sarah,
                "start_date": date(2026, 9, 5),
                "end_date": date(2027, 5, 20),
                "status": CompetitionStatus.ACTIVE,
                "is_published": True,
                "logo_url": "/static/img/mfl.jpeg"
            }
        )

        CompetitionAssignment.objects.get_or_create(
            competition=mfl,
            organizer=sarah,
            defaults={"assigned_by": admin_user, "role": CompetitionAssignment.Role.PRIMARY}
        )

        # Register all 8 teams into MFL
        for team in created_teams:
            CompetitionTeam.objects.get_or_create(competition=mfl, team=team)

        # 5. Saturday Sevens Championship
        sevens, _ = Competition.objects.get_or_create(
            name="Saturday Sevens Championship",
            season="Summer 2027",
            defaults={
                "competition_type": CompetitionType.TOURNAMENT,
                "tournament_format": TournamentFormat.GROUP_KNOCKOUT,
                "category": CompetitionCategory.SEVEN_A_SIDE,
                "description": "High-intensity weekend 7-a-side tournament with group stages and knockout finals.",
                "location": "Manchester, UK",
                "max_teams": 6,
                "primary_organizer": viktor,
                "created_by": viktor,
                "start_date": date(2027, 6, 12),
                "end_date": date(2027, 6, 26),
                "status": CompetitionStatus.UPCOMING,
                "is_published": True,
                "logo_url": "https://images.unsplash.com/photo-1517466787929-bc90951d0974?auto=format&fit=crop&w=900&q=80"
            }
        )
        CompetitionAssignment.objects.get_or_create(
            competition=sevens,
            organizer=viktor,
            defaults={"assigned_by": admin_user, "role": CompetitionAssignment.Role.PRIMARY}
        )
        for team in created_teams[:6]:
            CompetitionTeam.objects.get_or_create(competition=sevens, team=team)

        # 6. Next Gen Youth Cup
        youth, _ = Competition.objects.get_or_create(
            name="Next Gen Invitational Youth Cup",
            season="2027",
            defaults={
                "competition_type": CompetitionType.TOURNAMENT,
                "tournament_format": TournamentFormat.SINGLE_ELIMINATION,
                "category": CompetitionCategory.YOUTH,
                "description": "Under-18 elite youth tournament featuring top grassroots academies.",
                "location": "Birmingham, UK",
                "max_teams": 8,
                "primary_organizer": viktor,
                "created_by": viktor,
                "start_date": date(2027, 7, 10),
                "end_date": date(2027, 7, 18),
                "status": CompetitionStatus.UPCOMING,
                "is_published": True,
                "logo_url": "https://images.unsplash.com/photo-1522778119026-d647f0596c20?auto=format&fit=crop&w=900&q=80"
            }
        )
        for team in created_teams[2:6]:
            CompetitionTeam.objects.get_or_create(competition=youth, team=team)

        # 7. Generate Fixtures for MFL
        if not mfl.matches.exists():
            fixtures = generate_round_robin_fixtures(mfl, start_date=date(2026, 9, 6), double_round=False)
            self.stdout.write(f"Generated {len(fixtures)} fixtures for MFL.")

            # Let's mark the first 2 matchweeks as COMPLETED with scores and events!
            completed_match_configs = [
                # Matchweek 01
                {"home_score": 2, "away_score": 1, "round": "Matchweek 01",
                 "goals": [("Ethan Brooks", "Greenfield FC", 14, False), ("Lucas Thomas", "Greenfield FC", 67, False), ("Kai Sterling", "Riverside FC", 82, True)],
                 "cards": [("Adam Cole", "Riverside FC", "YELLOW_CARD", 35)]},
                {"home_score": 3, "away_score": 0, "round": "Matchweek 01",
                 "goals": [("Harry Kane", "United SC", 23, False), ("Bukayo Saka", "United SC", 55, False), ("Marcus Rashford", "United SC", 89, False)],
                 "cards": [("Ben White", "Falcons FC", "YELLOW_CARD", 42)]},
                {"home_score": 1, "away_score": 1, "round": "Matchweek 01",
                 "goals": [("Erling Haaland", "City Athletic", 38, False), ("Ollie Watkins", "West End Rovers", 74, False)],
                 "cards": []},
                {"home_score": 2, "away_score": 0, "round": "Matchweek 01",
                 "goals": [("Alexander Isak", "Northern Strikers", 19, False), ("Anthony Gordon", "Northern Strikers", 61, False)],
                 "cards": [("Lewis Dunk", "Apex United", "YELLOW_CARD", 51)]},

                # Matchweek 02
                {"home_score": 3, "away_score": 2, "round": "Matchweek 02",
                 "goals": [("Ethan Brooks", "Greenfield FC", 9, False), ("Mason Roberts", "Greenfield FC", 44, False), ("Ethan Brooks", "Greenfield FC", 78, False), ("Harry Kane", "United SC", 33, True), ("Phil Foden", "United SC", 71, False)],
                 "cards": [("Declan Rice", "United SC", "YELLOW_CARD", 60), ("Jack Davies", "Greenfield FC", "YELLOW_CARD", 85)]},
                {"home_score": 1, "away_score": 2, "round": "Matchweek 02",
                 "goals": [("Kai Sterling", "Riverside FC", 50, False), ("Gabriel Jesus", "Falcons FC", 28, False), ("Martin Odegaard", "Falcons FC", 79, False)],
                 "cards": []},
                {"home_score": 4, "away_score": 1, "round": "Matchweek 02",
                 "goals": [("Erling Haaland", "City Athletic", 12, False), ("Erling Haaland", "City Athletic", 41, True), ("Kevin De Bruyne", "City Athletic", 66, False), ("Jeremy Doku", "City Athletic", 83, False), ("Evan Ferguson", "Apex United", 58, False)],
                 "cards": [("Rodri Hernandez", "City Athletic", "YELLOW_CARD", 72)]},
                {"home_score": 0, "away_score": 1, "round": "Matchweek 02",
                 "goals": [("Alexander Isak", "Northern Strikers", 88, False)],
                 "cards": [("John McGinn", "West End Rovers", "RED_CARD", 80)]},
            ]

            mw1_and_2_matches = mfl.matches.filter(tournament_round__in=["Matchweek 01", "Matchweek 02"]).order_by("round_number", "id")

            for idx, match_obj in enumerate(mw1_and_2_matches):
                if idx < len(completed_match_configs):
                    cfg = completed_match_configs[idx]
                    match_obj.home_score = cfg["home_score"]
                    match_obj.away_score = cfg["away_score"]
                    match_obj.status = MatchStatus.COMPLETED
                    match_obj.recorded_by = sarah
                    match_obj.save()

                    # Add goal events
                    for p_name, t_name, minute, is_pen in cfg["goals"]:
                        team = Team.objects.get(name=t_name)
                        player = Player.objects.filter(team=team, full_name=p_name).first()
                        if player:
                            MatchEvent.objects.create(
                                match=match_obj,
                                team=team,
                                player=player,
                                event_type=MatchEventType.PENALTY if is_pen else MatchEventType.GOAL,
                                minute=minute,
                                description=f"Goal scored by #{player.jersey_number} {player.full_name}"
                            )

                    # Add card events
                    for p_name, t_name, c_type, minute in cfg["cards"]:
                        team = Team.objects.get(name=t_name)
                        player = Player.objects.filter(team=team, full_name=p_name).first()
                        if player:
                            MatchEvent.objects.create(
                                match=match_obj,
                                team=team,
                                player=player,
                                event_type=c_type,
                                minute=minute,
                                description=f"{c_type.replace('_', ' ').title()} shown to #{player.jersey_number} {player.full_name}"
                            )

        # 8. Calculate Standings
        recalculate_competition_standings(mfl)
        self.stdout.write("Recalculated standings for MFL.")

        # 9. Activity Logs
        ActivityLog.log("SEED_INIT", "Database populated with initial demo dataset.", user=admin_user)
        ActivityLog.log("APPLICATION_APPROVED", "Super Admin approved organizer application for Sarah Jenkins.", user=admin_user)
        ActivityLog.log("FIXTURES_GENERATED", "Generated round-robin fixtures for Metropolis Premier League.", user=sarah)
        ActivityLog.log("MATCH_RESULT_ENTERED", "Entered score: Greenfield FC 3 - 2 United SC.", user=sarah)

        self.stdout.write(self.style.SUCCESS("TOUCHLINE database seeded successfully!"))

