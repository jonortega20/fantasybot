"""FLIP decision engine (buy to resell).

Cross-references the league market with value trends and estimates the resale
margin. Two routes: SISTEMA (you pay ~value) and CLAUSULA (you pay the ~1.67x premium).
Returns data; the CLI does the formatting.
"""

from ..matching import match_name, POS
from ..sources.market_trends import trends_index

# Model parameters (conservative and transparent).
DEFAULT_HORIZON = 7    # days to project
DAMPING = 0.5          # dampens the extrapolation (trends revert)
SELL_COMMISSION = 0.0  # sale commission (adjustable)
SANITY_MAX_DIFF = 0.35  # discard matches if the value differs >35% from the real one


def daily_rate(trend) -> float:
    """Daily rate of change, average of the 3d and 7d windows."""
    v, v3, v7 = trend.get("valor"), trend.get("valor3"), trend.get("valor7")
    rates = []
    if v is not None and v3:
        rates.append((v - v3) / 3.0)
    if v is not None and v7:
        rates.append((v - v7) / 7.0)
    return sum(rates) / len(rates) if rates else 0.0


def _falling_now(trend) -> bool:
    """True when the FRESH signal says the player is turning down, regardless of the older
    3/7-day windows: futbolfantasy's own `tendencia` is negative, or the value fell over
    the last day (valor < valor1). This is the same `tendencia` the sell engine trusts."""
    v, v1, tend = trend.get("valor"), trend.get("valor1"), trend.get("tendencia")
    if tend is not None and tend < 0:
        return True
    return v is not None and bool(v1) and v < v1


def project(trend, horizon) -> float:
    """Projected value at `horizon` days. The 3/7-day rate LAGS: a player can rise all
    week yet peak and turn down today. When the fresh signal says he's already falling we
    must NOT extrapolate the stale rise (that buys him at the top and reads as a bogus
    "+1%" flip), so a positive rate is suppressed in that case."""
    rate = daily_rate(trend)
    if rate > 0 and _falling_now(trend):
        rate = 0.0
    return (trend.get("valor") or 0) + rate * horizon * DAMPING


def evaluate(element, index, horizon):
    """Evaluate a market element as a flip. None if it doesn't match or is dubious."""
    pm = element["playerMaster"]
    trend = match_name(pm.get("nickname", ""), pm.get("name", ""), index)
    if not trend or not trend.get("valor"):
        return None

    fantasy_value = pm.get("marketValue")
    if fantasy_value and abs(trend["valor"] - fantasy_value) / fantasy_value > SANITY_MAX_DIFF:
        return None  # name match probably wrong

    if element["discr"] == "marketPlayerLeague":
        via, buy_price = "SISTEMA", element.get("salePrice") or trend["valor"]
        owner = "Mercado Libre"
    else:
        via = "CLAUSULA"
        buy_price = element.get("playerTeam", {}).get("buyoutClause")
        if not buy_price:
            return None
        owner = (
            element.get("sellerTeam", {}).get("manager", {}).get("managerName")
            or element.get("playerTeam", {}).get("manager", {}).get("managerName")
            or "Rival"
        )

    proj = project(trend, horizon)
    margin = proj * (1 - SELL_COMMISSION) - buy_price
    return {
        "nombre": pm.get("nickname") or pm.get("name"),
        "market_id": element["id"],
        "player_id": pm.get("id"),
        "pos": POS.get(pm.get("positionId"), "?"),
        "via": via,
        "owner": owner,
        "valor_actual": trend["valor"],
        "buy_price": buy_price,
        "proyeccion": round(proj),
        "margin": round(margin),
        "margin_pct": round(margin / buy_price * 100, 1) if buy_price else 0,
        "rate_dia": round(daily_rate(trend)),
        "tendencia": trend.get("tendencia"),
    }


def opportunities(client, league_id, horizon=DEFAULT_HORIZON, owned=None):
    """List of flip opportunities sorted by margin %, highest to lowest.

    `owned` is the set of playerMaster ids already in the squad; they're excluded, so
    the agent never suggests "signing" a player you already own (e.g. one you've listed
    on the market, which otherwise shows up as a buyout/system target).
    """
    index = trends_index()
    owned = owned or set()
    ops = [evaluate(el, index, horizon) for el in client.market(league_id)]
    ops = [o for o in ops if o and o["player_id"] not in owned]
    ops.sort(key=lambda r: -r["margin_pct"])
    return ops
