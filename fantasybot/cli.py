"""fantasybot command-line interface.

    python -m fantasybot login                 # step 1: generate the login URL
    python -m fantasybot login "authredirect://...?code=..."   # step 2: redeem
    python -m fantasybot refresh               # renew the token
    python -m fantasybot me | leagues | team | market | lineup
    python -m fantasybot trends                # who's rising/falling in value
    python -m fantasybot onces real-madrid     # a team's likely starting XI
    python -m fantasybot flip [--horizon N]    # resale opportunities
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone

from . import auth
from .api import FantasyClient, FantasyError
from .sources import lineups as ff_lineups
from .sources.market_trends import market_trends
from .strategy import flip
from .strategy import lineup as lineup_opt
from .strategy import needs as needs_mod
from . import agent as agent_mod
from . import execute as execute_mod
from . import events
from . import state


def _print_json(obj):
    print(json.dumps(obj, indent=2, ensure_ascii=False))


def cmd_login(args):
    if args.redirect:
        tokens = auth.finish_login(args.redirect)
        print("[OK] Tokens saved.")
        print(f"  refresh_token: {'yes' if tokens.get('refresh_token') else 'NO'}")
    else:
        url = auth.start_login()
        print("Open this URL, log in with Google, and capture the 'authredirect://' URL")
        print("from the '(canceled)' request in DevTools > Network (Copy link address).\n")
        print(url)
        print("\nThen: python -m fantasybot login \"authredirect://...?code=...\"")


def cmd_refresh(args):
    auth.refresh(auth.load_tokens())
    print("[OK] Token refreshed.")


def cmd_me(args):
    _print_json(FantasyClient().me())


def cmd_leagues(args):
    _print_json(FantasyClient().leagues())


def cmd_team(args):
    fc = FantasyClient()
    lid, tid = fc.default_ids()
    _print_json(fc.team(lid, tid))


def cmd_lineup(args):
    fc = FantasyClient()
    _, tid = fc.default_ids()
    _print_json(fc.lineup(tid))


def cmd_market(args):
    fc = FantasyClient()
    lid, _ = fc.default_ids()
    _print_json(fc.market(lid))


def cmd_trends(args):
    players = [p for p in market_trends() if p.get("tendencia") is not None]
    up = sorted(players, key=lambda p: -p["tendencia"])[:10]
    down = sorted(players, key=lambda p: p["tendencia"])[:10]
    print("RISING:")
    for p in up:
        print(f"  {p['nombre']:<24} value={p['valor']:>12,}  trend={p['tendencia']}")
    print("FALLING:")
    for p in down:
        print(f"  {p['nombre']:<24} value={p['valor']:>12,}  trend={p['tendencia']}")


def cmd_onces(args):
    players = sorted(ff_lineups.team_lineup(args.team), key=lambda p: -(p["prob"] or 0))
    print(f"Likely starting XI {args.team} ({len(players)} players):")
    for p in players:
        estado = " ".join(s for s, on in [("INJURED", p["lesionado"]),
                           ("SUSPENDED", p["sancionado"]),
                           ("UNAVAILABLE", not p["disponible"])] if on)
        print(f"  {(p['prob'] or 0):>3}%  {p['nombre']:<26} {estado}")


def cmd_flip(args):
    fc = FantasyClient()
    lid, tid = fc.default_ids()
    team = fc.team(lid, tid)
    counts = {}
    for p in team["players"]:
        pos = flip.POS.get(p["playerMaster"]["positionId"], "?")
        counts[pos] = counts.get(pos, 0) + 1
    ops = flip.opportunities(fc, lid, args.horizon)
    if args.json:
        return _print_json({"money": team["teamMoney"], "squad": counts,
                            "horizon": args.horizon, "opportunities": ops})
    print(f"Balance: {team['teamMoney']:,} | Squad: {counts} | "
          f"Horizon: {args.horizon}d\n")
    print(f"{'PLAYER':<20}{'POS':<5}{'VIA':<9}{'BUY':>12}{'PROJ':>12}"
          f"{'MARGIN':>12}{'%':>7}  TREND")
    print("-" * 92)
    for r in ops:
        flag = " <=" if r["margin_pct"] >= 5 and r["buy_price"] <= team["teamMoney"] else ""
        print(f"{r['nombre']:<20}{r['pos']:<5}{r['via']:<9}{r['buy_price']:>12,}"
              f"{r['proyeccion']:>12,}{r['margin']:>12,}{r['margin_pct']:>6}%  "
              f"{r['tendencia']}{flag}")


def cmd_optimize(args):
    fc = FantasyClient()
    lid, tid = fc.default_ids()
    team = fc.team(lid, tid)
    best = lineup_opt.optimize(team)
    if args.json and not args.apply:
        return _print_json(best)
    d, m, f = best["formation"]
    print(f"Best formation: {d}-{m}-{f}  (score {best['total']})\n")
    for pos in ("goalkeeper", "defender", "midfield", "striker"):
        for e in ([best[pos]] if pos == "goalkeeper" else best[pos]):
            prob = f"{e['prob']}%" if e["prob"] is not None else "?"
            disp = "" if e["disponible"] else "  NOT AVAILABLE"
            print(f"  {pos[:3].upper()}  {e['nombre']:<20} prob={prob:<5} "
                  f"score={e['score']}{disp}")

    xi = lineup_opt.payload_ids(best)
    banked = [p["playerMaster"].get("nickname") for p in team["players"]
              if str(p.get("playerTeamId") or p["playerMaster"]["id"]) not in xi]
    print(f"\nSubstitutes (outside the XI): {banked}")

    if args.apply:
        fc.update_lineup(tid, best["payload"])
        events.emit("lineup", f"Lineup {d}-{m}-{f} applied",
                    detail={"score": best.get("total")})
        print("\n[OK] Lineup applied.")
    else:
        print("\n(Proposal only. Add --apply to save it to your team.)")


def cmd_needs(args):
    fc = FantasyClient()
    lid, tid = fc.default_ids()
    team = fc.team(lid, tid)
    rep = needs_mod.advise(fc, lid, team, days_to_matchday=args.days)
    if args.json:
        return _print_json(rep)
    if not rep["gaps"]:
        print("Balanced squad: no gaps below the minimum.")
        return
    print(f"Gaps: {rep['gaps']}  |  urgency factor: {rep['urgency_multiplier']}\n")
    for pos, cands in rep["suggestions"].items():
        print(f"== {pos}: candidates on the market ==")
        for c in cands[:6]:
            prob = f"{c['prob']}%" if c["prob"] is not None else "?"
            aff = "" if c["affordable"] else "  (can't afford)"
            print(f"  {c['nombre']:<20} {c['via']:<9} price={c['price']:>12,} "
                  f"maxBid={c['max_bid']:>12,} prob={prob}{aff}")
        print()


def cmd_agent(args):
    fc = FantasyClient()
    rep = agent_mod.review(fc, days_to_matchday=args.days)

    ev = rep["events"]
    cambios = "first review" if ev.get("first_run") else (
        ", ".join(filter(None, [
            f"out {ev['removed']}" if ev.get("removed") else "",
            f"in {ev['added']}" if ev.get("added") else "",
            f"balance {ev['money_delta']:+,}" if ev.get("money_delta") else "",
        ])) or "no changes")
    events.emit("review", f"Review: {cambios}",
                detail={"balance": f"{rep['money']:,}",
                        "flips": len(rep.get("flips", [])),
                        "lineup": ("change" if rep["lineup"].get("changed")
                                    else ("error" if rep["lineup"].get("error")
                                          else "already optimal"))})

    if args.json:
        return _print_json(rep)

    print("=" * 60)
    print("AGENT REVIEW")
    print("=" * 60)

    ev = rep["events"]
    if ev.get("first_run"):
        print("· First review (saving reference state).")
    else:
        if ev["removed"]:
            print(f"· ⚠ Players left your squad: {ev['removed']} "
                  f"(sale or buyout clause against you?)")
        if ev["added"]:
            print(f"· New in your squad: {ev['added']}")
        if ev["money_delta"]:
            print(f"· Balance change: {ev['money_delta']:+,}")
        if not (ev["removed"] or ev["added"] or ev["money_delta"]):
            print("· No changes since the last review.")

    print(f"\nBalance: {rep['money']:,}")
    md = rep.get("matchday") or {}
    if md.get("kickoff"):
        dias = md.get("days")
        print(f"Next matchday: {md['kickoff']}"
              + (f"  ({dias:.1f} days left)" if dias is not None else ""))
    lu = rep["lineup"]
    if lu.get("error"):
        print(f"\nOptimal lineup: NOT AVAILABLE ({lu['error']})")
    else:
        d, m, f = lu["formation"]
        tag = "  (WORTH CHANGING)" if lu["changed"] else "  (already the best)"
        print(f"Optimal lineup: {d}-{m}-{f}{tag}")
        for w in lu.get("watch", []):
            print(f"  ⚠ {w['nombre']} ({w['valor']:,}) outside the likely XI "
                  f"— transfer/injury? watch (sell?)")

    if rep["flips"]:
        print("\nFlip opportunities (buy to resell):")
        for o in rep["flips"]:
            print(f"  {o['nombre']:<18} {o['via']:<8} buy {o['buy_price']:>11,} "
                  f"→ +{o['margin']:,} ({o['margin_pct']}%)")

    if rep.get("sells"):
        print("\nRecommended sales:")
        for s in rep["sells"]:
            print(f"  {s['nombre']:<18} {s['pos']}  ~{s['sale_price']:,}  — {s['reason']}")

    if rep["gaps"]:
        print(f"\nSquad gaps: {rep['gaps']}")

    if rep["clause_targets"]:
        print("\nBuyout clause targets:")
        for t in rep["clause_targets"]:
            print(f"  {t['nombre']:<18} {t['pos']}  clause {t['clause']:,}  "
                  f"opens {t['unlock']}")

    if rep["reminders"]:
        print("\nScheduled reminders:")
        for r in rep["reminders"]:
            print(f"  [{r['fire_at']}] {r['message']}")

    if rep["tasks"]:
        print("\nPending tasks:")
        for t in rep["tasks"]:
            due = f" (before {t['due']})" if t.get("due") else ""
            print(f"  #{t['id']} {t['text']}{due}")

    # --- autonomous execution (line up + bid; buyout clauses NOT) ---
    lid, tid = fc.default_ids()
    team = fc.team(lid, tid)
    best = lineup_opt.optimize(team)
    current = agent_mod._current_xi_ids(fc, tid)
    result = execute_mod.act(fc, lid, tid, team, best, current,
                             dry_run=not args.execute)
    verbo = "EXECUTED" if args.execute else "PLAN (use --execute to act)"
    print(f"\n--- AUTONOMOUS ACTIONS [{verbo}] ---")
    lu = result["lineup"]
    if lu["changed"]:
        d, m, f = lu["formation"]
        print(f"· Lineup → {d}-{m}-{f}"
              + ("  ✓ applied" if lu.get("applied") else "  (would apply)"))
    else:
        print("· Lineup: already optimal, nothing to do.")
    bd = result["bids"]
    for b in bd["placed"]:
        print(f"· Bid {b['amount']:,} for {b['nombre']} ({b['margin_pct']}%)"
              + ("  ✓" if bd.get("applied") else "  (would bid)"))
    if not bd["placed"]:
        print("· Bids: no profitable flip opportunity right now.")
    if bd["cancelled"]:
        print(f"· Bids cancelled (no longer profitable): {bd['cancelled']}")


def cmd_sell(args):
    fc = FantasyClient()
    lid, _ = fc.default_ids()
    resp = fc.sell_player(lid, args.player_id, args.price)
    events.emit("sell", f"Sale: {args.player_id} at {args.price:,}")
    print(f"[OK] {args.player_id} listed for sale at {args.price:,}.")
    _print_json(resp)


def cmd_bid(args):
    fc = FantasyClient()
    lid, _ = fc.default_ids()
    resp = fc.make_bid(lid, args.market_id, args.amount)
    events.emit("bid", f"Bid {args.amount:,} on {args.market_id}")
    _print_json(resp)


def cmd_cancel_bid(args):
    fc = FantasyClient()
    lid, _ = fc.default_ids()
    resp = fc.cancel_bid(lid, args.market_id, args.bid_id)
    events.emit("cancel", f"Bid cancelled: {args.market_id}")
    _print_json(resp)


def cmd_clause(args):
    fc = FantasyClient()
    lid, _ = fc.default_ids()
    resp = fc.pay_buyout_clause(lid, args.player_id, args.amount)
    events.emit("clause", f"Buyout clause: {args.player_id} for {args.amount:,}")
    _print_json(resp)


def cmd_bid_now(args):
    from . import bidding
    lid, _ = FantasyClient().default_ids()
    bidding.last_minute_bid(lid, args.market_id, args.max, dry_run=args.dry_run)


def cmd_bid_plan(args):
    if args.clear:
        state.clear_bid_plan()
        print("Bid plan cleared.")
        return
    if args.market_id and args.max is not None:
        state.add_bid_target(args.market_id, args.max)
        events.emit("bid-plan", f"Last-minute bid scheduled: {args.market_id}",
                    detail={"max": f"{args.max:,}"}, status="plan")
    _print_json(state.load_bid_plan())


def cmd_bid_run(args):
    from . import bidding
    lid, _ = FantasyClient().default_ids()
    bidding.run_bid_plan(lid, dry_run=args.dry_run)


def cmd_due(args):
    """Fire due reminders. Meant for a scheduler (every minute)."""
    now = datetime.now(timezone.utc)
    due = state.due_reminders(now)
    if not due:
        return  # nothing to fire; silent for cron
    for r in due:
        print(f"🔔 {r['message']}  (event: {r['event_at']})")
        state.mark_reminder_fired(r["key"])


def cmd_watch(args):
    """Open the monitoring UI ('mission control') and, optionally, trigger a run.

    - `--run`      triggers the deterministic agent (fantasybot agent --execute).
    - `--hermes`   triggers the Hermes brain with the skill (LLM), if installed.
    Without flags, it just monitors: you'll see the next cron cycle live.
    """
    import threading
    import webbrowser
    from . import monitor

    srv, url = monitor.serve(args.host, args.port, background=True,
                             run_mode="hermes" if args.hermes else "agent")
    print(f"Mission Control at {url}")
    if args.host in ("127.0.0.1", "localhost"):
        print(f"  (remote VPS: tunnel  ssh -L {args.port}:127.0.0.1:{args.port} <server>)")

    def fire():
        time.sleep(1.2)  # let the UI connect the stream before starting
        # Goes through monitor.trigger() so this can't race a concurrent
        # "Launch agent" button click (or a second watch process) into
        # firing two real agent cycles at once.
        monitor.trigger("hermes" if args.hermes else "agent")

    if args.run or args.hermes:
        threading.Thread(target=fire, daemon=True).start()
    if not args.no_open:
        try:
            webbrowser.open(url)
        except Exception:
            pass

    print("Ctrl+C to exit.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        srv.shutdown()
        print("\nSee you later.")


def cmd_tasks(args):
    if args.done is not None:
        state.complete_task(args.done)
        print(f"Task #{args.done} marked as done.")
        return
    pend = state.pending_tasks()
    if not pend:
        print("No pending tasks.")
    for t in pend:
        due = f" (before {t['due']})" if t.get("due") else ""
        print(f"  #{t['id']} {t['text']}{due}")


def build_parser():
    p = argparse.ArgumentParser(prog="fantasybot", description="LALIGA Fantasy agent")
    sub = p.add_subparsers(dest="cmd", required=True)

    lp = sub.add_parser("login", help="OAuth login (2 steps)")
    lp.add_argument("redirect", nargs="?", help="authredirect:// URL from step 2")
    lp.set_defaults(func=cmd_login)

    for name, func in [("refresh", cmd_refresh), ("me", cmd_me),
                       ("leagues", cmd_leagues), ("team", cmd_team),
                       ("lineup", cmd_lineup), ("market", cmd_market),
                       ("trends", cmd_trends)]:
        sub.add_parser(name, help=name).set_defaults(func=func)

    op = sub.add_parser("onces", help="a team's likely starting XI")
    op.add_argument("team", help="team slug, e.g. real-madrid")
    op.set_defaults(func=cmd_onces)

    fp = sub.add_parser("flip", help="resale opportunities")
    fp.add_argument("--horizon", type=int, default=flip.DEFAULT_HORIZON)
    fp.add_argument("--json", action="store_true", help="JSON output")
    fp.set_defaults(func=cmd_flip)

    opt = sub.add_parser("optimize", help="best lineup (--apply to save)")
    opt.add_argument("--apply", action="store_true", help="save the lineup")
    opt.add_argument("--json", action="store_true", help="JSON output (incl. payload)")
    opt.set_defaults(func=cmd_optimize)

    nd = sub.add_parser("needs", help="squad gaps and suggested signings")
    nd.add_argument("--days", type=int, default=None,
                    help="days until the matchday (for urgency)")
    nd.add_argument("--json", action="store_true", help="JSON output")
    nd.set_defaults(func=cmd_needs)

    ag = sub.add_parser("agent", help="full agent review (like a human)")
    ag.add_argument("--days", type=int, default=None,
                    help="days until the matchday (for urgency)")
    ag.add_argument("--execute", action="store_true",
                    help="actually ACT (line up and bid); without it, only plans")
    ag.add_argument("--json", action="store_true",
                    help="JSON output of the report (for Hermes)")
    ag.set_defaults(func=cmd_agent)

    wt = sub.add_parser("watch", help="live monitoring UI (mission control)")
    wt.add_argument("--run", action="store_true",
                    help="trigger the deterministic agent (agent --execute)")
    wt.add_argument("--hermes", action="store_true",
                    help="trigger the Hermes brain with the skill (LLM)")
    wt.add_argument("--port", type=int, default=9137)
    wt.add_argument("--host", default="127.0.0.1")
    wt.add_argument("--no-open", action="store_true", help="don't open the browser")
    wt.set_defaults(func=cmd_watch)

    tk = sub.add_parser("tasks", help="pending task list")
    tk.add_argument("--done", type=int, default=None, metavar="ID",
                    help="mark a task as done")
    tk.set_defaults(func=cmd_tasks)

    sub.add_parser("due", help="fire due reminders (for cron)").set_defaults(func=cmd_due)

    sl = sub.add_parser("sell", help="list a player for sale (playerId price)")
    sl.add_argument("player_id")
    sl.add_argument("price", type=int)
    sl.set_defaults(func=cmd_sell)

    bd = sub.add_parser("bid", help="bid on a market player (marketId amount)")
    bd.add_argument("market_id")
    bd.add_argument("amount", type=int)
    bd.set_defaults(func=cmd_bid)

    cb = sub.add_parser("cancel-bid", help="cancel a bid (marketId bidId)")
    cb.add_argument("market_id")
    cb.add_argument("bid_id")
    cb.set_defaults(func=cmd_cancel_bid)

    cl = sub.add_parser("clause", help="pay a player's buyout clause (playerId amount)")
    cl.add_argument("player_id")
    cl.add_argument("amount", type=int)
    cl.set_defaults(func=cmd_clause)

    sn = sub.add_parser("bid-now", help="one-off last-minute bid (marketId max)")
    sn.add_argument("market_id")
    sn.add_argument("max", type=int, help="bid cap")
    sn.add_argument("--dry-run", action="store_true")
    sn.set_defaults(func=cmd_bid_now)

    sp = sub.add_parser("bid-plan", help="schedule last-minute bids (marketId cap)")
    sp.add_argument("market_id", nargs="?")
    sp.add_argument("max", type=int, nargs="?", help="bid cap")
    sp.add_argument("--clear", action="store_true")
    sp.set_defaults(func=cmd_bid_plan)

    sr = sub.add_parser("bid-run", help="run the bid plan at close (for cron)")
    sr.add_argument("--dry-run", action="store_true")
    sr.set_defaults(func=cmd_bid_run)

    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        args.func(args)
    except (FantasyError, auth.AuthError) as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
