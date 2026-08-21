"""Telegram Bot daemon for LaLiga Fantasy.

Zero external pip dependencies: built with Python standard library (urllib.request, json, threading).
"""

import json
import logging
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, Any, Optional

from .. import auth
from .. import config
from .. import execute as execute_mod
from .. import agent as agent_mod
from ..strategy import rivals as rivals_mod
from ..strategy import history as history_mod
from ..strategy import flip as flip_mod
from ..strategy import lineup as lineup_opt
from ..sources.market_trends import market_trends
from . import sessions
from . import ui

logger = logging.getLogger("fantasybot.telegram")


class TelegramBot:
    """Zero-dependency Telegram Bot API client and polling daemon."""

    def __init__(self, token: str):
        self.token = token
        self.base_url = f"https://api.telegram.org/bot{token}"
        self.offset = 0
        self.running = False

    def _api_call(self, method: str, data: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        url = f"{self.base_url}/{method}"
        headers = {"User-Agent": "FantasyBot-Telegram/1.0"}
        body = None
        if data is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(data).encode("utf-8")

        req = urllib.request.Request(url, data=body, headers=headers, method="POST" if body else "GET")
        try:
            with urllib.request.urlopen(req, timeout=35) as resp:
                res = json.loads(resp.read().decode("utf-8"))
                if res.get("ok"):
                    return res.get("result")
                return None
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="ignore")
            logger.error("Telegram API Error %d %s: %s", e.code, e.reason, err_body)
            return None
        except Exception as e:
            logger.error("Network error on Telegram API %s: %s", method, e)
            return None

    def send_message(
        self,
        chat_id: int,
        text: str,
        reply_markup: Optional[Dict[str, Any]] = None,
        parse_mode: str = "HTML"
    ) -> Optional[Dict[str, Any]]:
        # Telegram character limit is 4096
        if len(text) > 4000:
            chunks = []
            cur = ""
            for line in text.split("\n"):
                if len(cur) + len(line) + 1 > 3800:
                    chunks.append(cur)
                    cur = line + "\n"
                else:
                    cur += line + "\n"
            if cur:
                chunks.append(cur)

            last_res = None
            for idx, ch in enumerate(chunks):
                is_last = (idx == len(chunks) - 1)
                payload = {
                    "chat_id": chat_id,
                    "text": ch,
                    "parse_mode": parse_mode,
                    "disable_web_page_preview": True,
                }
                if is_last and reply_markup:
                    payload["reply_markup"] = reply_markup
                last_res = self._api_call("sendMessage", payload)
            return last_res

        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        return self._api_call("sendMessage", payload)

    def edit_message_text(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        reply_markup: Optional[Dict[str, Any]] = None,
        parse_mode: str = "HTML"
    ) -> Optional[Dict[str, Any]]:
        if len(text) > 4000:
            return self.send_message(chat_id, text, reply_markup=reply_markup, parse_mode=parse_mode)

        payload = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        res = self._api_call("editMessageText", payload)
        if not res:
            return self.send_message(chat_id, text, reply_markup=reply_markup, parse_mode=parse_mode)
        return res

    def answer_callback_query(self, callback_query_id: str, text: Optional[str] = None):
        payload = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text
        return self._api_call("answerCallbackQuery", payload)

    # --- Command & Message Handlers ---

    def handle_update(self, update: Dict[str, Any]):
        if "message" in update:
            self.handle_message(update["message"])
        elif "callback_query" in update:
            self.handle_callback_query(update["callback_query"])

    def handle_message(self, msg: Dict[str, Any]):
        chat_id = msg.get("chat", {}).get("id")
        text = msg.get("text", "").strip()
        if not chat_id or not text:
            return

        # Check for OAuth callback URL or code
        if "authredirect://" in text or "code=" in text or (len(text) > 40 and not text.startswith("/")):
            self.process_login_code(chat_id, text)
            return

        if text.startswith("/start") or text.startswith("/menu"):
            self.cmd_start(chat_id)
        elif text.startswith("/help"):
            self.cmd_help(chat_id)
        elif text.startswith("/tutorial"):
            self.cmd_tutorial(chat_id)
        elif text.startswith("/login"):
            self.cmd_login(chat_id)
        elif text.startswith("/logout"):
            self.cmd_logout(chat_id)
        elif text.startswith("/team"):
            self.cmd_team(chat_id)
        elif text.startswith("/rivals"):
            parts = text.split(maxsplit=1)
            query = parts[1] if len(parts) > 1 else None
            self.cmd_rivals(chat_id, query)
        elif text.startswith("/history"):
            parts = text.split(maxsplit=1)
            query = parts[1] if len(parts) > 1 else None
            self.cmd_history(chat_id, query)
        elif text.startswith("/market"):
            self.cmd_market(chat_id)
        elif text.startswith("/trends"):
            self.cmd_trends(chat_id)
        elif text.startswith("/flip"):
            self.cmd_flip(chat_id)
        elif text.startswith("/leagues") or text.startswith("/ligas"):
            self.cmd_leagues(chat_id)
        elif text.startswith("/lineup"):
            self.cmd_lineup(chat_id)
        elif text.startswith("/autopilot") or text.startswith("/run"):
            self.cmd_autopilot(chat_id)
        elif text.startswith("/settings") or text.startswith("/ajustes"):
            self.cmd_settings(chat_id)
        elif text.startswith("/sell") or text.startswith("/vender"):
            self.cmd_sell_menu(chat_id)
        elif text.startswith("/reportes") or text.startswith("/admin_feedback"):
            self.cmd_admin_feedback(chat_id)
        elif text.startswith("/me"):
            self.cmd_me(chat_id)
        elif text.startswith("/id") or text.startswith("/myid"):
            self.send_message(chat_id, f"🆔 Tu Telegram ID es: <code>{chat_id}</code>")
        elif text.startswith("/bug"):
            parts = text.split(maxsplit=1)
            content = parts[1] if len(parts) > 1 else ""
            self.cmd_report(chat_id, msg.get("from", {}), "BUG", content)
        elif text.startswith("/sugerencia") or text.startswith("/sugerencias") or text.startswith("/feedback"):
            parts = text.split(maxsplit=1)
            content = parts[1] if len(parts) > 1 else ""
            self.cmd_report(chat_id, msg.get("from", {}), "SUGERENCIA", content)
        else:
            self.send_message(
                chat_id,
                "❓ Comando no reconocido. Usa /menu para abrir el panel de control o /help para ver la lista de comandos.",
                reply_markup=ui.main_menu_keyboard(sessions.is_user_logged_in(chat_id))
            )

    def handle_callback_query(self, cq: Dict[str, Any]):
        cq_id = cq.get("id")
        chat_id = cq.get("message", {}).get("chat", {}).get("id")
        message_id = cq.get("message", {}).get("message_id")
        data = cq.get("data", "")

        if not chat_id:
            return

        self.answer_callback_query(cq_id)

        if data == "cmd_menu":
            self.cmd_start(chat_id, message_id=message_id)
        elif data == "cmd_help":
            self.cmd_help(chat_id)
        elif data == "cmd_tutorial":
            self.cmd_tutorial(chat_id, message_id=message_id)
        elif data == "cmd_login":
            self.cmd_login(chat_id)
        elif data == "cmd_team":
            self.cmd_team(chat_id, message_id=message_id)
        elif data == "cmd_rivals":
            self.cmd_rivals(chat_id, message_id=message_id)
        elif data == "cmd_history":
            self.cmd_history(chat_id, message_id=message_id)
        elif data == "cmd_market":
            self.cmd_market(chat_id, message_id=message_id)
        elif data == "cmd_trends":
            self.cmd_trends(chat_id, message_id=message_id)
        elif data == "cmd_flip":
            self.cmd_flip(chat_id, message_id=message_id)
        elif data == "cmd_lineup":
            self.cmd_lineup(chat_id, message_id=message_id)
        elif data == "cmd_autopilot":
            self.cmd_autopilot(chat_id, message_id=message_id)
        elif data == "cmd_settings":
            self.cmd_settings(chat_id, message_id=message_id)
        elif data == "action_apply_lineup":
            self.cmd_apply_lineup(chat_id, message_id=message_id)
        elif data == "action_auto_bids":
            self.cmd_auto_bids(chat_id, message_id=message_id)
        elif data.startswith("bid_"):
            parts = data.split("_")
            mid, amt = parts[1], int(parts[2])
            self.cmd_bid_flip(chat_id, mid, amt, message_id=message_id)
        elif data.startswith("clause_"):
            parts = data.split("_")
            pid, amt = parts[1], int(parts[2])
            self.cmd_pay_clause(chat_id, pid, amt, message_id=message_id)
        elif data == "cmd_sell_menu":
            self.cmd_sell_menu(chat_id, message_id=message_id)
        elif data.startswith("sell_"):
            pid = data.split("sell_")[1]
            self.cmd_sell_player(chat_id, pid, message_id=message_id)
        elif data.startswith("toggle_"):
            key = data.split("toggle_")[1]
            self.cmd_toggle_setting(chat_id, key, message_id=message_id)
        elif data == "cmd_me":
            self.cmd_me(chat_id, message_id=message_id)
        elif data == "cmd_leagues":
            self.cmd_leagues(chat_id, message_id=message_id)
        elif data.startswith("set_league_"):
            lid = data.split("set_league_")[1]
            self.cmd_set_league(chat_id, lid, message_id=message_id)
        elif data == "cmd_sugerencia_btn":
            self.cmd_report(chat_id, {}, "SUGERENCIA", "")
        elif data == "cmd_bug_btn":
            self.cmd_report(chat_id, {}, "BUG", "")
        elif data.startswith("rival_"):
            manager_id = data.split("_")[1]
            self.cmd_rival_detail(chat_id, manager_id, message_id=message_id)
        elif data.startswith("history_"):
            manager_id = data.split("_")[1]
            self.cmd_history_detail(chat_id, manager_id, message_id=message_id)

    # --- Actions ---

    def cmd_start(self, chat_id: int, message_id: Optional[int] = None):
        logged_in = sessions.is_user_logged_in(chat_id)
        if logged_in:
            try:
                client = sessions.get_client_for_user(chat_id)
                me = client.me()
                user_name = me.get("managerName") or me.get("nickname") or me.get("name") or "Manager"
                status_text = f"✅ Conectado como <b>{user_name}</b>"
            except Exception:
                status_text = "⚠️ Sesión expirada o no iniciada"
                logged_in = False
        else:
            status_text = "🔒 No has iniciado sesión todavía"

        text = (
            "⚽ <b>Bienvenido a LaLiga Fantasy Bot</b>\n\n"
            f"{status_text}\n\n"
            "Elige una opción en el menú interactivo para consultar tu equipo, mercado, finanzas de rivales o tácticas:"
        )
        markup = ui.main_menu_keyboard(logged_in)
        if message_id:
            self.edit_message_text(chat_id, message_id, text, reply_markup=markup)
        else:
            self.send_message(chat_id, text, reply_markup=markup)

    def cmd_help(self, chat_id: int):
        text = (
            "📖 <b>Guía de Comandos del Bot:</b>\n\n"
            "🔐 <b>Cuenta:</b>\n"
            "• /login - Conectar tu cuenta de LaLiga Fantasy de forma segura\n"
            "• /logout - Cerrar sesión y borrar tus credenciales\n"
            "• /leagues - Ver todas tus ligas y cambiar de liga activa\n"
            "• /me - Ver tu perfil, saldo y ranking\n"
            "• /id - Ver tu Telegram Chat ID\n\n"
            "📋 <b>Tu Club:</b>\n"
            "• /team - Tu plantilla, valoraciones y cláusulas\n"
            "• /lineup - Tu XI actual y alineación óptima recomendada\n"
            "• /sell - Seleccionar y poner jugadores en venta al mercado\n\n"
            "⚔️ <b>Rivales y Mercado:</b>\n"
            "• /rivals [nombre|#1] - Finanzas, saldo estimado y blindajes de rivales\n"
            "• /history [nombre|#1] - Historial de compras/ventas, flips y ROI\n"
            "• /market - Jugadores en venta en el mercado de tu liga\n"
            "• /trends - Jugadores que más suben y bajan en LaLiga\n"
            "• /flip - Oportunidades de reventa y pujas\n\n"
            "🚀 <b>Autopilot y Ajustes:</b>\n"
            "• /autopilot - Ejecutar alineación óptima y auto-pujas\n"
            "• /settings - Configurar alertas y notificaciones inteligentes\n\n"
            "💬 <b>Feedback y Soporte:</b>\n"
            "• /bug &lt;mensaje&gt; - Reportar un error al desarrollador\n"
            "• /sugerencia &lt;mensaje&gt; - Enviar una idea o sugerencia"
        )
        self.send_message(chat_id, text, reply_markup=ui.back_to_menu_keyboard())
    def cmd_tutorial(self, chat_id: int, message_id: Optional[int] = None):
        text = ui.format_tutorial()
        markup = {
            "inline_keyboard": [
                [{"text": "🔐 Ir a Iniciar Sesión", "callback_data": "cmd_login"}],
                [{"text": "🔙 Menú Principal", "callback_data": "cmd_menu"}]
            ]
        }
        if message_id:
            self.edit_message_text(chat_id, message_id, text, reply_markup=markup)
        else:
            self.send_message(chat_id, text, reply_markup=markup)

    def cmd_login(self, chat_id: int):
        auth_url, _ = sessions.start_pkce_login(chat_id)
        text = (
            "🔐 <b>Inicio de Sesión Oficial en LaLiga Fantasy</b>\n\n"
            "1️⃣ Haz clic en <b>Iniciar Sesión Oficial en LaLiga</b>.\n"
            "2️⃣ Identifícate en la web oficial con tu cuenta (Google, Apple o Email).\n"
            "3️⃣ Al terminar, copia el enlace de redirección (<code>authredirect://...</code>) y <b>pégalo aquí en el chat</b>.\n\n"
            "<i>💡 ¿Dudas de cómo copiar el enlace? Pulsa el botón de tutorial abajo.</i>"
        )
        markup = {
            "inline_keyboard": [
                [{"text": "🔗 Iniciar Sesión Oficial en LaLiga", "url": auth_url}],
                [{"text": "📖 Ver Tutorial Paso a Paso", "callback_data": "cmd_tutorial"}],
                [{"text": "🔙 Volver", "callback_data": "cmd_menu"}]
            ]
        }
        self.send_message(chat_id, text, reply_markup=markup)

    def cmd_logout(self, chat_id: int):
        sessions.delete_user_session(chat_id)
        self.send_message(chat_id, "🚪 Has cerrado sesión correctamente.", reply_markup=ui.main_menu_keyboard(False))

    def process_login_code(self, chat_id: int, code_or_url: str):
        try:
            res = sessions.complete_pkce_login(chat_id, code_or_url)
            user = res.get("user", {})
            user_name = user.get("managerName") or user.get("nickname") or user.get("name") or "Manager"
            leagues = res.get("leagues", [])
            league_name = leagues[0].get("name") if leagues else "Tu Liga"

            text = (
                f"🎉 <b>¡Inicio de sesión exitoso!</b>\n\n"
                f"👤 <b>Manager:</b> {user_name}\n"
                f"🏆 <b>Liga activa:</b> {league_name}\n\n"
                "Ya puedes usar todos los comandos o navegar con los botones del menú:"
            )
            self.send_message(chat_id, text, reply_markup=ui.main_menu_keyboard(True))
        except Exception as e:
            self.send_message(
                chat_id,
                f"❌ Error al iniciar sesión: <code>{str(e)[:200]}</code>\n\nEscribe /login para intentarlo de nuevo.",
                reply_markup=ui.main_menu_keyboard(False)
            )

    def _get_client_or_ask_login(self, chat_id: int) -> Optional[sessions.UserFantasyClient]:
        if not sessions.is_user_logged_in(chat_id):
            self.send_message(
                chat_id,
                "🔒 Necesitas iniciar sesión primero para ver los datos de tu liga.\n\nEscribe /login o pulsa el botón abajo:",
                reply_markup=ui.main_menu_keyboard(False)
            )
            return None
        try:
            return sessions.get_client_for_user(chat_id)
        except Exception as e:
            self.send_message(chat_id, f"⚠️ Error de sesión: {e}. Escribe /login para renovar.")
            return None

    def cmd_team(self, chat_id: int, message_id: Optional[int] = None):
        client = self._get_client_or_ask_login(chat_id)
        if not client:
            return
        try:
            lid, tid = client.default_ids()
            team_data = client.team(lid, tid)
            text = ui.format_team(team_data)
            markup = ui.team_keyboard()
            if message_id:
                self.edit_message_text(chat_id, message_id, text, reply_markup=markup)
            else:
                self.send_message(chat_id, text, reply_markup=markup)
        except Exception as e:
            self.send_message(chat_id, f"❌ Error al cargar tu plantilla: {e}")

    def cmd_rivals(self, chat_id: int, query: Optional[str] = None, message_id: Optional[int] = None):
        client = self._get_client_or_ask_login(chat_id)
        if not client:
            return
        try:
            lid, _ = client.default_ids()
            rivals = rivals_mod.analyze_rivals(client, lid)

            if query:
                q_lower = query.lower().strip()
                matched = []
                clean_num = q_lower.lstrip("#")
                if clean_num.isdigit():
                    matched = [r for r in rivals if r.get("position") == int(clean_num)]
                if not matched and q_lower in ("me", "you", "tu", "yo"):
                    matched = [r for r in rivals if r.get("is_me")]
                if not matched:
                    matched = [r for r in rivals if str(r.get("manager_id")) == query]
                if not matched:
                    matched = [r for r in rivals if q_lower in r.get("manager_name", "").lower()]

                if not matched:
                    self.send_message(chat_id, f"❓ No se encontró ningún rival para '{query}'.")
                    return
                text = ui.format_rival_detail(matched[0])
                markup = ui.back_to_menu_keyboard()
            else:
                text = ui.format_rivals_summary(rivals)
                markup = ui.rivals_keyboard(rivals)

            if message_id:
                self.edit_message_text(chat_id, message_id, text, reply_markup=markup)
            else:
                self.send_message(chat_id, text, reply_markup=markup)
        except Exception as e:
            self.send_message(chat_id, f"❌ Error al consultar rivales: {e}")

    def cmd_rival_detail(self, chat_id: int, manager_id: str, message_id: Optional[int] = None):
        client = self._get_client_or_ask_login(chat_id)
        if not client:
            return
        try:
            lid, _ = client.default_ids()
            rivals = rivals_mod.analyze_rivals(client, lid)
            matched = [r for r in rivals if str(r.get("manager_id")) == str(manager_id)]
            if not matched:
                self.send_message(chat_id, "Rival no encontrado.")
                return
            text = ui.format_rival_detail(matched[0])
            markup = ui.back_to_menu_keyboard()
            if message_id:
                self.edit_message_text(chat_id, message_id, text, reply_markup=markup)
            else:
                self.send_message(chat_id, text, reply_markup=markup)
        except Exception as e:
            self.send_message(chat_id, f"❌ Error: {e}")

    def cmd_history(self, chat_id: int, query: Optional[str] = None, message_id: Optional[int] = None):
        client = self._get_client_or_ask_login(chat_id)
        if not client:
            return
        try:
            lid, _ = client.default_ids()
            report = history_mod.analyze_league_trading_history(client, lid)
            managers = report.get("managers", [])

            if query:
                q_lower = query.lower().strip()
                matched = []
                clean_num = q_lower.lstrip("#")
                if clean_num.isdigit():
                    matched = [m for m in managers if m.get("position") == int(clean_num)]
                if not matched and q_lower in ("me", "you", "tu", "yo"):
                    matched = [m for m in managers if m.get("is_me")]
                if not matched:
                    matched = [m for m in managers if str(m.get("manager_id")) == query]
                if not matched:
                    matched = [m for m in managers if q_lower in m.get("manager_name", "").lower()]

                if not matched:
                    self.send_message(chat_id, f"❓ No se encontró historial para '{query}'.")
                    return
                text = ui.format_manager_history(matched[0])
                markup = ui.back_to_menu_keyboard()
            else:
                text = ui.format_history_summary(report)
                markup = ui.history_keyboard(managers)

            if message_id:
                self.edit_message_text(chat_id, message_id, text, reply_markup=markup)
            else:
                self.send_message(chat_id, text, reply_markup=markup)
        except Exception as e:
            self.send_message(chat_id, f"❌ Error al consultar historial: {e}")

    def cmd_history_detail(self, chat_id: int, manager_id: str, message_id: Optional[int] = None):
        client = self._get_client_or_ask_login(chat_id)
        if not client:
            return
        try:
            lid, _ = client.default_ids()
            report = history_mod.analyze_league_trading_history(client, lid)
            managers = report.get("managers", [])
            matched = [m for m in managers if str(m.get("manager_id")) == str(manager_id)]
            if not matched:
                self.send_message(chat_id, "Manager no encontrado.")
                return
            text = ui.format_manager_history(matched[0])
            markup = ui.back_to_menu_keyboard()
            if message_id:
                self.edit_message_text(chat_id, message_id, text, reply_markup=markup)
            else:
                self.send_message(chat_id, text, reply_markup=markup)
        except Exception as e:
            self.send_message(chat_id, f"❌ Error: {e}")

    def cmd_market(self, chat_id: int, message_id: Optional[int] = None):
        client = self._get_client_or_ask_login(chat_id)
        if not client:
            return
        try:
            lid, _ = client.default_ids()
            market_items = client.market(lid) or []
            text = ui.format_market(market_items)
            markup = ui.back_to_menu_keyboard()
            if message_id:
                self.edit_message_text(chat_id, message_id, text, reply_markup=markup)
            else:
                self.send_message(chat_id, text, reply_markup=markup)
        except Exception as e:
            self.send_message(chat_id, f"❌ Error al cargar mercado: {e}")

    def cmd_trends(self, chat_id: int, message_id: Optional[int] = None):
        try:
            trends = market_trends()
            text = ui.format_trends(trends)
            markup = ui.back_to_menu_keyboard()
            if message_id:
                self.edit_message_text(chat_id, message_id, text, reply_markup=markup)
            else:
                self.send_message(chat_id, text, reply_markup=markup)
        except Exception as e:
            self.send_message(chat_id, f"❌ Error al cargar tendencias: {e}")

    def cmd_flip(self, chat_id: int, message_id: Optional[int] = None):
        client = self._get_client_or_ask_login(chat_id)
        if not client:
            return
        try:
            lid, tid = client.default_ids()
            team_data = client.team(lid, tid)
            owned = {p.get("playerMaster", {}).get("id") for p in team_data.get("players", []) if p.get("playerMaster", {}).get("id")}
            flips = flip_mod.opportunities(client, lid, owned=owned)
            if not flips:
                text = "🔄 <b>Oportunidades de Reventa (Flip)</b>\n\nNo hay oportunidades claras de reventa en el mercado actual."
            else:
                lines = [
                    "🔄 <b>Oportunidades de Reventa (Flips)</b>",
                    "<i>Jugadores con mayor margen proyectado a 7 días:</i>\n"
                ]
                for f in flips[:6]:
                    via = f.get("via", "SISTEMA")
                    owner = f.get("owner", "Mercado Libre")
                    icon = "⚡" if via == "CLAUSULA" else "🛒"
                    diff_sign = "+" if f.get("margin", 0) >= 0 else ""
                    lines.append(
                        f"{icon} <b>{f['nombre']}</b> ({f['pos']})\n"
                        f"  • 👤 <b>Origen:</b> {via} <i>({owner})</i>\n"
                        f"  • 💵 <b>Precio:</b> {ui.fmt_eur(f['buy_price'])}\n"
                        f"  • 📈 <b>Proy. 7d:</b> {ui.fmt_eur(f['proyeccion'])}\n"
                        f"  • 💰 <b>Margen:</b> <b>{diff_sign}{ui.fmt_eur(f['margin'])}</b> ({f['margin_pct']:+.1f}%)\n"
                    )
                text = "\n".join(lines)

            markup = ui.flips_keyboard(flips)
            if message_id:
                self.edit_message_text(chat_id, message_id, text, reply_markup=markup)
            else:
                self.send_message(chat_id, text, reply_markup=markup)
        except Exception as e:
            self.send_message(chat_id, f"❌ Error al buscar flips: {e}")

    def cmd_lineup(self, chat_id: int, message_id: Optional[int] = None):
        client = self._get_client_or_ask_login(chat_id)
        if not client:
            return
        try:
            lid, tid = client.default_ids()
            team_data = client.team(lid, tid)
            lineup_data = client.lineup(tid)
            form_dict = lineup_data.get("formation") or {}
            raw_tact = form_dict.get("tacticalFormation") or [3, 4, 3]
            tactical = "-".join(str(x) for x in raw_tact)

            lines = [
                f"⚽ <b>Alineación Actual ({tactical})</b>\n",
            ]
            current_ids = set()
            for pos_key, pos_label, pos_icon in [
                ("goalkeeper", "PORTERO", "🧤"),
                ("defender", "DEFENSAS", "🛡"),
                ("midfield", "MEDIOS", "🎯"),
                ("striker", "DELANTEROS", "⚡")
            ]:
                players_list = form_dict.get(pos_key, [])
                if players_list:
                    pnames = []
                    for p in players_list:
                        pm = p.get("playerMaster") or {}
                        ptid = p.get("playerTeamId") or pm.get("id")
                        if ptid:
                            current_ids.add(str(ptid))
                        pnames.append(pm.get("nickname") or pm.get("name") or "Jugador")
                    lines.append(f"{pos_icon} <b>{pos_label}:</b> " + " • ".join(f"<b>{n}</b>" for n in pnames))

            # Calculate optimal lineup recommendation
            can_apply = False
            try:
                best = lineup_opt.optimize(team_data)
                d, m, f = best["formation"]
                opt_tactical = f"{d}-{m}-{f}"
                optimal_ids = set()
                optimal_ids.add(str(best["goalkeeper"]["playerTeamId"]))
                for d_p in best.get("defender", []):
                    optimal_ids.add(str(d_p["playerTeamId"]))
                for m_p in best.get("midfield", []):
                    optimal_ids.add(str(m_p["playerTeamId"]))
                for s_p in best.get("striker", []):
                    optimal_ids.add(str(s_p["playerTeamId"]))

                if current_ids == optimal_ids:
                    lines.append("\n✅ <b>¡Tu XI actual ya es el óptimo!</b>")
                    lines.append("<i>No necesitas realizar ningún cambio para la próxima jornada.</i>")
                else:
                    can_apply = True
                    lines.append(f"\n🌟 <b>Alineación Óptima Recomendada ({opt_tactical})</b>\n")
                    gk_name = best["goalkeeper"].get("nombre") or best["goalkeeper"].get("name")
                    lines.append(f"🧤 <b>PORTERO:</b> <b>{gk_name}</b>")
                    defs = [p.get("nombre") or p.get("name") for p in best.get("defender", [])]
                    lines.append(f"🛡 <b>DEFENSAS:</b> " + " • ".join(f"<b>{n}</b>" for n in defs))
                    mids = [p.get("nombre") or p.get("name") for p in best.get("midfield", [])]
                    lines.append(f"🎯 <b>MEDIOS:</b> " + " • ".join(f"<b>{n}</b>" for n in mids))
                    strikers = [p.get("nombre") or p.get("name") for p in best.get("striker", [])]
                    lines.append(f"⚡ <b>DELANTEROS:</b> " + " • ".join(f"<b>{n}</b>" for n in strikers))
            except Exception as opt_err:
                lines.append(f"\n<i>(Aviso de optimización: {opt_err})</i>")

            text = "\n".join(lines)
            markup = ui.lineup_keyboard(can_apply=can_apply)
            if message_id:
                self.edit_message_text(chat_id, message_id, text, reply_markup=markup)
            else:
                self.send_message(chat_id, text, reply_markup=markup)
        except Exception as e:
            self.send_message(chat_id, f"❌ Error al consultar alineación: {e}")

    def cmd_apply_lineup(self, chat_id: int, message_id: Optional[int] = None):
        client = self._get_client_or_ask_login(chat_id)
        if not client:
            return
        try:
            lid, tid = client.default_ids()
            team_data = client.team(lid, tid)
            best = lineup_opt.optimize(team_data)
            current_ids = agent_mod._current_xi_ids(client, tid)
            res = execute_mod.apply_lineup(client, tid, best, current_ids, dry_run=False)
            d, m, f = best["formation"]
            text = (
                f"🎉 <b>¡Alineación Guardada con Éxito!</b>\n\n"
                f"Se ha aplicado tu <b>XI Óptimo ({d}-{m}-{f})</b> directamente en tu cuenta oficial de LaLiga Fantasy. ⚽"
            )
            self.send_message(chat_id, text, reply_markup=ui.back_to_menu_keyboard())
        except Exception as e:
            self.send_message(chat_id, f"❌ Error al aplicar alineación: {e}", reply_markup=ui.back_to_menu_keyboard())

    def cmd_bid_flip(self, chat_id: int, market_id: str, amount: int, message_id: Optional[int] = None):
        client = self._get_client_or_ask_login(chat_id)
        if not client:
            return
        try:
            lid, _ = client.default_ids()
            client.make_bid(lid, market_id, amount)
            text = (
                f"✅ <b>¡Puja Realizada con Éxito!</b>\n\n"
                f"Has pujado <b>{amount:,} €</b> por el jugador en el mercado de tu liga. 🛒"
            )
            self.send_message(chat_id, text, reply_markup=ui.back_to_menu_keyboard())
        except Exception as e:
            self.send_message(chat_id, f"❌ Error al realizar puja: {e}", reply_markup=ui.back_to_menu_keyboard())

    def cmd_pay_clause(self, chat_id: int, player_id: str, amount: int, message_id: Optional[int] = None):
        client = self._get_client_or_ask_login(chat_id)
        if not client:
            return
        try:
            lid, _ = client.default_ids()
            client.pay_buyout_clause(lid, player_id, amount)
            text = (
                f"⚡ <b>¡Clausulazo Ejecutado con Éxito!</b>\n\n"
                f"Has pagado la cláusula de rescisión de <b>{amount:,} €</b> por el jugador. 💥"
            )
            self.send_message(chat_id, text, reply_markup=ui.back_to_menu_keyboard())
        except Exception as e:
            self.send_message(chat_id, f"❌ Error al pagar cláusula: {e}", reply_markup=ui.back_to_menu_keyboard())

    def cmd_auto_bids(self, chat_id: int, message_id: Optional[int] = None):
        client = self._get_client_or_ask_login(chat_id)
        if not client:
            return
        try:
            lid, tid = client.default_ids()
            team = client.team(lid, tid)
            res = execute_mod.sync_bids(client, lid, team, dry_run=False)
            placed = res.get("placed", [])
            cancelled = res.get("cancelled", [])
            lines = ["🤖 <b>Resultado de Auto-Pujas:</b>\n"]
            if placed:
                lines.append("💰 <b>Pujas Realizadas:</b>")
                for b in placed:
                    lines.append(f"  • {b['nombre']}: {b['amount']:,} € (+{b['margin_pct']}%)")
            else:
                lines.append("• No hubo nuevos flips que encajaran con tu saldo disponible.")
            if cancelled:
                lines.append("\n🚫 <b>Pujas Canceladas (ya no rentables):</b>")
                for c in cancelled:
                    lines.append(f"  • {c}")
            text = "\n".join(lines)
            self.send_message(chat_id, text, reply_markup=ui.back_to_menu_keyboard())
        except Exception as e:
            self.send_message(chat_id, f"❌ Error en auto-pujas: {e}", reply_markup=ui.back_to_menu_keyboard())

    def cmd_sell_menu(self, chat_id: int, message_id: Optional[int] = None):
        client = self._get_client_or_ask_login(chat_id)
        if not client:
            return
        try:
            lid, tid = client.default_ids()
            team_data = client.team(lid, tid)
            players = team_data.get("players", [])
            text = (
                "🏷 <b>Poner Jugador en Venta</b>\n\n"
                "Selecciona el jugador de tu plantilla que deseas listar en el mercado oficial:"
            )
            markup = ui.sell_player_keyboard(players)
            if message_id:
                self.edit_message_text(chat_id, message_id, text, reply_markup=markup)
            else:
                self.send_message(chat_id, text, reply_markup=markup)
        except Exception as e:
            self.send_message(chat_id, f"❌ Error al cargar plantilla para venta: {e}")

    def cmd_sell_player(self, chat_id: int, player_id: str, message_id: Optional[int] = None):
        client = self._get_client_or_ask_login(chat_id)
        if not client:
            return
        try:
            lid, tid = client.default_ids()
            team_data = client.team(lid, tid)
            players = team_data.get("players", [])
            target = next((p for p in players if str(p.get("playerMaster", {}).get("id")) == str(player_id)), None)
            if not target:
                self.send_message(chat_id, "Jugador no encontrado en tu plantilla.")
                return
            pm = target.get("playerMaster", {})
            price = pm.get("marketValue") or 1000000
            name = pm.get("nickname") or pm.get("name") or "Jugador"
            client.sell_player(lid, player_id, price)
            text = (
                f"✅ <b>¡Jugador Puesto en Venta!</b>\n\n"
                f"Has listado a <b>{name}</b> en el mercado oficial por <b>{price:,} €</b>. 🏷"
            )
            self.send_message(chat_id, text, reply_markup=ui.back_to_menu_keyboard())
        except Exception as e:
            self.send_message(chat_id, f"❌ Error al poner en venta: {e}", reply_markup=ui.back_to_menu_keyboard())

    def cmd_autopilot(self, chat_id: int, message_id: Optional[int] = None):
        client = self._get_client_or_ask_login(chat_id)
        if not client:
            return
        try:
            lid, tid = client.default_ids()
            team = client.team(lid, tid)
            best = lineup_opt.optimize(team)
            current_ids = agent_mod._current_xi_ids(client, tid)
            res = execute_mod.act(client, lid, tid, team, best, current_ids, dry_run=False)

            lu = res["lineup"]
            bd = res["bids"]
            lines = ["🚀 <b>Autopilot de LaLiga Fantasy Ejecutado</b>\n"]
            if lu.get("changed"):
                d, m, f = lu["formation"]
                lines.append(f"⚽ <b>Alineación:</b> Actualizada al XI óptimo ({d}-{m}-{f}) ✅")
            else:
                lines.append("⚽ <b>Alineación:</b> Ya estaba 100% óptima ✅")

            if bd.get("placed"):
                lines.append("\n💰 <b>Pujas Realizadas:</b>")
                for b in bd["placed"]:
                    lines.append(f"  • {b['nombre']}: {b['amount']:,} € (+{b['margin_pct']}%)")
            else:
                lines.append("\n💰 <b>Pujas:</b> No hay nuevas oportunidades de flip dentro de tu saldo.")

            if bd.get("cancelled"):
                lines.append("\n🚫 <b>Pujas Canceladas:</b>")
                for c in bd["cancelled"]:
                    lines.append(f"  • {c}")

            text = "\n".join(lines)
            self.send_message(chat_id, text, reply_markup=ui.back_to_menu_keyboard())
        except Exception as e:
            self.send_message(chat_id, f"❌ Error en autopilot: {e}", reply_markup=ui.back_to_menu_keyboard())

    def cmd_settings(self, chat_id: int, message_id: Optional[int] = None):
        settings = sessions.get_user_settings(chat_id)
        text = (
            "⚙️ <b>Ajustes y Notificaciones Automáticas</b>\n\n"
            "Configura tus alertas inteligentes para recibir avisos o automatizaciones en este chat de Telegram:"
        )
        markup = ui.settings_keyboard(settings)
        if message_id:
            self.edit_message_text(chat_id, message_id, text, reply_markup=markup)
        else:
            self.send_message(chat_id, text, reply_markup=markup)

    def cmd_toggle_setting(self, chat_id: int, key: str, message_id: Optional[int] = None):
        new_settings = sessions.toggle_user_setting(chat_id, key)
        text = (
            "⚙️ <b>Ajustes y Notificaciones Automáticas</b>\n\n"
            "Configura tus alertas inteligentes para recibir avisos o automatizaciones en este chat de Telegram:"
        )
        markup = ui.settings_keyboard(new_settings)
        if message_id:
            self.edit_message_text(chat_id, message_id, text, reply_markup=markup)
        else:
            self.send_message(chat_id, text, reply_markup=markup)

    def cmd_me(self, chat_id: int, message_id: Optional[int] = None):
        client = self._get_client_or_ask_login(chat_id)
        if not client:
            return
        try:
            me = client.me()
            lid, tid = client.default_ids()
            leagues = client.leagues()
            cur_league = next((l for l in leagues if l.get("id") == lid), {})
            team = client.team(lid, tid)
            user_name = me.get("managerName") or me.get("nickname") or me.get("name") or "Manager"

            text = (
                f"👤 <b>Mi Perfil de LaLiga Fantasy</b>\n\n"
                f"• <b>Usuario:</b> {user_name}\n"
                f"• <b>Liga:</b> {cur_league.get('name', 'Liga')}\n"
                f"• <b>Puntos:</b> {team.get('teamPoints', 0)} pts (#{team.get('position', '-')})\n"
                f"• <b>Valor Plantilla:</b> {team.get('teamValue', 0):,} €\n"
                f"• <b>Saldo Bancario:</b> {team.get('teamMoney', 0):,} €"
            )
            markup = ui.back_to_menu_keyboard()
            if message_id:
                self.edit_message_text(chat_id, message_id, text, reply_markup=markup)
            else:
                self.send_message(chat_id, text, reply_markup=markup)
        except Exception as e:
            self.send_message(chat_id, f"❌ Error: {e}")

    def cmd_leagues(self, chat_id: int, message_id: Optional[int] = None):
        client = self._get_client_or_ask_login(chat_id)
        if not client:
            return
        try:
            leagues = client.leagues()
            if not leagues:
                self.send_message(chat_id, "No tienes ninguna liga activa en esta cuenta.")
                return

            lid, _ = client.default_ids()
            cur_lg = next((l for l in leagues if str(l.get("id")) == str(lid)), leagues[0])

            text = (
                f"🏆 <b>Tus Ligas en LaLiga Fantasy</b>\n\n"
                f"• <b>Liga activa actual:</b> <b>{cur_lg.get('name', 'Liga')}</b>\n\n"
                f"Pulsa sobre cualquier liga para cambiar de liga activa:"
            )
            markup = ui.leagues_keyboard(leagues, active_lid=str(lid))
            if message_id:
                self.edit_message_text(chat_id, message_id, text, reply_markup=markup)
            else:
                self.send_message(chat_id, text, reply_markup=markup)
        except Exception as e:
            self.send_message(chat_id, f"❌ Error al consultar ligas: {e}")

    def cmd_set_league(self, chat_id: int, league_id: str, message_id: Optional[int] = None):
        client = self._get_client_or_ask_login(chat_id)
        if not client:
            return
        try:
            sessions.set_user_active_league(chat_id, league_id)
            leagues = client.leagues()
            cur_lg = next((l for l in leagues if str(l.get("id")) == str(league_id)), {})
            lg_name = cur_lg.get("name", "Liga seleccionada")

            text = (
                f"✅ <b>¡Liga cambiada con éxito!</b>\n\n"
                f"Ahora estás operando en: 🏆 <b>{lg_name}</b>\n\n"
                f"Todas tus consultas de plantilla, mercado y rivales se aplicarán sobre esta liga."
            )
            markup = ui.main_menu_keyboard(True)
            if message_id:
                self.edit_message_text(chat_id, message_id, text, reply_markup=markup)
            else:
                self.send_message(chat_id, text, reply_markup=markup)
        except Exception as e:
            self.send_message(chat_id, f"❌ Error al cambiar de liga: {e}")

    def cmd_report(self, chat_id: int, user_info: Dict[str, Any], report_type: str, content: str):
        from . import feedback
        if not content.strip():
            emoji = "🐛" if report_type == "BUG" else "💡"
            cmd_name = "bug" if report_type == "BUG" else "sugerencia"
            self.send_message(
                chat_id,
                f"{emoji} <b>Enviar {report_type.lower()}:</b>\n\n"
                f"Escribe el comando seguido de tu mensaje. Por ejemplo:\n"
                f"<code>/{cmd_name} Describe aquí tu {report_type.lower()}...</code>",
                reply_markup=ui.back_to_menu_keyboard()
            )
            return

        entry = feedback.record_feedback(chat_id, user_info, report_type, content.strip())
        emoji = "🐛" if report_type == "BUG" else "💡"

        # Acknowledge to user
        self.send_message(
            chat_id,
            f"✅ <b>¡Muchas gracias!</b>\n\n"
            f"Tu {report_type.lower()} ha sido registrado y enviado directamente al desarrollador. 📩",
            reply_markup=ui.back_to_menu_keyboard()
        )

        # Notify Admin if TELEGRAM_ADMIN_CHAT_ID is configured
        admin_id = os.environ.get("TELEGRAM_ADMIN_CHAT_ID") or "351138675"
        if admin_id:
            try:
                uname = user_info.get("username")
                u_str = f"@{uname}" if uname else f"ID: {chat_id}"
                admin_msg = (
                    f"📩 <b>Nuevo Reporte en el Bot</b>\n\n"
                    f"👤 <b>De:</b> {user_info.get('first_name', 'Usuario')} ({u_str})\n"
                    f"🏷 <b>Tipo:</b> {emoji} <b>{report_type}</b>\n"
                    f"📅 <b>Fecha:</b> {entry['date']}\n\n"
                    f"💬 <b>Mensaje:</b>\n<i>{content.strip()}</i>"
                )
                self.send_message(int(admin_id), admin_msg)
            except Exception as e:
                logger.error("Failed to forward report to admin: %s", e)

    def cmd_admin_feedback(self, chat_id: int):
        from . import feedback
        items = feedback.load_all_feedback()
        if not items:
            self.send_message(chat_id, "📭 No hay reportes ni sugerencias guardadas todavía.", reply_markup=ui.back_to_menu_keyboard())
            return

        lines = [f"📋 <b>Bandeja de Entrada de Reportes ({len(items)}):</b>\n"]
        for idx, item in enumerate(items[-15:], 1):
            emoji = "🐛" if item.get("type") == "BUG" else "💡"
            u_name = item.get("username")
            u_str = f"@{u_name}" if u_name else f"ID: {item.get('chat_id')}"
            lines.append(f"{idx}. {emoji} <b>[{item.get('type')}]</b> de {u_str} ({item.get('date')})\n   <i>\"{item.get('message')}\"</i>\n")

        self.send_message(chat_id, "\n".join(lines), reply_markup=ui.back_to_menu_keyboard())

    # --- Polling Loop ---

    def start_polling(self):
        self.running = True
        print("[Telegram Bot] Polling daemon started successfully.")
        print("[Telegram Bot] Open https://t.me/LaLigaFantasyTelegramBot in Telegram!")

        # Start background alerts and autopilot worker
        from . import notifications
        notifications.start_notification_worker(self)
        
        while self.running:
            try:
                updates = self._api_call("getUpdates", {
                    "offset": self.offset,
                    "timeout": 25,
                })
                if updates:
                    for upd in updates:
                        upd_id = upd.get("update_id", 0)
                        if upd_id >= self.offset:
                            self.offset = upd_id + 1
                        self.handle_update(upd)
            except KeyboardInterrupt:
                print("\n[Telegram Bot] Stopping polling daemon...")
                break
            except Exception as e:
                logger.error("Polling error: %s", e)
                time.sleep(2)


def run_bot(token: str):
    bot = TelegramBot(token)
    bot.start_polling()
