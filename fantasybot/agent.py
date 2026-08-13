"""The agent: a full review, like a human would do when logging in.

`review()` runs an attentive user's cycle:
  1) Looks at WHAT HAS CHANGED since the last connection (signings against you,
     balance...).
  2) Reviews lineup, market, flip opportunities and squad gaps.
  3) Detects buyout targets and works out WHEN to react (reminders).
  4) Keeps the week's task list (adds/completes on its own).

Returns a structured report. Firing the reminders (cronjobs) and the
notifications are built on top (see README / next steps).
"""

from datetime import datetime, timedelta

from . import state
from .matching import match_name, POS
from .strategy import flip, needs as needs_mod, sell as sell_mod
from .strategy import lineup as lineup_opt
from .sources.lineups import probable_lineups
from .sources.market_trends import trends_index
from .sources import matchday


def _parse(iso):
    try:
        return datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return None


def market_close(market):
    """Market close time = nearest expiration of a system player."""
    times = [e["expirationDate"] for e in market
             if e.get("discr") == "marketPlayerLeague" and e.get("expirationDate")]
    return min(times) if times else None


def clause_targets(market, team, prob_index):
    """Other managers' players worth signing via buyout clause when it opens.

    v1: the ones that fill a squad gap and you can afford. Each brings its unlock
    time to schedule the reminder.
    """
    gap_positions = set(needs_mod.gaps(team))
    owned = {p["playerMaster"]["id"] for p in team["players"]}
    money = team["teamMoney"]
    targets = []
    for el in market:
        if el["discr"] != "marketPlayerTeam":
            continue
        pm = el["playerMaster"]
        if pm["id"] in owned:
            continue
        pos = POS.get(pm.get("positionId"))
        pt = el.get("playerTeam", {})
        clause, unlock = pt.get("buyoutClause"), pt.get("buyoutClauseLockedEndTime")
        if not (clause and unlock and pos in gap_positions and clause <= money):
            continue
        info = match_name(pm.get("nickname", ""), pm.get("name", ""), prob_index)
        targets.append({
            "nombre": pm.get("nickname") or pm.get("name"),
            "player_id": pm["id"],
            "pos": pos,
            "clause": clause,
            "unlock": unlock,
            "prob": info.get("prob") if info else None,
            "reason": f"fills a {pos} gap",
        })
    targets.sort(key=lambda t: (t["prob"] or 0), reverse=True)
    return targets


def _sync_tasks(gaps, targets, sells, lineup_changed):
    """Keeps the task list: creates missing ones, closes resolved ones."""
    # squad gaps
    for pos in ("POR", "DEF", "MED", "DEL"):
        key = f"gap:{pos}"
        if pos in gaps:
            state.add_task(f"Sign {pos}: you're short in that position.", key=key)
        else:
            state.complete_by_key(key)
    # buyout targets (and close the ones that no longer apply)
    for t in targets:
        state.add_task(
            f"Buyout {t['nombre']} ({t['pos']}) for {t['clause']:,} "
            f"when its clause opens.", due=t["unlock"], key=f"clause:{t['player_id']}")
    state.complete_missing("clause:", {f"clause:{t['player_id']}" for t in targets})
    # recommended sales
    for s in sells:
        state.add_task(f"Sell {s['nombre']} (~{s['sale_price']:,}): {s['reason']}.",
                       key=f"sell:{s['player_id']}")
    state.complete_missing("sell:", {f"sell:{s['player_id']}" for s in sells})
    # lineup
    if lineup_changed:
        state.add_task("Update lineup (there's a better XI).", key="lineup")
    else:
        state.complete_by_key("lineup")


def _current_xi_ids(client, team_id):
    lu = client.lineup(team_id)
    f = lu.get("formation", {})
    ids = set()
    for pos in ("goalkeeper", "defender", "midfield", "striker"):
        for p in f.get(pos, []) or []:
            ids.add(p.get("playerTeamId") or p["playerMaster"]["id"])
    return ids


def review(client, days_to_matchday=None):
    lid, tid = client.default_ids()
    team = client.team(lid, tid)
    market = client.market(lid)
    prob_index = probable_lineups()

    # date of the next matchday (for urgency and final lineup)
    kickoff = matchday.next_kickoff()
    if days_to_matchday is None:
        days_to_matchday = matchday.days_until_matchday()

    # 1) what has changed
    prev = state.load_snapshot()
    curr = state.snapshot(team)
    events = state.diff_snapshots(prev, curr)
    state.save_snapshot(curr)

    # 2) lineup (squad may be temporarily too thin for any valid formation,
    # e.g. early season / after sales — degrade gracefully instead of crashing)
    try:
        best = lineup_opt.optimize(team, prob_index)
        best_ids = lineup_opt.payload_ids(best)
        lineup_changed = best_ids != _current_xi_ids(client, tid)
        lineup_error = None
    except ValueError as e:
        best = None
        lineup_changed = False
        lineup_error = str(e)

    # 3) flips, needs and sales
    flips = [o for o in flip.opportunities(client, lid)
             if o["margin_pct"] > 0 and o["buy_price"] <= team["teamMoney"]][:5]
    gaps = needs_mod.gaps(team)
    needs_report = needs_mod.advise(client, lid, team, days_to_matchday)
    sells = sell_mod.sell_candidates(team, best, trends_index()) if best else []

    # 4) buyout targets + reminders
    targets = clause_targets(market, team, prob_index)
    reminders = []
    close = market_close(market)
    if close:
        dt = _parse(close)
        if dt:
            reminders.append({
                "key": f"market_close:{close}",
                "fire_at": (dt - timedelta(minutes=5)).isoformat(),
                "event_at": close,
                "message": "Market closes in 5 min: review bids and needs.",
            })
    for t in targets:
        dt = _parse(t["unlock"])
        if dt:
            reminders.append({
                "key": f"clause:{t['player_id']}:{t['unlock']}",
                "fire_at": (dt - timedelta(seconds=60)).isoformat(),
                "event_at": t["unlock"],
                "message": (f"{t['nombre']}'s clause opens: prepare a buyout "
                            f"of {t['clause']:,} ({t['reason']})."),
            })
    if kickoff:
        kdt = _parse(kickoff)
        if kdt:
            reminders.append({
                "key": f"lineup_lock:{kickoff}",
                "fire_at": (kdt - timedelta(hours=2)).isoformat(),
                "event_at": kickoff,
                "message": "Matchday starts in 2h: set your FINAL LINEUP.",
            })
    reminders.sort(key=lambda r: r["fire_at"])

    _sync_tasks(gaps, targets, sells, lineup_changed)
    state.save_reminders(reminders)

    return {
        "events": events,
        "money": team["teamMoney"],
        "matchday": {"kickoff": kickoff, "days": days_to_matchday},
        "lineup": ({"formation": best["formation"], "changed": lineup_changed,
                    "total": best["total"], "watch": best.get("watch", [])}
                   if best else {"error": lineup_error}),
        "flips": flips,
        "gaps": gaps,
        "needs": needs_report,
        "sells": sells,
        "clause_targets": targets,
        "reminders": reminders,
        "tasks": state.pending_tasks(),
    }
