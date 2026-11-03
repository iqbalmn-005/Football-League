import re

with open('front/organizer_index.html', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Add CSS before </style>
css_snippet = """
        /* TEAMS & SQUADS MINIMALIST CARDS (LOGO & NAME ONLY) */
        .teams-cards-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
            gap: 18px;
            padding: 24px;
        }

        .organizer-team-card {
            background: #ffffff;
            border: 1.5px solid var(--border);
            border-radius: 12px;
            padding: 24px 16px;
            text-align: center;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            gap: 14px;
            text-decoration: none;
            cursor: pointer;
            transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1);
            box-shadow: 0 1px 4px rgba(0, 0, 0, 0.03);
            position: relative;
            overflow: hidden;
        }

        .organizer-team-card::before {
            content: "";
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            height: 3px;
            background: linear-gradient(90deg, #245d3c, #b4f56b);
            opacity: 0;
            transition: opacity 0.2s ease;
        }

        .organizer-team-card:hover {
            transform: translateY(-4px);
            border-color: var(--green-dark);
            box-shadow: 0 10px 24px rgba(36, 93, 60, 0.12);
            background: #fafdfa;
        }

        .organizer-team-card:hover::before {
            opacity: 1;
        }

        .team-card-crest {
            width: 80px;
            height: 80px;
            border-radius: 50%;
            background: var(--soft-green);
            border: 2px solid rgba(36, 93, 60, 0.2);
            display: flex;
            align-items: center;
            justify-content: center;
            overflow: hidden;
            flex-shrink: 0;
            box-shadow: 0 3px 10px rgba(0, 0, 0, 0.06);
            transition: transform 0.2s ease, border-color 0.2s ease;
        }

        .organizer-team-card:hover .team-card-crest {
            transform: scale(1.08);
            border-color: var(--green-dark);
        }

        .team-card-crest img {
            width: 100%;
            height: 100%;
            object-fit: cover;
            display: block;
        }

        .team-crest-fallback {
            font-family: var(--font-heading);
            font-size: 24px;
            font-weight: 900;
            color: var(--green-dark);
            letter-spacing: 0.5px;
        }

        .team-card-title {
            font-family: var(--font-heading);
            font-size: 17px;
            font-weight: 800;
            color: var(--dark);
            line-height: 1.25;
            text-align: center;
            word-break: break-word;
            transition: color 0.15s ease;
        }

        .organizer-team-card:hover .team-card-title {
            color: var(--green-dark);
        }

        .team-empty-state {
            grid-column: 1 / -1;
            text-align: center;
            padding: 48px 20px;
            color: var(--muted);
        }

        @media (max-width: 768px) {
            .teams-cards-grid {
                grid-template-columns: repeat(2, 1fr);
                gap: 12px;
                padding: 16px;
            }

            .organizer-team-card {
                padding: 18px 12px;
            }

            .team-card-crest {
                width: 64px;
                height: 64px;
            }

            .team-card-title {
                font-size: 15px;
            }
        }
    </style>"""

if 'TEAMS & SQUADS MINIMALIST CARDS' not in content:
    content = content.replace('</style>', css_snippet, 1)

# 2. Replace Tab 5 Teams section
old_teams_section_pattern = re.compile(
    r'(<!-- TAB 5: TEAMS & SQUADS -->\s*<section class="tab-content \{% if active_tab == \'teams\' %\}active\{% endif %\}" id="teams">)(.*?)(</section>)',
    re.DOTALL
)

new_teams_html = """<!-- TAB 5: TEAMS & SQUADS -->
                <section class="tab-content {% if active_tab == 'teams' %}active{% endif %}" id="teams">
                    <div class="card">
                        <div class="card-heading">
                            <div>
                                <h2>♟ Participating Teams</h2>
                                <p class="card-subtitle">Click on any team to view full squad details, player cards, and manage players.</p>
                            </div>
                            <button class="btn btn-primary" onclick="openAddTeamModal()">+ Register New Team</button>
                        </div>

                        <div class="teams-cards-grid">
                            {% for t in comp_teams %}
                            <a href="/organizer/team/{{ t.id }}/?competition={{ active_competition.id }}" class="organizer-team-card" title="Click to view player cards & squad for {{ t.name }}">
                                <div class="team-card-crest">
                                    {% if t.get_logo_url %}
                                    <img src="{{ t.get_logo_url }}" alt="{{ t.name }}" loading="lazy">
                                    {% else %}
                                    <span class="team-crest-fallback">{{ t.short_name|default:t.name|slice:":3"|upper }}</span>
                                    {% endif %}
                                </div>
                                <div class="team-card-title">{{ t.name }}</div>
                            </a>
                            {% empty %}
                            <div class="team-empty-state">
                                <div style="font-size:42px;margin-bottom:10px;">🛡️</div>
                                <h3 style="font-family:var(--font-heading);font-size:20px;color:var(--dark);margin-bottom:6px;">No Teams Registered Yet</h3>
                                <p style="color:var(--muted);font-size:12px;margin-bottom:18px;">Click "+ Register New Team" above to add participating clubs to this competition.</p>
                                <button class="btn btn-primary" type="button" onclick="openAddTeamModal()">+ Register New Team</button>
                            </div>
                            {% endfor %}
                        </div>
                    </div>
                </section>"""

content, count = old_teams_section_pattern.subn(new_teams_html, content)
print(f"Replaced tab content count: {count}")

with open('front/organizer_index.html', 'w', encoding='utf-8') as f:
    f.write(content)

print("Updated front/organizer_index.html successfully!")

