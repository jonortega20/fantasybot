"""Background notification and automated alerts scheduler for Telegram users."""

import logging
import threading
import time
from typing import Dict, Any, Set

from . import sessions
from ..strategy import flip as flip_mod
from ..strategy import lineup as lineup_opt
from .. import agent as agent_mod
from .. import execute as execute_mod

logger = logging.getLogger("fantasybot.notifications")

# Track sent notifications to prevent spamming the same flip
_SEEN_MARKET_FLIPS: Dict[int, Set[str]] = {}


def start_notification_worker(bot_instance):
    """Starts the background worker thread for user notifications."""
    t = threading.Thread(target=_notification_loop, args=(bot_instance,), daemon=True)
    t.start()
    return t


def _notification_loop(bot):
    logger.info("Notification worker loop started.")
    time.sleep(10)  # Initial grace period

    while bot.running:
        try:
            chat_ids = sessions.get_all_logged_in_chat_ids()
            for chat_id in chat_ids:
                try:
                    _check_user_notifications(bot, chat_id)
                except Exception as e:
                    logger.debug("Error checking notifications for chat_id %d: %s", chat_id, e)
        except Exception as e:
            logger.error("Error in notification worker loop: %s", e)

        # Check every 15 minutes
        for _ in range(90):
            if not bot.running:
                break
            time.sleep(10)


def _check_user_notifications(bot, chat_id: int):
    settings = sessions.get_user_settings(chat_id)
    if not any(settings.values()):
        return

    client = sessions.get_client_for_user(chat_id)
    try:
        lid, tid = client.default_ids()
    except Exception:
        return

    # 1. Market Flips Notification
    if settings.get("notify_flips"):
        try:
            team_data = client.team(lid, tid)
            owned = {p.get("playerMaster", {}).get("id") for p in team_data.get("players", []) if p.get("playerMaster", {}).get("id")}
            flips = flip_mod.opportunities(client, lid, owned=owned)
            profitable = [f for f in flips if f.get("via") == "SISTEMA" and f.get("margin", 0) > 200_000 and f.get("margin_pct", 0) >= 3.0]

            seen = _SEEN_MARKET_FLIPS.setdefault(chat_id, set())
            new_flips = [f for f in profitable if f["market_id"] not in seen]

            if new_flips:
                for f in new_flips:
                    seen.add(f["market_id"])

                lines = ["🔔 <b>¡Nuevas Oportunidades de Reventa (Flip) en tu Mercado!</b>\n"]
                for f in new_flips[:4]:
                    lines.append(
                        f"  • <b>{f['nombre']}</b> ({f['pos']}): Compra a {f['buy_price']:,} € → "
                        f"Proy: {f['proyeccion']:,} € (<b>+{f['margin']:,} €</b> | +{f['margin_pct']}%)"
                    )
                lines.append("\n<i>💡 Pulsa en Oportunidades (Flip) para pujar por ellos al instante.</i>")
                bot.send_message(chat_id, "\n".join(lines))
        except Exception as e:
            logger.debug("Error checking market flips for %d: %s", chat_id, e)

    # 2. Auto-Lineup Automation
    if settings.get("auto_lineup"):
        try:
            team_data = client.team(lid, tid)
            best = lineup_opt.optimize(team_data)
            current_ids = agent_mod._current_xi_ids(client, tid)
            res = execute_mod.apply_lineup(client, tid, best, current_ids, dry_run=False)
            if res.get("changed"):
                d, m, f = best["formation"]
                bot.send_message(
                    chat_id,
                    f"🤖 <b>Auto-Alinear Ejecutado:</b>\n\n"
                    f"Tu alineación ha sido actualizada automáticamente al <b>XI Óptimo ({d}-{m}-{f})</b> para la próxima jornada. ⚽"
                )
        except Exception as e:
            logger.debug("Error in auto-lineup for %d: %s", chat_id, e)
