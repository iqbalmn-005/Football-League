import os

path_team = 'front/team.html'
with open(path_team, 'r', encoding='utf-8') as f:
    text = f.read().replace('\r\n', '\n')

old_recent = """                    {% for m in recent_matches %}
                    <div style="background:#fafbfa;border:1px solid var(--border);border-radius:4px;padding:12px;display:flex;justify-content:space-between;align-items:center;">
                        <div>
                            <div style="font-size:11px;color:var(--muted);">{{ m.tournament_round }} · {{ m.match_date|date:"d M Y" }}</div>"""

new_recent = """                    {% for m in recent_matches %}
                    <div style="background:{% if forloop.first %}#f0f9ff{% else %}#fafbfa{% endif %};border:{% if forloop.first %}1.5px solid #0284c7{% else %}1px solid var(--border){% endif %};border-radius:4px;padding:12px;display:flex;justify-content:space-between;align-items:center;{% if forloop.first %}box-shadow:0 4px 12px rgba(2,132,199,0.12);{% endif %}">
                        <div>
                            <div style="display:flex;align-items:center;gap:6px;margin-bottom:2px;">
                                <span style="font-size:11px;color:var(--muted);">{{ m.tournament_round }} · {{ m.match_date|date:"d M Y" }}</span>
                                {% if forloop.first %}
                                <span style="background:#0c4a6e;color:#bae6fd;font-size:9px;font-weight:900;padding:2px 6px;border-radius:3px;">🏆 LATEST RESULT</span>
                                {% endif %}
                            </div>"""

old_upcoming = """                    {% for m in upcoming_matches %}
                    <div style="background:#fafbfa;border:1px solid var(--border);border-radius:4px;padding:12px;display:flex;justify-content:space-between;align-items:center;">
                        <div>
                            <div style="font-size:11px;color:var(--muted);">{{ m.tournament_round }} · {{ m.match_date|date:"D, d M" }} @ {{ m.kickoff_time|time:"H:i" }}</div>"""

new_upcoming = """                    {% for m in upcoming_matches %}
                    <div style="background:{% if forloop.first %}#f7fee7{% else %}#fafbfa{% endif %};border:{% if forloop.first %}1.5px solid var(--green-dark){% else %}1px solid var(--border){% endif %};border-radius:4px;padding:12px;display:flex;justify-content:space-between;align-items:center;{% if forloop.first %}box-shadow:0 4px 12px rgba(36,93,60,0.12);{% endif %}">
                        <div>
                            <div style="display:flex;align-items:center;gap:6px;margin-bottom:2px;">
                                <span style="font-size:11px;color:var(--muted);">{{ m.tournament_round }} · {{ m.match_date|date:"D, d M" }} @ {{ m.kickoff_time|time:"H:i" }}</span>
                                {% if forloop.first %}
                                <span style="background:#101b16;color:#b4f56b;font-size:9px;font-weight:900;padding:2px 6px;border-radius:3px;box-shadow:0 0 6px rgba(180,245,107,0.35);">⚡ NEXT MATCH</span>
                                {% endif %}
                            </div>"""

assert old_recent in text, "old_recent not found in team.html"
assert old_upcoming in text, "old_upcoming not found in team.html"

text = text.replace(old_recent, new_recent, 1)
text = text.replace(old_upcoming, new_upcoming, 1)

with open(path_team, 'w', encoding='utf-8') as f:
    f.write(text)

print("[OK] front/team.html updated with fixture and result highlighting.")

