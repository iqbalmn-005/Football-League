import os

path_team = 'front/team.html'
with open(path_team, 'r', encoding='utf-8') as f:
    text = f.read().replace('\r\n', '\n')

old_team_up = """                    {% for m in upcoming_matches %}
                    <div style="background:{% if forloop.first %}#f7fee7{% else %}#fafbfa{% endif %};border:{% if forloop.first %}1.5px solid var(--green-dark){% else %}1px solid var(--border){% endif %};border-radius:4px;padding:12px;display:flex;justify-content:space-between;align-items:center;{% if forloop.first %}box-shadow:0 4px 12px rgba(36,93,60,0.12);{% endif %}">
                        <div>
                            <div style="display:flex;align-items:center;gap:6px;margin-bottom:2px;">
                                <span style="font-size:11px;color:var(--muted);">{{ m.tournament_round }} · {{ m.match_date|date:"D, d M" }} @ {{ m.kickoff_time|time:"H:i" }}</span>
                                {% if forloop.first %}
                                <span style="background:#101b16;color:#b4f56b;font-size:9px;font-weight:900;padding:2px 6px;border-radius:3px;box-shadow:0 0 6px rgba(180,245,107,0.35);">⚡ NEXT MATCH</span>
                                {% endif %}
                            </div>"""

new_team_up = """                    {% for m in upcoming_matches %}
                    <div style="background:{% if forloop.first %}#fef2f2{% else %}#fafbfa{% endif %};border:{% if forloop.first %}1.5px solid #dc2626{% else %}1px solid var(--border){% endif %};border-radius:4px;padding:12px;display:flex;justify-content:space-between;align-items:center;{% if forloop.first %}box-shadow:0 4px 12px rgba(220,38,38,0.14);{% endif %}">
                        <div>
                            <div style="display:flex;align-items:center;gap:6px;margin-bottom:2px;">
                                <span style="font-size:11px;color:var(--muted);">{{ m.tournament_round }} · {{ m.match_date|date:"D, d M" }} @ {{ m.kickoff_time|time:"H:i" }}</span>
                                {% if forloop.first %}
                                <span style="background:#dc2626;color:#ffffff;font-size:9px;font-weight:900;padding:2px 6px;border-radius:3px;">⚡ NEXT MATCH</span>
                                {% endif %}
                            </div>"""

if old_team_up in text:
    text = text.replace(old_team_up, new_team_up, 1)
    with open(path_team, 'w', encoding='utf-8') as f:
        f.write(text)
    print("[OK] front/team.html updated with non-green red accent for next match.")
else:
    print("[INFO] old_team_up not matched in front/team.html.")

