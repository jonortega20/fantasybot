import unittest
import os
import shutil
import tempfile
from fantasybot.telegram import sessions, ui, TelegramBot


class TestTelegramModule(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.orig_sessions_dir = sessions.TELEGRAM_SESSIONS_DIR
        sessions.TELEGRAM_SESSIONS_DIR = self.test_dir

    def tearDown(self):
        sessions.TELEGRAM_SESSIONS_DIR = self.orig_sessions_dir
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_session_lifecycle(self):
        chat_id = 999888777
        self.assertFalse(sessions.is_user_logged_in(chat_id))

        tokens = {"access_token": "fake_token", "refresh_token": "fake_refresh"}
        sessions.save_user_tokens(chat_id, tokens)
        self.assertTrue(sessions.is_user_logged_in(chat_id))

        loaded = sessions.load_user_tokens(chat_id)
        self.assertEqual(loaded["access_token"], "fake_token")

        sessions.delete_user_session(chat_id)
        self.assertFalse(sessions.is_user_logged_in(chat_id))

    def test_ui_keyboards(self):
        menu_unlogged = ui.main_menu_keyboard(logged_in=False)
        self.assertTrue(any("cmd_login" in btn["callback_data"] for row in menu_unlogged["inline_keyboard"] for btn in row))

        menu_logged = ui.main_menu_keyboard(logged_in=True)
        self.assertTrue(any("cmd_team" in btn["callback_data"] for row in menu_logged["inline_keyboard"] for btn in row))
        self.assertTrue(any("cmd_rivals" in btn["callback_data"] for row in menu_logged["inline_keyboard"] for btn in row))
        self.assertTrue(any("cmd_history" in btn["callback_data"] for row in menu_logged["inline_keyboard"] for btn in row))

    def test_ui_formatters(self):
        team_data = {
            "name": "Test FC",
            "teamValue": 100_000_000,
            "teamMoney": 10_000_000,
            "players": [
                {
                    "playerMaster": {"nickname": "Raphinha", "marketValue": 90_000_000, "positionId": 4},
                    "buyoutClause": 100_000_000
                }
            ]
        }
        formatted = ui.format_team(team_data)
        self.assertIn("Raphinha", formatted)
        self.assertIn("100.000.000", formatted)


if __name__ == "__main__":
    unittest.main()
