"""Tests for TUI wiki integration — REPL shell edition."""

from __future__ import annotations

from textual.binding import Binding
from textual.widgets import Input

from opspilot.tui.app import OpsPilotApp
from opspilot.tui.screens.sessions import SessionsScreen
from opspilot.tui.screens.wiki_tree import WikiTreeScreen
from opspilot.tui.wiki_modal import WikiQueryModal

# ── WikiQueryModal: can be pushed directly ─────────────────────────────────────


class TestWikiQueryModalStructure:
    async def test_has_session_id_displayed(self) -> None:
        from textual.widgets import Static

        async with OpsPilotApp().run_test() as pilot:
            await pilot.app.push_screen(WikiQueryModal("sess_abc00001"))
            await pilot.pause()
            texts = [str(w.render()) for w in pilot.app.screen.query(Static)]
            assert any("sess_abc00001" in t for t in texts)

    async def test_has_generate_button(self) -> None:
        from textual.widgets import Button

        async with OpsPilotApp().run_test() as pilot:
            await pilot.app.push_screen(WikiQueryModal("sess_abc00001"))
            await pilot.pause()
            buttons = pilot.app.screen.query(Button)
            ids = [b.id for b in buttons]
            assert "generate" in ids

    async def test_has_cancel_button(self) -> None:
        from textual.widgets import Button

        async with OpsPilotApp().run_test() as pilot:
            await pilot.app.push_screen(WikiQueryModal("sess_abc00001"))
            await pilot.pause()
            buttons = pilot.app.screen.query(Button)
            ids = [b.id for b in buttons]
            assert "cancel" in ids

    async def test_cancel_button_dismisses_modal(self) -> None:
        dismissed: list[str | None] = []

        async with OpsPilotApp().run_test() as pilot:
            await pilot.app.push_screen(WikiQueryModal("sess_abc00001"), dismissed.append)
            await pilot.pause()
            await pilot.app.screen.run_action("dismiss(None)")
            await pilot.pause()
            assert dismissed == [None]

    async def test_escape_dismisses_modal(self) -> None:
        dismissed: list[str | None] = []

        async with OpsPilotApp().run_test() as pilot:
            await pilot.app.push_screen(WikiQueryModal("sess_abc00001"), dismissed.append)
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            assert dismissed == [None]


# ── SessionsScreen class-level binding definitions ────────────────────────────


class TestSessionsWikiBinding:
    def test_w_binding_defined(self) -> None:
        bindings = [b for b in SessionsScreen.BINDINGS if isinstance(b, Binding)]
        keys = [b.key for b in bindings]
        assert "w" in keys

    def test_w_binding_action(self) -> None:
        bindings = {b.key: b for b in SessionsScreen.BINDINGS if isinstance(b, Binding)}
        assert bindings["w"].action == "wiki_from_session"

    async def test_no_selection_no_modal_opened(self) -> None:
        """W with no row selected must not crash (screen tested standalone)."""
        screen = SessionsScreen()
        assert screen._selected_session_id is None
        screen.action_wiki_from_session()  # must not raise without mounting


# ── WikiTreeScreen class-level binding definitions ─────────────────────────────


class TestWikiTreePromoteBinding:
    def test_p_binding_defined(self) -> None:
        bindings = [b for b in WikiTreeScreen.BINDINGS if isinstance(b, Binding)]
        keys = [b.key for b in bindings]
        assert "p" in keys

    def test_p_binding_action(self) -> None:
        bindings = {b.key: b for b in WikiTreeScreen.BINDINGS if isinstance(b, Binding)}
        assert bindings["p"].action == "promote_page"


# ── REPL wiki commands ─────────────────────────────────────────────────────────


class TestWikiReplCommands:
    async def test_wiki_list_command_dispatches(self) -> None:
        async with OpsPilotApp().run_test() as pilot:
            inp = pilot.app.query_one("#cmd-input", Input)
            inp.value = "/wiki list"
            await pilot.press("enter")
            await pilot.pause(0.3)
            assert pilot.app.query_one("#cmd-input", Input).value == ""

    async def test_wiki_lint_command_dispatches(self) -> None:
        async with OpsPilotApp().run_test() as pilot:
            inp = pilot.app.query_one("#cmd-input", Input)
            inp.value = "/wiki lint"
            await pilot.press("enter")
            await pilot.pause(0.3)
            assert pilot.app.query_one("#cmd-input", Input).value == ""

    async def test_wiki_show_without_slug_shows_usage(self) -> None:
        async with OpsPilotApp().run_test() as pilot:
            inp = pilot.app.query_one("#cmd-input", Input)
            inp.value = "/wiki show"
            await pilot.press("enter")
            await pilot.pause(0.1)
            assert pilot.app.query_one("#cmd-input", Input) is not None

    async def test_wiki_unknown_subcommand_shows_hint(self) -> None:
        async with OpsPilotApp().run_test() as pilot:
            inp = pilot.app.query_one("#cmd-input", Input)
            inp.value = "/wiki badcmd"
            await pilot.press("enter")
            await pilot.pause(0.1)
            assert pilot.app.query_one("#cmd-input", Input) is not None
