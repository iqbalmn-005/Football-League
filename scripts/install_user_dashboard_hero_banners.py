import os

path_user = 'front/user_dashboard.html'
with open(path_user, 'r', encoding='utf-8') as f:
    text_user = f.read().replace('\r\n', '\n')

banner_css = """
        /* LEAGUE BANNER DESIGN FOR FEATURED MATCHES */
        .league-banner {
            position: relative;
            overflow: hidden;
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 20px;
            padding: 22px 26px;
            margin-bottom: 24px;
            border: 1px solid #26342b;
            border-radius: 8px;
            background:
                radial-gradient(ellipse at 90% 10%, rgba(180, 245, 107, 0.16), transparent 50%),
                linear-gradient(135deg, #101b16, #17251e);
            color: #ffffff;
        }

        .league-banner::after {
            content: "⚽";
            position: absolute;
            right: 22%;
            top: -40px;
            font-size: 150px;
            opacity: .05;
            pointer-events: none;
        }

        .league-brand {
            display: flex;
            align-items: center;
            gap: 18px;
            min-width: 0;
            flex: 1;
        }

        .match-banner-crests {
            display: flex;
            align-items: center;
            gap: 10px;
            flex-shrink: 0;
        }

        .league-crest {
            width: 62px;
            height: 62px;
            min-width: 62px;
            min-height: 62px;
            border-radius: 12px;
            background: #0f1914;
            border: 2px solid rgba(180, 245, 107, 0.45);
            box-shadow: 0 4px 14px rgba(0, 0, 0, 0.35);
            display: flex;
            align-items: center;
            justify-content: center;
            overflow: hidden;
            flex-shrink: 0;
        }

        .league-crest img {
            width: 100%;
            height: 100%;
            object-fit: cover;
            display: block;
        }

        .league-crest-fallback {
            font-family: var(--font-heading);
            font-size: 22px;
            line-height: 1;
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

        .league-info {
            min-width: 0;
            flex: 1;
        }

        .league-info h2 {
            font-family: var(--font-heading);
            font-size: 24px;
            font-weight: 900;
            margin: 2px 0 6px;
            color: #ffffff;
            line-height: 1.2;
            word-break: break-word;
        }

        .league-meta {
            display: flex;
            gap: 14px;
            flex-wrap: wrap;
            font-size: 12px;
            color: rgba(255, 255, 255, 0.75);
            font-weight: 600;
        }

        .banner-actions {
            flex-shrink: 0;
            display: flex;
            gap: 10px;
        }

        .status-pill.live {
            background: var(--green);
            color: var(--dark);
            font-size: 10px;
            font-weight: 900;
            padding: 3px 8px;
            border-radius: 4px;
            letter-spacing: 0.5px;
            text-transform: uppercase;
        }

        @media (max-width: 900px) {
            .league-banner {
                flex-direction: column;
                align-items: flex-start;
                padding: 18px 20px;
                gap: 16px;
            }
            .banner-actions {
                width: 100%;
            }
            .banner-actions .btn {
                width: 100%;
            }
        }
"""

style_tag = "</style>"
idx = text_user.find(style_tag)
assert idx != -1
text_user = text_user[:idx] + banner_css + text_user[idx:]

# 1. Insert Next Match banner in Upcoming tab
upcoming_header = """                <div class="section-header-row">
                    <div class="section-title-box">
                        <h2>Upcoming matches</h2>
                        <p>Your next fixtures, kickoff times and venues.</p>
                    </div>
                    <div class="filter-pill-group">
                        <button class="filter-btn active" onclick="filterFixtures('all', this)">All Matches</button>
                        <button class="filter-btn" onclick="filterFixtures('week', this)">This Week</button>
                    </div>
                </div>"""

upcoming_banner = """                <div class="section-header-row">
                    <div class="section-title-box">
                        <h2>Upcoming matches</h2>
                        <p>Your next fixtures, kickoff times and venues.</p>
                    </div>
                    <div class="filter-pill-group">
                        <button class="filter-btn active" onclick="filterFixtures('all', this)">All Matches</button>
                        <button class="filter-btn" onclick="filterFixtures('week', this)">This Week</button>
                    </div>
                </div>

                {% if next_match %}
                <!-- FEATURED NEXT MATCH HERO BANNER -->
                <section class="league-banner next-match-hero-banner" style="margin-bottom:20px;">
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
                            <span class="status-pill live" style="margin-bottom:4px;display:inline-block;">⚡ Next Match</span>
                            <h2>{{ next_match.home_team.name }} <span style="color:var(--green);font-weight:600;font-size:20px;">vs</span> {{ next_match.away_team.name }}</h2>
                            <div class="league-meta">
                                <span>◷ {{ next_match.match_date|date:"D, d M Y" }} · {{ next_match.kickoff_time|time:"H:i A" }}</span>
                                <span>📍 {{ next_match.venue|default:"Community Pitch" }}</span>
                                <span>🏆 {{ next_match.tournament_round }}</span>
                            </div>
                        </div>
                    </div>
                    <div class="banner-actions">
                        <button class="btn btn-primary" type="button" onclick="openMatchModal('{{ next_match.id }}')">
                            👁 Match Details
                        </button>
                    </div>
                </section>
                {% endif %}"""

assert upcoming_header in text_user, "upcoming_header not found in user_dashboard.html"
text_user = text_user.replace(upcoming_header, upcoming_banner, 1)

# 2. Insert Last Result banner in Results tab
results_header = """                <div class="section-header-row">
                    <div class="section-title-box">
                        <h2>Completed Match Results</h2>
                        <p>Full-time scores, goal scorers, and official match records.</p>
                    </div>
                </div>"""

results_banner = """                <div class="section-header-row">
                    <div class="section-title-box">
                        <h2>Completed Match Results</h2>
                        <p>Full-time scores, goal scorers, and official match records.</p>
                    </div>
                </div>

                {% if last_match %}
                <!-- FEATURED LAST MATCH RESULT HERO BANNER -->
                <section class="league-banner last-match-hero-banner" style="margin-bottom:20px;">
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
                            <span class="status-pill live" style="margin-bottom:4px;display:inline-block;">🏆 Last Match Result</span>
                            <h2>{{ last_match.home_team.name }} <span style="color:var(--green);font-weight:900;margin:0 4px;">{{ last_match.home_score }} - {{ last_match.away_score }}</span> {{ last_match.away_team.name }}</h2>
                            <div class="league-meta">
                                <span>◷ Full Time · {{ last_match.match_date|date:"D, d M Y" }}</span>
                                <span>📍 {{ last_match.venue|default:"Community Pitch" }}</span>
                                <span>🏆 {{ last_match.tournament_round }}</span>
                            </div>
                        </div>
                    </div>
                    <div class="banner-actions">
                        <button class="btn btn-primary" type="button" onclick="openMatchModal('{{ last_match.id }}')">
                            👁 Match Report
                        </button>
                    </div>
                </section>
                {% endif %}"""

assert results_header in text_user, "results_header not found in user_dashboard.html"
text_user = text_user.replace(results_header, results_banner, 1)

with open(path_user, 'w', encoding='utf-8') as f:
    f.write(text_user)

print("[OK] Successfully installed Next Match and Last Match hero banners in user_dashboard.html")

