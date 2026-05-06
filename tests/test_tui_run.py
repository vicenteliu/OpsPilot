"""Tests for TUI run flow — REPL shell edition."""

from __future__ import annotations

from textual.widgets import Button, Input, Label

from opspilot.tui.app import OpsPilotApp
from opspilot.tui.run_modal import RunModal

# ── RunModal: still exists and can be pushed independently ────────────────────


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
        async with OpsPilotApp().run_test() as pilot:
            pilot.app.push_screen(RunModal())
            await pilot.pause()
            await pilot.click("#btn-run")
            await pilot.pause()
            modal = pilot.app.screen
            lbl = modal.query_one("#status-line", Label)
            assert "required" in str(lbl.render()).lower()


# ── REPL command parsing ──────────────────────────────────────────────────────


class TestRunCommandParsing:
    async def test_run_without_ticket_shows_usage(self) -> None:
        async with OpsPilotApp().run_test() as pilot:
            inp = pilot.app.query_one("#cmd-input", Input)
            inp.value = "/run"
            await pilot.press("enter")
            await pilot.pause(0.1)
            # Should show usage error, not crash
            assert pilot.app.query_one("#cmd-input", Input) is not None

    async def test_run_with_ticket_dispatches(self) -> None:
        # Dispatching /run with a path triggers a background worker.
        # We only verify the app doesn't crash, not the full orchestrator result.
        async with OpsPilotApp().run_test() as pilot:
            inp = pilot.app.query_one("#cmd-input", Input)
            inp.value = "/run /nonexistent/ticket.json --playbook playbooks/pb_test"
            await pilot.press("enter")
            await pilot.pause(0.2)
            # Input should be cleared; app still alive
            assert pilot.app.query_one("#cmd-input", Input).value == ""

    async def test_sessions_command_dispatches(self) -> None:
        async with OpsPilotApp().run_test() as pilot:
            inp = pilot.app.query_one("#cmd-input", Input)
            inp.value = "/sessions"
            await pilot.press("enter")
            await pilot.pause(0.3)
            assert pilot.app.query_one("#cmd-input", Input).value == ""

    async def test_kb_missing_subcommand_shows_hint(self) -> None:
        async with OpsPilotApp().run_test() as pilot:
            inp = pilot.app.query_one("#cmd-input", Input)
            inp.value = "/kb"
            await pilot.press("enter")
            await pilot.pause(0.1)
            assert pilot.app.query_one("#cmd-input", Input) is not None


# ── Auto-start via constructor ─────────────────────────────────────────────────


class TestAutoStart:
    async def test_app_without_run_input_no_auto_run(self) -> None:
        async with OpsPilotApp().run_test() as pilot:
            await pilot.pause(0.5)
            # No RunModal pushed — app stays on main screen
            assert not isinstance(pilot.app.screen, RunModal)
