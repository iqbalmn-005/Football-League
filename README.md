# TOUCHLINE ⚽
> **Tagline:** *Your Game. Your League.*

TOUCHLINE is a comprehensive, production-ready football tournament and league management platform built with Python Django. It delivers a modern, responsive interface for community leagues, weekend cups, elite academies, and grassroots tournaments.

---

## 🌟 Key Highlights & Features

### 1. Three Distinct Role-Based Portals (RBAC)
- **Super Admin (`/super-admin/`):**
  - Real-time command center dashboard with KPI metrics.
  - **Approvals Hub:** Review organizer applications, quick-approve or decline with customized rejection feedback.
  - **Competition Control:** Create leagues & tournaments, assign competitions to verified organizers, or transfer competitions between directors.
  - **Organizer Management:** Suspend or reactivate organizers instantly.
  - **Directory:** Global registry of clubs, teams, and player rosters.
  - **Audit Trail:** Comprehensive activity logging of all administrative actions.
  - **Platform Settings:** Toggle registrations, default rules, and auto-publishing.

- **League Organizer (`/organizer/`):**
  - **Competition Switcher:** Manage multiple assigned or created tournaments from one unified console.
  - **Berger Algorithm Fixture Generator:** Automatically generates balanced single or double round-robin matchweeks in one click.
  - **Match Management:** Schedule or reschedule dates, kickoff times, and venues.
  - **Official Match Scorecards:** Enter match results with goal scorers, assist providers, and yellow/red cards.
  - **Automated Points Table:** Standings automatically recompute on result submission (Win = 3 pts, Draw = 1 pt, Loss = 0 pts; sorted by Points, GD, GF).
  - **Squad & Player Registration:** Add teams with crests, managers, home grounds, and player profiles with photos and jersey numbers.
  - **Co-Organizer Delegation:** Invite other verified organizers to assist in tournament coordination.

- **Public Viewer (`/`):**
  - **Landing Page (`list.html`):** Explore all active and upcoming competitions with category filters (11-a-side, 7-a-side, 5-a-side, Youth) and live search.
  - **Public Tournament Viewer (`/competition/<id>/`):** Five full interactive sections:
    1. *Upcoming Matches* (with venue & kickoff details).
    2. *Completed Results* (interactive scorecards & match event breakdown).
    3. *Live Points Table* (with official 5-match form guide pills).
    4. *Statistics Leaderboards* (Golden Boot race, Golden Glove clean sheets, Disciplinary cards).
    5. *Clubs Directory* (with team profiles and squad rosters).
  - **Interactive Modals:** Popups for player headshots, age, nationality, statistics, and full match event timelines.
  - **Team Profile (`/team/<id>/`):** Dedicated club landing page with squad rosters, manager info, win rate, and recent match history.

---

## 🎨 Color Palette & Typography
- **Main Background:** `#101B16`
- **Card Background:** `#17251E`
- **Accent Green:** `#B4F56B`
- **Dark Green:** `#245D3C`
- **Cream Surface:** `#F5F6EF`
- **White:** `#FFFFFF`
- **Muted Text:** `#AAB5AC`
- **Borders:** `#34453B`
- **Headings Font:** *Barlow Condensed*
- **Body Font:** *DM Sans*

---

## 🚀 Quick Start Guide (Local Setup)

### Prerequisites
- Python 3.10+ (tested on Python 3.12 / 3.14)
- pip

### 1. Clone & Enter Project Directory
```bash
cd Football/Football
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Apply Database Migrations
```bash
python manage.py migrate
```

### 4. Populate Complete Demo Dataset
Populates Super Admin, Approved Organizers, Pending Applicant, Rejected Applicant, Viewer, 4 Competitions, 8 Teams, 88 Players, and generated fixtures with completed match results:
```bash
python manage.py seed_data
```

### 5. Launch Development Server
```bash
python manage.py runserver
```
Visit `http://localhost:8000/` in your browser.

---

## 🔑 Pre-Seeded Demonstration Accounts

| Role | Username / Identifier | Password | Access / Status |
|---|---|---|---|
| **Super Admin** | `admin` | `adminpassword123` | Full root access at `/super-admin/` |
| **Approved Organizer 1** | `07700900001` (or `sarah.jenkins`) | `organizer123` | Directs Metropolis Premier League at `/organizer/` |
| **Approved Organizer 2** | `07700900002` (or `viktor.chen`) | `organizer123` | Directs Saturday Sevens Championship |
| **Pending Organizer** | `07700900003` (or `marcus.vance`) | `organizer123` | Application pending in Super Admin Approvals Hub |
| **Rejected Organizer** | `07700900004` (or `clara.oswald`) | `organizer123` | Shows rejection reason & re-apply option |
| **Public Viewer** | `viewer` | `viewer123` | Public browsing at `/` |

---

## 🔄 End-to-End Workflow Testing

1. **Organizer Registration:**
   - Go to `http://localhost:8000/register/`.
   - Select *League / Tournament Organizer*, enter phone number and password.
   - Fill out the *Organizer Application* form with organization details, experience, and proposed leagues.
   - Status updates to `Under Review`.
2. **Super Admin Review:**
   - Log in as `admin` (`adminpassword123`) and navigate to `/super-admin/?tab=approvals`.
   - Click **✓ Approve** or **✕ Reject** (which prompts for rejection notes).
3. **Competition Management:**
   - Log in as the approved organizer at `/organizer/`.
   - Add teams with logos and manager details.
   - Click **⚡ Generate Fixtures** to run the automated round-robin Berger algorithm.
   - Click **Enter Score** on any match to record final score, goal scorers, and cards.
   - Watch the **Live Standings** points table and **League Statistics** update automatically!
4. **Public Viewer Access:**
   - Open `http://localhost:8000/` as a viewer.
   - Search for competitions or filter by `11-a-side`, `7-a-side`, `5-a-side`, or `Youth`.
   - Click *View Competition* to inspect the live points table, fixtures, and click any player or match for detailed popups.

---

## 🌐 Online Deployment Guide

### Deploying to Render / Railway / Heroku
1. **Set Environment Variables:**
   - `SECRET_KEY`: Long random string
   - `DEBUG`: `False` (for production)
   - `ALLOWED_HOSTS`: `your-domain.com,*.onrender.com`
   - `DATABASE_URL`: PostgreSQL connection string (when using PostgreSQL in production)
2. **Collect Static Files:**
   ```bash
   python manage.py collectstatic --noinput
   ```
3. **Run Migrations & Seed (optional initial run):**
   ```bash
   python manage.py migrate
   python manage.py seed_data
   ```
4. **Start Web Server:**
   ```bash
   gunicorn Football.wsgi:application --bind 0.0.0.0:$PORT
   ```

---

## 🛡️ Security Measures
- Django Session-based authentication with role-based access control decorators (`@super_admin_required`, `@approved_organizer_required`).
- Password hashing with PBKDF2 SHA-256.
- CSRF protection enabled on all POST forms.
- Server-side data validation on all fixtures, scores, and applications.
- Organizer isolation: Organizers can only manage competitions explicitly assigned to them or created by them.

---

© 2026 TOUCHLINE Platform. Built for the love of the game.
