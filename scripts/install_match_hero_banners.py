import os

path_org = 'front/organizer_index.html'
with open(path_org, 'r', encoding='utf-8') as f:
    text_org = f.read().replace('\r\n', '\n')

# 1. Add CSS for match banner crests in organizer_index.html
extra_css = """
        .match-banner-crests {
            display: flex;
            align-items: center;
            gap: 10px;
            flex-shrink: 0;
        }

        .match-vs-badge {
            font-family: var(--font-heading);
            font-size: 13px;
            font-weight: 900;
            color: var(--green);
            background: rgba(180, 245, 107, 0.15);
            padding: 4px 8px;
            border-radius: 6px;
            border: 1px solid rgba(180, 245, 107, 0.35);
            letter-spacing: 0.5px;
        }

        .banner-score-display {
            display: flex;
            align-items: center;
            gap: 6px;
            font-family: var(--font-heading);
            font-size: 26px;
            font-weight: 900;
            color: var(--green);
            background: #0f1914;
            padding: 4px 12px;
            border-radius: 8px;
            border: 1.5px solid rgba(180, 245, 107, 0.4);
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
        }
"""

style_tag = "</style>"
idx = text_org.find(style_tag)
assert idx != -1
text_org = text_org[:idx] + extra_css + text_org[idx:]

# 2. Insert next_match hero banner in Tab 2: Fixtures
fixtures_tab_start = """                <!-- TAB 2: FIXTURES & SCHEDULING -->
                <section class="tab-content {% if active_tab == 'fixtures' %}active{% endif %}" id="fixtures">"""

next_match_banner = """                <!-- TAB 2: FIXTURES & SCHEDULING -->
                <section class="tab-content {% if active_tab == 'fixtures' %}active{% endif %}" id="fixtures">
                    {% if next_match %}
                    <!-- NEXT MATCH HERO BANNER (MATCHING LEAGUE BANNER DESIGN) -->
                    <section class="league-banner next-match-hero-banner" style="margin-bottom:18px;">
                        <div class="league-brand">
                            <div class="match-banner-crests">
                                <div class="league-crest" title="{{ next_match.home_team.name }}">
                                    {% if next_match.home_team.get_logo_url %}
                                    <img src="{{ next_match.home_team.get_logo_url }}" alt="{{ next_match.home_team.name }}">
                                    {% else %}
                                    <span class="league-crest-fallback" style="font-weight:900;color:var(--green);font-size:22px;">{{ next_match.home_team.short_name|default:next_match.home_team.name|slice:":3"|upper }}</span>
                                    {% endif %}
                                </div>
                                <span class="match-vs-badge">VS</span>
                                <div class="league-crest" title="{{ next_match.away_team.name }}">
                                    {% if next_match.away_team.get_logo_url %}
                                    <img src="{{ next_match.away_team.get_logo_url }}" alt="{{ next_match.away_team.name }}">
                                    {% else %}
                                    <span class="league-crest-fallback" style="font-weight:900;color:var(--green);font-size:22px;">{{ next_match.away_team.short_name|default:next_match.away_team.name|slice:":3"|upper }}</span>
                                    {% endif %}
                                </div>
                            </div>
                            <div class="league-info">
                                <span class="status-pill live" style="margin-bottom:4px;display:inline-block;background:var(--green);color:var(--dark);font-weight:900;">⚡ Next Match</span>
                                <h2>{{ next_match.home_team.name }} <span style="color:var(--green);font-weight:600;font-size:20px;">vs</span> {{ next_match.away_team.name }}</h2>
                                <div class="league-meta">
                                    <span>◷ {{ next_match.match_date|date:"D, d M Y" }} · {{ next_match.kickoff_time|time:"H:i" }}</span>
                                    <span>📍 {{ next_match.venue|default:"Official Pitch" }}</span>
                                    <span>🏆 {{ next_match.tournament_round }}</span>
                                    <span>🛡️ {{ active_competition.name }}</span>
                                </div>
                            </div>
                        </div>
                        <div class="banner-actions">
                            <button class="btn" style="background:#ffffff;color:var(--dark);font-weight:800;" type="button"
                                onclick="openRescheduleModal('{{ next_match.id }}', '{{ next_match.home_team.name|escapejs }} vs {{ next_match.away_team.name|escapejs }}', '{{ next_match.match_date.isoformat }}', '{{ next_match.kickoff_time.isoformat }}', '{{ next_match.venue|escapejs }}', '{{ next_match.status }}', '{{ next_match.tournament_round|escapejs }}')">
                                📅 Reschedule
                            </button>
                            <button class="btn btn-primary" type="button"
                                onclick="openRecordResultModal('{{ next_match.id }}', '{{ next_match.home_team.name|escapejs }}', '{{ next_match.away_team.name|escapejs }}', '{{ next_match.tournament_round }}')">
                                + Enter Score
                            </button>
                        </div>
                    </section>
                    {% endif %}"""

assert fixtures_tab_start in text_org, "fixtures_tab_start not found in organizer_index.html"
text_org = text_org.replace(fixtures_tab_start, next_match_banner, 1)

# 3. Insert last_match hero banner in Tab 3: Results
results_tab_start = """                <!-- TAB 3: RESULTS ENTRY -->
                <section class="tab-content {% if active_tab == 'results' %}active{% endif %}" id="results">"""

last_match_banner = """                <!-- TAB 3: RESULTS ENTRY -->
                <section class="tab-content {% if active_tab == 'results' %}active{% endif %}" id="results">
                    {% if last_match %}
                    <!-- LAST MATCH HERO BANNER (MATCHING LEAGUE BANNER DESIGN) -->
                    <section class="league-banner last-match-hero-banner" style="margin-bottom:18px;">
                        <div class="league-brand">
                            <div class="match-banner-crests">
                                <div class="league-crest" title="{{ last_match.home_team.name }}">
                                    {% if last_match.home_team.get_logo_url %}
                                    <img src="{{ last_match.home_team.get_logo_url }}" alt="{{ last_match.home_team.name }}">
                                    {% else %}
                                    <span class="league-crest-fallback" style="font-weight:900;color:var(--green);font-size:22px;">{{ last_match.home_team.short_name|default:last_match.home_team.name|slice:":3"|upper }}</span>
                                    {% endif %}
                                </div>
                                <div class="banner-score-display">
                                    <span>{{ last_match.home_score }}</span>
                                    <span style="opacity:0.6;font-size:16px;">:</span>
                                    <span>{{ last_match.away_score }}</span>
                                </div>
                                <div class="league-crest" title="{{ last_match.away_team.name }}">
                                    {% if last_match.away_team.get_logo_url %}
                                    <img src="{{ last_match.away_team.get_logo_url }}" alt="{{ last_match.away_team.name }}">
                                    {% else %}
                                    <span class="league-crest-fallback" style="font-weight:900;color:var(--green);font-size:22px;">{{ last_match.away_team.short_name|default:last_match.away_team.name|slice:":3"|upper }}</span>
                                    {% endif %}
                                </div>
                            </div>
                            <div class="league-info">
                                <span class="status-pill live" style="margin-bottom:4px;display:inline-block;background:var(--green);color:var(--dark);font-weight:900;">🏆 Last Match Result</span>
                                <h2>{{ last_match.home_team.name }} <span style="color:var(--green);font-weight:900;margin:0 4px;">{{ last_match.home_score }} - {{ last_match.away_score }}</span> {{ last_match.away_team.name }}</h2>
                                <div class="league-meta">
                                    <span>◷ Full Time · {{ last_match.match_date|date:"D, d M Y" }}</span>
                                    <span>📍 {{ last_match.venue|default:"Official Pitch" }}</span>
                                    <span>🏆 {{ last_match.tournament_round }}</span>
                                    <span>⚡ {{ last_match.events.count }} Events recorded</span>
                                </div>
                            </div>
                        </div>
                        <div class="banner-actions">
                            <button class="btn btn-primary" type="button"
                                onclick="openRecordResultModal('{{ last_match.id }}', '{{ last_match.home_team.name|escapejs }}', '{{ last_match.away_team.name|escapejs }}', '{{ last_match.tournament_round }}', '{{ last_match.home_score|default_if_none:0 }}', '{{ last_match.away_score|default_if_none:0 }}')">
                                ✎ Edit Score &amp; Events
                            </button>
                        </div>
                    </section>
                    {% endif %}"""

assert results_tab_start in text_org, "results_tab_start not found in organizer_index.html"
text_org = text_org.replace(results_tab_start, last_match_banner, 1)

with open(path_org, 'w', encoding='utf-8') as f:
    f.write(text_org)

print("[OK] Successfully installed Next Match and Last Match hero banners in organizer_index.html")

