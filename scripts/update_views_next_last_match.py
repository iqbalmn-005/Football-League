import os

path_org = 'leagues/organizer_views.py'
with open(path_org, 'r', encoding='utf-8') as f:
    text_org = f.read()

old_org = """        all_matches = active_competition.matches.all().order_by('round_number', 'match_date', 'kickoff_time')

        standings = StandingEntry.objects.filter(competition=active_competition).select_related('team').order_by('position')"""

new_org = """        all_matches = active_competition.matches.all().order_by('round_number', 'match_date', 'kickoff_time')
        next_match = upcoming_matches.first()
        last_match = completed_matches.first()

        standings = StandingEntry.objects.filter(competition=active_competition).select_related('team').order_by('position')"""

context_org_old = """            'all_matches': all_matches,
            'standings': standings,"""

context_org_new = """            'all_matches': all_matches,
            'next_match': next_match,
            'last_match': last_match,
            'standings': standings,"""

assert old_org in text_org.replace('\r\n', '\n'), "old_org not found"
text_org = text_org.replace('\r\n', '\n')
text_org = text_org.replace(old_org, new_org, 1)
text_org = text_org.replace(context_org_old, context_org_new, 1)

with open(path_org, 'w', encoding='utf-8') as f:
    f.write(text_org)

print("[OK] Updated leagues/organizer_views.py with next_match and last_match")

path_pub = 'leagues/public_views.py'
with open(path_pub, 'r', encoding='utf-8') as f:
    text_pub = f.read()

old_pub = """    completed_matches = competition.matches.filter(
        status=MatchStatus.COMPLETED
    ).order_by('-match_date', '-kickoff_time')

    standings = StandingEntry.objects.filter(competition=competition).select_related('team').order_by('position')"""

new_pub = """    completed_matches = competition.matches.filter(
        status=MatchStatus.COMPLETED
    ).order_by('-match_date', '-kickoff_time')

    next_match = upcoming_matches.first()
    last_match = completed_matches.first()

    standings = StandingEntry.objects.filter(competition=competition).select_related('team').order_by('position')"""

context_pub_old = """        'completed_matches': completed_matches,
        'standings': standings,"""

context_pub_new = """        'completed_matches': completed_matches,
        'next_match': next_match,
        'last_match': last_match,
        'standings': standings,"""

text_pub = text_pub.replace('\r\n', '\n')
assert old_pub in text_pub, "old_pub not found"
text_pub = text_pub.replace(old_pub, new_pub, 1)
text_pub = text_pub.replace(context_pub_old, context_pub_new, 1)

with open(path_pub, 'w', encoding='utf-8') as f:
    f.write(text_pub)

print("[OK] Updated leagues/public_views.py with next_match and last_match")

