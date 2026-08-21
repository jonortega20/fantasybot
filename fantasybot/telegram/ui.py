"""Telegram message formatting, emojis, and inline keyboard builders."""

from typing import List, Dict, Any, Optional
from ..matching import POS


def main_menu_keyboard(logged_in: bool = True) -> Dict[str, Any]:
    """Builds the main interactive keyboard for Telegram."""
    if not logged_in:
        return {
            "inline_keyboard": [
                [{"text": "🔐 Iniciar Sesión en LaLiga Fantasy", "callback_data": "cmd_login"}],
                [{"text": "📖 Tutorial Paso a Paso (Móvil / PC)", "callback_data": "cmd_tutorial"}],
                [{"text": "ℹ️ Ayuda & Comandos", "callback_data": "cmd_help"}]
            ]
        }

    return {
        "inline_keyboard": [
            [
                {"text": "📋 Mi Plantilla", "callback_data": "cmd_team"},
                {"text": "⚔️ Rivales & Finanzas", "callback_data": "cmd_rivals"},
            ],
            [
                {"text": "📊 Histórico & Flips", "callback_data": "cmd_history"},
                {"text": "🛒 Mercado en Vivo", "callback_data": "cmd_market"},
            ],
            [
                {"text": "⚽ Alineación Óptima", "callback_data": "cmd_lineup"},
                {"text": "🔄 Oportunidades (Flip)", "callback_data": "cmd_flip"},
            ],
            [
                {"text": "🚀 Autopilot Completo", "callback_data": "cmd_autopilot"},
                {"text": "⚙️ Ajustes & Alertas", "callback_data": "cmd_settings"},
            ],
            [
                {"text": "🏆 Mis Ligas / Cambiar", "callback_data": "cmd_leagues"},
                {"text": "👤 Mi Perfil", "callback_data": "cmd_me"},
            ],
            [
                {"text": "💡 Enviar Sugerencia", "callback_data": "cmd_sugerencia_btn"},
                {"text": "🐛 Reportar Bug", "callback_data": "cmd_bug_btn"},
            ],
            [
                {"text": "📖 Tutorial Paso a Paso", "callback_data": "cmd_tutorial"},
                {"text": "ℹ️ Ayuda & Comandos", "callback_data": "cmd_help"},
            ]
        ]
    }


def lineup_keyboard(can_apply: bool = False) -> Dict[str, Any]:
    rows = []
    if can_apply:
        rows.append([{"text": "🚀 Aplicar Alineación Óptima en LaLiga", "callback_data": "action_apply_lineup"}])
    rows.append([{"text": "🔙 Menú Principal", "callback_data": "cmd_menu"}])
    return {"inline_keyboard": rows}


def flips_keyboard(flips: List[Dict[str, Any]]) -> Dict[str, Any]:
    rows = []
    for f in flips[:5]:
        mid = f.get("market_id")
        amt = f.get("buy_price")
        name = f.get("nombre")
        via = f.get("via", "SISTEMA")
        pid = f.get("player_id")
        if via == "SISTEMA" and mid and amt:
            rows.append([{"text": f"💰 Pujar por {name} ({amt:,} €)", "callback_data": f"bid_{mid}_{amt}"}])
        elif via == "CLAUSULA" and pid and amt:
            rows.append([{"text": f"⚡ Clausulazo a {name} ({amt:,} €)", "callback_data": f"clause_{pid}_{amt}"}])
    if any(f.get("via") == "SISTEMA" for f in flips):
        rows.append([{"text": "🚀 Auto-Pujar por Flips de Mercado", "callback_data": "action_auto_bids"}])
    rows.append([{"text": "🔙 Menú Principal", "callback_data": "cmd_menu"}])
    return {"inline_keyboard": rows}


def team_keyboard() -> Dict[str, Any]:
    return {
        "inline_keyboard": [
            [{"text": "🏷 Poner Jugador en Venta", "callback_data": "cmd_sell_menu"}],
            [{"text": "🔙 Menú Principal", "callback_data": "cmd_menu"}]
        ]
    }


def sell_player_keyboard(players: List[Dict[str, Any]]) -> Dict[str, Any]:
    rows = []
    for p in players:
        pm = p.get("playerMaster", {})
        pid = pm.get("id")
        name = pm.get("nickname") or pm.get("name") or "Jugador"
        val = pm.get("marketValue") or 0
        if pid:
            rows.append([{"text": f"🏷 Vender {name} ({val:,} €)", "callback_data": f"sell_{pid}"}])
    rows.append([{"text": "🔙 Volver a Mi Plantilla", "callback_data": "cmd_team"}])
    return {"inline_keyboard": rows}


def settings_keyboard(settings: Dict[str, bool]) -> Dict[str, Any]:
    f_txt = "ACTIVADAS 🔔" if settings.get("notify_flips") else "DESACTIVADAS 🔕"
    l_txt = "ACTIVADO ⏰" if settings.get("notify_lineup") else "DESACTIVADO 🔕"
    a_txt = "ACTIVADO 🤖" if settings.get("auto_lineup") else "DESACTIVADO ⏸"
    return {
        "inline_keyboard": [
            [{"text": f"Alertas Flips Mercado: {f_txt}", "callback_data": "toggle_notify_flips"}],
            [{"text": f"Recordatorio Jornada: {l_txt}", "callback_data": "toggle_notify_lineup"}],
            [{"text": f"Auto-Alinear Automático: {a_txt}", "callback_data": "toggle_auto_lineup"}],
            [{"text": "🔙 Menú Principal", "callback_data": "cmd_menu"}]
        ]
    }


def leagues_keyboard(leagues: List[Dict[str, Any]], active_lid: Optional[str] = None) -> Dict[str, Any]:
    rows = []
    for lg in leagues:
        lid = str(lg.get("id"))
        name = lg.get("name", "Liga")
        is_active = (str(lid) == str(active_lid))
        prefix = "✅ " if is_active else "🏆 "
        rows.append([{"text": f"{prefix}{name}", "callback_data": f"set_league_{lid}"}])
    rows.append([{"text": "🔙 Menú Principal", "callback_data": "cmd_menu"}])
    return {"inline_keyboard": rows}


def back_to_menu_keyboard() -> Dict[str, Any]:
    return {
        "inline_keyboard": [
            [{"text": "🔙 Menú Principal", "callback_data": "cmd_menu"}]
        ]
    }


def rivals_keyboard(rivals: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Creates inline buttons for each rival to inspect their detailed squad."""
    rows = []
    current_row = []
    for idx, r in enumerate(rivals, 1):
        name = r.get("manager_name", f"Manager {idx}")[:12]
        current_row.append({
            "text": f"#{idx} {name}",
            "callback_data": f"rival_{r.get('manager_id')}"
        })
        if len(current_row) == 2:
            rows.append(current_row)
            current_row = []
    if current_row:
        rows.append(current_row)

    rows.append([{"text": "🔙 Menú Principal", "callback_data": "cmd_menu"}])
    return {"inline_keyboard": rows}


def history_keyboard(managers: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Creates inline buttons for each manager to inspect their trading flips."""
    rows = []
    current_row = []
    for idx, m in enumerate(managers, 1):
        name = m.get("manager_name", f"Manager {idx}")[:12]
        current_row.append({
            "text": f"#{idx} {name}",
            "callback_data": f"history_{m.get('manager_id')}"
        })
        if len(current_row) == 2:
            rows.append(current_row)
            current_row = []
    if current_row:
        rows.append(current_row)

    rows.append([{"text": "🔙 Menú Principal", "callback_data": "cmd_menu"}])
    return {"inline_keyboard": rows}


# --- Text formatters ---

def format_team(team_data: Dict[str, Any]) -> str:
    lines = [
        f"📋 <b>Mi Plantilla: {team_data.get('name', 'Equipo')}</b>",
        f"💰 <b>Valor:</b> {team_data.get('teamValue', 0):,} € | <b>Saldo:</b> {team_data.get('teamMoney', 0):,} €",
        f"👥 <b>Jugadores:</b> {len(team_data.get('players', []))}\n",
        "<code>POS JUGADOR            VALOR      CLÁUSULA</code>",
        "<code>" + "─" * 46 + "</code>"
    ]
    for p in sorted(team_data.get("players", []), key=lambda x: -(x.get("playerMaster", {}).get("marketValue") or 0)):
        pm = p.get("playerMaster") or {}
        pos = POS.get(pm.get("positionId"), "?")
        name = (pm.get("nickname") or pm.get("name") or "Unknown")[:16]
        mv = pm.get("marketValue") or 0
        clause = p.get("buyoutClause") or 0
        lines.append(f"<code>{pos:<4}{name:<17}{mv:>11,}{clause:>14,}</code>")

    return "\n".join(lines)


def format_rivals_summary(rivals: List[Dict[str, Any]]) -> str:
    events_count = rivals[0].get("tracked_events_count", 0) if rivals else 0
    d_from = rivals[0].get("tracked_from_date", "?") if rivals else "?"
    d_to = rivals[0].get("tracked_to_date", "?") if rivals else "?"

    lines = [
        "⚔️ <b>Finanzas y Presupuesto de Rivales</b>",
        f"📦 <i>Historial: {events_count} operaciones ({d_from} a {d_to})</i>\n",
        "<code>#  MANAGER        EQUIPO      NETO    EST. CASH</code>",
        "<code>" + "─" * 47 + "</code>"
    ]
    for r in rivals:
        is_me = " (tú)" if r["is_me"] else ""
        name = (r["manager_name"][:11] + is_me)[:13]
        pos = f"#{r['position']}" if r["position"] else "-"
        tv = r["team_value"] // 1_000_000
        net = r["net_profit"] // 1_000_000
        cash = r["estimated_balance"] // 1_000_000
        lines.append(f"<code>{pos:<3}{name:<14}{tv:>5}M{net:>+6}M{cash:>8}M</code>")

    lines.append("\n<i>💡 Pulsa en cualquier rival abajo para ver su plantilla y blindajes.</i>")
    return "\n".join(lines)


def format_rival_detail(r: Dict[str, Any]) -> str:
    profit_sign = "+" if r["net_profit"] >= 0 else ""
    lines = [
        f"👤 <b>Manager: {r['manager_name']}</b> (#{r['position']} - {r['points']} pts)",
        f"💰 <b>Valor Equipo:</b> {r['team_value']:,} € | <b>Saldo Est.:</b> ~{r['estimated_balance']:,} €",
        f"🛒 <b>Compras:</b> {r['purchases']:,} € | <b>Ventas:</b> {r['sales']:,} € (Neto: {profit_sign}{r['net_profit']:,} €)\n",
        "<code>JUGADOR          POS       COMPRA        VALOR   PROFIT/LOSS</code>",
        "<code>" + "─" * 60 + "</code>"
    ]
    for p in r.get("players", []):
        bought = f"{p['bought_price']:,}" if not p["is_initial"] else "(Inicial)"
        diff_sign = "+" if p["diff"] >= 0 else ""
        gain = f"{diff_sign}{p['diff']:,}" if not p["is_initial"] else "-"
        lines.append(f"<code>{p['name'][:14]:<15}{p['pos']:<4}{bought:>12}{p['market_value']:>13,}{gain:>16}</code>")

    return "\n".join(lines)


def format_history_summary(report: Dict[str, Any]) -> str:
    managers = report.get("managers", [])
    lines = [
        "📊 <b>Ranking de Especulación y Rentabilidad (Flips)</b>",
        f"📦 <i>{report.get('tracked_events', 0)} operaciones ({report.get('tracked_from')} a {report.get('tracked_to')})</i>\n",
        "<code>#  MANAGER        TOTAL P&L   FLIPS  WIN%   AVG ROI</code>",
        "<code>" + "─" * 49 + "</code>"
    ]
    for idx, m in enumerate(managers, 1):
        is_me = " (tú)" if m["is_me"] else ""
        name = (m["manager_name"][:11] + is_me)[:13]
        tot = m["total_pnl"] // 1_000_000
        flips = m["total_trades"]
        win = f"{m['win_rate_pct']:.0f}%" if flips else "-"
        roi = f"{m['avg_roi_pct']:+.1f}%" if flips else "-"
        lines.append(f"<code>#{idx:<2}{name:<14}{tot:>+7}M{flips:>6}{win:>7}{roi:>9}</code>")

    lines.append("\n<i>💡 Pulsa en cualquier manager para ver su historial de compra-venta.</i>")
    return "\n".join(lines)


def format_manager_history(m: Dict[str, Any]) -> str:
    tot_sign = "+" if m["total_pnl"] >= 0 else ""
    real_sign = "+" if m["realized_profit"] >= 0 else ""
    unreal_sign = "+" if m["unrealized_profit"] >= 0 else ""

    lines = [
        f"📊 <b>Historial de Trading: {m['manager_name']}</b> (#{m['position']} - {m['points']} pts)",
        f"📈 <b>P&L Total:</b> {tot_sign}{m['total_pnl']:,} €",
        f"  • Realizado (Flips cerrados): {real_sign}{m['realized_profit']:,} €",
        f"  • Latente (En plantilla): {unreal_sign}{m['unrealized_profit']:,} €\n",
    ]

    open_h = m.get("open_holdings", [])
    if open_h:
        lines.append("🟢 <b>Posiciones en Plantilla (Ganancia Latente):</b>")
        for o in open_h:
            diff_sign = "+" if o["unrealized_profit"] >= 0 else ""
            lines.append(f"  • <b>{o['name']}</b> ({o['pos']}): Comprado por {o['buy_price']:,} € → Vale {o['market_value']:,} € (<b>{diff_sign}{o['unrealized_profit']:,} €</b> | {o['roi_pct']:+.1f}%)")
        lines.append("")

    flips = m.get("completed_flips", [])
    if flips:
        lines.append(f"🔄 <b>Flips Cerrados ({len(flips)} operaciones | {m['win_rate_pct']:.1f}% Win):</b>")
        for f in flips[:10]:
            diff_sign = "+" if f["profit"] >= 0 else ""
            lines.append(f"  • <b>{f['name']}</b> ({f['pos']}): {f['buy_price']:,} → {f['sell_price']:,} (<b>{diff_sign}{f['profit']:,} €</b> | {f['roi_pct']:+.1f}%)")
        if len(flips) > 10:
            lines.append(f"  <i>...y {len(flips) - 10} operaciones más.</i>")
        lines.append("")

    init_s = m.get("initial_sales", [])
    if init_s:
        lines.append(f"📦 <b>Ventas de Plantilla Inicial ({len(init_s)} jugadores):</b>")
        for s in init_s[:6]:
            lines.append(f"  • {s['name']} ({s['pos']}) vendido por {s['sell_price']:,} € ({s['sell_date']})")
        if len(init_s) > 6:
            lines.append(f"  <i>...y {len(init_s) - 6} ventas más.</i>")

    return "\n".join(lines)


def format_market(market_items: List[Dict[str, Any]]) -> str:
    lines = [
        "🛒 <b>Mercado de Fichajes en Vivo</b>\n",
        "<code>POS JUGADOR            PRECIO   CLÁUSULA</code>",
        "<code>" + "─" * 44 + "</code>"
    ]
    for it in sorted(market_items, key=lambda x: -(x.get("price") or x.get("playerMaster", {}).get("marketValue") or 0))[:20]:
        pm = it.get("playerMaster") or {}
        pos = POS.get(pm.get("positionId"), "?")
        name = (pm.get("nickname") or pm.get("name") or "Unknown")[:16]
        price = it.get("price") or pm.get("marketValue") or 0
        clause = it.get("buyoutClause") or pm.get("marketValue") or 0
        lines.append(f"<code>{pos:<4}{name:<17}{price:>10,}{clause:>13,}</code>")

    return "\n".join(lines)


def format_trends(trends_list: List[Dict[str, Any]]) -> str:
    up = sorted([p for p in trends_list if p.get("tendencia", 0) > 0], key=lambda x: -x["tendencia"])[:7]
    down = sorted([p for p in trends_list if p.get("tendencia", 0) < 0], key=lambda x: x["tendencia"])[:7]

    lines = ["📈 <b>Tendencias de Mercado (Subidas y Bajadas)</b>\n", "🟢 <b>Mayores Subidas:</b>"]
    for p in up:
        lines.append(f"  • <b>{p.get('nombre', 'Jugador')}</b> ({p.get('equipo', '')}): +{p.get('tendencia', 0):,} €/día")

    lines.append("\n🔴 <b>Mayores Bajadas:</b>")
    for p in down:
        lines.append(f"  • <b>{p.get('nombre', 'Jugador')}</b> ({p.get('equipo', '')}): {p.get('tendencia', 0):,} €/día")

    return "\n".join(lines)


def format_tutorial() -> str:
    return (
        "📖 <b>Tutorial: Cómo conectar tu cuenta paso a paso</b>\n\n"
        "La autenticación es 100% oficial mediante <b>OAuth2 y PKCE</b> de LaLiga. "
        "El bot nunca ve tu contraseña.\n\n"
        "─────────────────────────\n"
        "📱 <b>MÉTODO 1: DESDE EL MÓVIL (Recomendado)</b>\n"
        "1️⃣ Pulsa en /login y haz clic en <b>Iniciar Sesión Oficial en LaLiga</b>.\n"
        "2️⃣ Inicia sesión con tu cuenta (Google, Apple o Email).\n"
        "3️⃣ Al terminar, el navegador intentará abrir la app y se quedará en blanco o mostrará un mensaje de alerta.\n"
        "4️⃣ <b>Toca arriba en la barra de direcciones del navegador</b> y copia la URL completa (empieza por <code>authredirect://...</code>).\n"
        "5️⃣ <b>Pega ese enlace aquí en el chat</b> y el bot te conectará al instante.\n\n"
        "─────────────────────────\n"
        "💻 <b>MÉTODO 2: DESDE EL ORDENADOR (Chrome / Edge)</b>\n"
        "1️⃣ Abre el enlace de /login en tu PC.\n"
        "2️⃣ Pulsa la tecla <b>F12</b> (o clic derecho → Inspeccionar) y ve a la pestaña <b>Red (Network)</b>.\n"
        "3️⃣ Marca la casilla <b>Preserve log</b> (Conservar registro).\n"
        "4️⃣ Inicia sesión con tu cuenta.\n"
        "5️⃣ En la lista de peticiones verás una fila en rojo que dice <code>authredirect://... (canceled)</code>.\n"
        "6️⃣ Haz <b>clic derecho sobre esa fila → Copiar → Copiar dirección del enlace</b>.\n"
        "7️⃣ <b>Pega el enlace en el chat</b> de Telegram.\n\n"
        "<i>✅ ¡Una vez conectado, la sesión dura 90 días y se renueva automáticamente!</i>"
    )
