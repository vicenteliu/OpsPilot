"""Tests for PR-22: TUI Run modal and `opspilot tui run` CLI subcommand."""

from __future__ import annotations

from unittest.mock import patch

from textual.widgets import Button, Input, Label

from opspilot.tui.app import OpsPilotApp
from opspilot.tui.run_modal import RunModal
from opspilot.tui.screens import SessionsScreen

# ──────────────────────────────────────────────────────────────────────────
#  RunModal structure — push onto OpsPilotApp in each test
# ──────────────────────────────────────────────────────────────────────────


class TestRunModalStructure:
    async def test_modal_has_three_inputs(self) -> None:
        async with OpsPilotApp().run_test() as pilot:
            pilot.app.push_screen(RunModal())
            await pilot.pause()
            modal = pilot.app.screen
            assert isinstance(modal, RunModal)
            assert len(modal.query(Input)) == 3

    async def test_modal_has_run_and_cancel_buttons(self) -> None:
        async with OpsPilotApp().run_test() as pilot:
            pilot.app.push_screen(RunModal())
            await pilot.pause()
            modal = pilot.app.screen
            assert modal.query_one("#btn-run", Button)
            assert modal.query_one("#btn-cancel", Button)

    async def test_modal_has_status_label(self) -> None:
        async with OpsPilotApp().run_test() as pilot:
            pilot.app.push_screen(RunModal())
            await pilot.pause()
            modal = pilot.app.screen
            lbl = modal.query_one("#status-line", Label)
            assert "Ready" in str(lbl.render())

    async def test_default_playbook_prefilled(self) -> None:
        async with OpsPilotApp().run_test() as pilot:
            pilot.app.push_screen(RunModal(playbook_dir="my/playbook"))
            await pilot.pause()
            modal = pilot.app.screen
            val = modal.query_one("#inp-playbook", Input).value
            assert val == "my/playbook"

    async def test_default_input_prefilled(self) -> None:
        async with OpsPilotApp().run_test() as pilot:
            pilot.app.push_screen(RunModal(input_path="/tmp/ticket.json"))
            await pilot.pause()
            modal = pilot.app.screen
            val = modal.query_one("#inp-ticket", Input).value
            assert val == "/tmp/ticket.json"

    async def test_cancel_button_dismisses(self) -> None:
        results: list[str | None] = []

        async with OpsPilotApp().run_test() as pilot:
            pilot.app.push_screen(RunModal(), lambda r: results.append(r))
            await pilot.pause()
            modal = pilot.app.screen
            assert isinstance(modal, RunModal)
            await pilot.click("#btn-cancel")
            await pilot.pause()

        assert results == [None]

    async def test_run_without_ticket_shows_error(self) -> None:
        # RunModal() has empty ticket field by default
        async with OpsPilotApp().run_test() as pilot:
            pilot.app.push_screen(RunModal())
            await pilot.pause()
            await pilot.click("#btn-run")
            await pilot.pause()
            modal = pilot.app.screen
            lbl = modal.query_one("#status-line", Label)
            assert "required" in str(lbl.render()).lower()


# ──────────────────────────────────────────────────────────────────────────
#  App-level Run keybinding
# ──────────────────────────────────────────────────────────────────────────


class TestRunKeybinding:
    async def test_r_key_opens_run_modal(self) -> None:
        async with OpsPilotApp().run_test() as pilot:
            await pilot.press("r")
            await pilot.pause()
            assert isinstance(pilot.app.screen, RunModal)

    async def test_run_modal_opened_via_action(self) -> None:
        async with OpsPilotApp().run_test() as pilot:
            pilot.app.action_start_run()
            await pilot.pause()
            assert isinstance(pilot.app.screen, RunModal)


# ──────────────────────────────────────────────────────────────────────────
#  Sessions screen refresh (PR-22 integration point)
# ──────────────────────────────────────────────────────────────────────────


class TestSessionsRefresh:
    async def test_refresh_sessions_clears_and_reloads(self) -> None:
        async with OpsPilotApp().run_test() as pilot:
            await pilot.press("2")
            await pilot.pause(0.3)
            screen = pilot.app.query_one(SessionsScreen)
            screen.refresh_sessions()
            await pilot.pause(0.3)
            # Table should still have at least 1 row (placeholder or real sessions)
            assert screen.query_one("DataTable").row_count >= 1


# ──────────────────────────────────────────────────────────────────────────
#  Auto-start via run_input constructor param
# ──────────────────────────────────────────────────────────────────────────


class TestAutoStart:
    async def test_app_with_run_input_opens_modal(self) -> None:
        app = OpsPilotApp(run_input="/tmp/ticket.json", run_playbook="playbooks/pb_test")
        async with app.run_test() as pilot:
            await pilot.pause(0.6)  # 0.3s timer + render
            assert isinstance(pilot.app.screen, RunModal)

    async def test_app_without_run_input_no_modal(self) -> None:
        async with OpsPilotApp().run_test() as pilot:
            await pilot.pause(0.5)
            assert not isinstance(pilot.app.screen, RunModal)


# ──────────────────────────────────────────────────────────────────────────
#  _on_run_done refreshes Sessions and switches to it
# ──────────────────────────────────────────────────────────────────────────


class TestOnRunDone:
    async def test_on_run_done_with_session_id_switches_to_sessions(self) -> None:
        async with OpsPilotApp().run_test() as pilot:
            with patch.object(
                pilot.app.query_one(SessionsScreen),
                "refresh_sessions",
                return_value=None,
            ) as mock_refresh:
                pilot.app._on_run_done("sess_abc123")
                await pilot.pause()
                mock_refresh.assert_called_once()
                assert pilot.app.active_module == "sessions"

    async def test_on_run_done_with_none_does_nothing(self) -> None:
        async with OpsPilotApp().run_test() as pilot:
            original_module = pilot.app.active_module
            pilot.app._on_run_done(None)
            await pilot.pause()
            assert pilot.app.active_module == original_module
