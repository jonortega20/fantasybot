"""Squad needs + signings advisor.

Detects positions where you're short (e.g. a single goalkeeper) and looks for
candidates in the market to sign, prioritizing those who will start for their team.

Includes URGENCY logic: the fewer days left until the matchday, the more willing
to pay a little above the ideal price (if you wait, another one may not show up in
time). With several days ahead, there's no rush.
"""

from ..matching import match_name, POS
from ..sources.lineups import probable_lineups

# Recommended minimum per position (1 starter + rotation/injury margin).
MIN_SQUAD = {"POR": 2, "DEF": 5, "MED": 5, "DEL": 3}


def squad_counts(team):
    counts = {"POR": 0, "DEF": 0, "MED": 0, "DEL": 0}
    for p in team["players"]:
        pos = POS.get(p["playerMaster"]["positionId"])
        if pos:
            counts[pos] += 1
    return counts


def gaps(team):
    """Positions below the recommended minimum, with how many are missing."""
    counts = squad_counts(team)
    return {pos: MIN_SQUAD[pos] - counts[pos]
            for pos in counts if counts[pos] < MIN_SQUAD[pos]}


def urgency_multiplier(days_to_matchday):
    """How much extra over the ideal price we accept based on how close the matchday is.

    Far (>=5 days): 1.0 (no rush). Close: up to ~1.15 on matchday.
    None = unknown → 1.0 (cautious).
    """
    if days_to_matchday is None:
        return 1.0
    if days_to_matchday >= 5:
        return 1.0
    # from 5 days (1.0) to 0 days (1.15), linear
    return round(1.0 + (5 - max(0, days_to_matchday)) * 0.03, 3)


def candidates(client, league_id, position, prob_index=None, money=None, owned=None):
    """Market candidates in a position, sorted by starting probability.

    Returns dicts with buy price, route (system/buyout) and starting prob.
    Excludes players you already own (`owned` = set of playerMaster.id).
    """
    if prob_index is None:
        prob_index = probable_lineups()
    owned = owned or set()
    pos_id = {v: k for k, v in POS.items()}[position]

    out = []
    for el in client.market(league_id):
        pm = el["playerMaster"]
        if pm.get("positionId") != pos_id:
            continue
        if pm.get("id") in owned:
            continue  # already yours
        clause = sale = None
        if el["discr"] == "marketPlayerLeague":
            via, price = "SISTEMA", el.get("salePrice") or pm.get("marketValue")
        else:
            clause = el.get("playerTeam", {}).get("buyoutClause")
            # A player another manager has listed can simply be BID for, at his sale
            # price. That is nearly always cheaper than his clause (~1.67x value) and
            # available now instead of when the lock expires. Offering only the clause
            # here was overpricing every signing from another squad.
            sale = el.get("salePrice") if el.get("status") == "on_sale" else None
            if sale and (clause is None or sale < clause):
                via, price = "PUJA", sale
            else:
                via, price = "CLAUSULA", clause
        if not price:
            continue
        info = match_name(pm.get("nickname", ""), pm.get("name", ""), prob_index)
        prob = info.get("prob") if info else None
        disponible = pm.get("playerStatus", "ok") == "ok"
        if info and (info.get("lesionado") or not info.get("disponible", True)):
            disponible = False
        out.append({
            "nombre": pm.get("nickname") or pm.get("name"),
            "market_id": el["id"],
            "player_id": pm.get("id"),
            "via": via,
            "price": price,
            "prob": prob,
            "disponible": disponible,
            "valor": pm.get("marketValue"),
            "affordable": (money is None or price <= money),
            # both routes, so the caller can see what the alternative would have cost
            "clause": clause,
            "sale_price": sale,
            "expires": el.get("expirationDate"),
        })
    # sort: available starters first, then by probability and value
    out.sort(key=lambda c: (c["disponible"], c["prob"] or 0, c["valor"] or 0),
             reverse=True)
    return out


def advise(client, league_id, team, days_to_matchday=None):
    """Report: squad gaps and the best candidates to fill them."""
    prob_index = probable_lineups()
    mult = urgency_multiplier(days_to_matchday)
    money = team["teamMoney"]
    owned = {p["playerMaster"].get("id") for p in team["players"]}
    report = {"gaps": gaps(team), "urgency_multiplier": mult, "suggestions": {}}
    for pos in report["gaps"]:
        cands = candidates(client, league_id, pos, prob_index, money, owned)
        for c in cands:
            # recommended cap: the price, raised by urgency when there is bidding
            # involved. A clause is a fixed amount — urgency cannot change it.
            c["max_bid"] = (round(c["price"] * mult)
                            if c["via"] in ("SISTEMA", "PUJA") else c["price"])
        report["suggestions"][pos] = cands
    return report
