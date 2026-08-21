# Changelog

All notable changes to the **fantasybot** project for rival tracking, transfer accounting, and squad analysis.

---

## [Unreleased] - 2026-08-21

### Added

#### 1. API Client Enhancements (`fantasybot/api.py`)
- **`league_teams(league_id)`**: Fetches live roster, market valuations, manager points, positions, and squad clause data for all league participants.
- **`league_activity(league_id, fetch_all=True)`**: Automatically iterates through paginated endpoints (`/leagues/{id}/activity/{idx}`) to retrieve the complete chronological transfer history from day 1 of the league.

#### 2. Persistent Transaction & Squad State (`fantasybot/state.py`)
- **Cumulative Activity Storage (`.state/activity_history.json`)**: Merges and de-duplicates transfer events across sessions so that historical transactions are never lost even after API circular buffer rollovers.
- **Rival Squad Snapshots (`.state/rivals_snapshot.json`)**: Tracks squad rosters and detects clause increases / blindajes between runs.
- **Players Metadata Cache (`.state/players_cache.json`)**: Caches player name, position, and valuations locally to minimize API traffic.
- Added state management functions: `record_activity()`, `load_activity_history()`, `snapshot_rivals()`, `save_rivals_snapshot()`, `load_rivals_snapshot()`, `load_players_cache()`, `save_players_cache()`, and `diff_rival_clauses()`.

#### 3. Rival Strategy & Accounting Module (`fantasybot/strategy/rivals.py`)
- **`parse_activity()`**: Aggregates market purchases (`Type 31`), market sales (`Type 33`), manager-to-manager buyouts (`Type 1`), and matchday point rewards (`Type 6`).
- **`analyze_player_acquisitions()`**: Cross-references squad players with historical purchases to identify:
  - Exact purchase price (`BOUGHT AT`) and buy date.
  - Capital gain/loss (`PROFIT / LOSS`) in currency and percentage revaluation ($\Delta \text{Value}$ and $\%\text{Gain}$).
  - Identification of players from the initial assigned squad (`(Initial)`).
- **`analyze_squad_clauses()`**: Calculates total squad clause valuation, highest clause, and top protected player ($\text{Clause} - \text{Market Value}$).
- **`analyze_rivals()`**: Combines squad valuations, persistent transaction history, and pure baseline accounting to estimate available liquid cash for all league rivals.

#### 4. Trading History & P&L Module (`fantasybot/strategy/history.py`)
- **`compute_manager_trading_history()`**:
  - Matches buy and sell transactions (FIFO) by player to compute completed flips, holding duration in days, and return on equity (ROI %).
  - Tracks open purchased holdings with live unrealized capital gains/losses.
  - Tracks initial squad liquidations and total sales revenue.
- **`resolve_player_names()`**: Resolves player metadata from local cache and API.
- **`analyze_league_trading_history()`**: Produces league-wide speculation leaderboards sorted by total portfolio P&L.

#### 5. CLI Commands (`fantasybot/cli.py`)
- **`python -m fantasybot rivals [manager|rank]`**:
  - General league overview with position, team value, squad size, total purchases, total sales, net profit, estimated cash, and top protected players.
  - Detailed individual squad performance table (`PLAYER`, `POS`, `BOUGHT AT`, `CURRENT VALUE`, `PROFIT / LOSS`, `CLAUSE`, `PROTECTION`).
  - Reality check comparison on user's own account (`Real Cash vs Pure Estimated`).
- **`python -m fantasybot history [manager|rank]`**:
  - League-wide speculation and trading ROI leaderboard (`TOTAL P&L`, `REALIZED`, `UNREALIZED`, `FLIPS`, `WIN%`, `AVG ROI`).
  - Detailed trade log showing open holdings, completed flips with ROI %, and initial squad sales.
- **Flexible search support**: Query by multi-word name without quotes (`rivals EPT Alfaro`), rank position (`rivals 1` or `#1`), manager/team ID (`rivals 867521`), or shortcut for own account (`rivals me`).
- **`--json` flags**: Structured JSON export for programmatic consumption (`rivals --json`, `history --json`).
- **`--initial-budget` flag**: Allows custom league starting budget overrides.

#### 6. Multi-User Telegram Bot & Interactive Autopilot (`fantasybot/telegram/`)
- **Multi-Tenant Sessions (`fantasybot/telegram/sessions.py`)**:
  - Multi-user session storage with isolated tokens per `chat_id` and automatic OAuth2 PKCE login.
  - Multi-league switcher (`/leagues`) with dynamic league selection and persistent active league tracking.
  - User preference toggles (`get_user_settings`, `toggle_user_setting`) for personalized alert configuration.
- **Interactive Action Engine (`fantasybot/telegram/bot.py`)**:
  - **1-Click Lineup Applicator**: Directly sets optimal tactical XI on official LaLiga Fantasy accounts.
  - **Single-Tap Bids & Buyouts**: Distinguishes between auction market bids (`make_bid`) and manager buyout clauses (`pay_buyout_clause`) with dedicated buttons and owner tags.
  - **Squad Player Sales**: List players on the transfer market with one click (`/sell`).
  - **1-Click Autopilot**: Runs lineup optimization, submits high-margin flip bids within balance limits, and cancels declining bids (`/autopilot` / `/run`).
- **Mobile-First UX & Visual Card Redesign (`fantasybot/telegram/ui.py`)**:
  - Overhauled all command outputs for mobile legibility, replacing monospaced tables with structured card layouts.
  - Spanish currency formatting (`1.000.000 €` / `14,2M €`).
  - Categorized squad breakdown by position (`🧤 PORTEROS`, `🛡 DEFENSAS`, `🎯 CENTROCAMPISTAS`, `⚡ DELANTEROS`).
  - Flip opportunity cards with manager ownership indicator, 7-day projections, and expected profit margin.
  - Ranked rival cards with podium medals (🥇, 🥈, 🥉), estimated liquid cash, and squad valuations.
- **Background Notification & Alert Worker (`fantasybot/telegram/notifications.py`)**:
  - Background daemon thread checking for new profitable market flips and automatic matchday lineup optimization.
  - Interactive settings panel (`/settings`) with instant toggle buttons for flip alerts, matchday reminders, and auto-lineups.
- **User Feedback & Bug Inbox (`fantasybot/telegram/feedback.py`)**:
  - `/bug <msg>` and `/sugerencia <msg>` commands for users to send feedback directly.
  - Persistent JSON Lines feedback storage (`.state/feedback.jsonl`).
  - Real-time forwarding of reports to admin chat ID.
  - Admin inbox viewer command (`/reportes` / `/admin_feedback`).
- **Zero External Dependencies**: Pure Python standard library implementation (`urllib.request`, `json`, `threading`).

#### 7. LLM Agent Integration (`fantasybot/agent.py`)
- Included league rival financial data and clause increases into `review()` dictionary and CLI summary output.

#### 8. Unit Tests (`tests/test_rivals.py`, `tests/test_history.py`, `tests/test_telegram.py`)
- Added comprehensive unit tests covering activity parsing, clause protection analysis, rival accounting, trade ROI, and Telegram sessions/UI.
- All **56/56 unit tests** passing in test suite.

#### 9. Documentation (`README.md`)
- Updated README with usage instructions for `rivals`, `history`, and `telegram`, plus attribution credits to original author Jon Ortega.
