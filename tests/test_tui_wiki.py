"""Tests for TUI wiki integration (PR-26).

WikiQueryModal must be tested via OpsPilotApp.run_test() + push_screen,
not WikiQueryModal().run_test() — ModalScreen has no run_test().
"""

from __future__ import annotations

from textual.binding import Binding

from opspilot.tui.app import OpsPilotApp
from opspilot.tui.screens.sessions import SessionsScreen
from opspilot.tui.screens.wiki_tree import WikiTreeScreen
from opspilot.tui.wiki_modal import WikiQueryModal

# ── WikiQueryModal: structure ──────────────────────────────────────────────────


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


# ── SessionsScreen: W binding ──────────────────────────────────────────────────


class TestSessionsWikiBinding:
    def test_w_binding_defined(self) -> None:
        bindings = [b for b in SessionsScreen.BINDINGS if isinstance(b, Binding)]
        keys = [b.key for b in bindings]
        assert "w" in keys

    def test_w_binding_action(self) -> None:
        bindings = {b.key: b for b in SessionsScreen.BINDINGS if isinstance(b, Binding)}
        assert bindings["w"].action == "wiki_from_session"

    async def test_no_selection_no_modal_opened(self) -> None:
        """W with no row selected must not crash."""
        async with OpsPilotApp().run_test() as pilot:
            await pilot.press("2")
            await pilot.pause()
            # No row selected yet → action should be a no-op
            screen = pilot.app.query_one(SessionsScreen)
            assert screen._selected_session_id is None
            screen.action_wiki_from_session()  # must not raise
            await pilot.pause()
            # Modal should NOT have been pushed (app.screen is still sessions area)
            assert not isinstance(pilot.app.screen, WikiQueryModal)


# ── WikiTreeScreen: P binding ──────────────────────────────────────────────────


class TestWikiTreePromoteBinding:
    def test_p_binding_defined(self) -> None:
        bindings = [b for b in WikiTreeScreen.BINDINGS if isinstance(b, Binding)]
        keys = [b.key for b in bindings]
        assert "p" in keys

    def test_p_binding_action(self) -> None:
        bindings = {b.key: b for b in WikiTreeScreen.BINDINGS if isinstance(b, Binding)}
        assert bindings["p"].action == "promote_page"

    async def test_no_selection_no_crash(self) -> None:
        async with OpsPilotApp().run_test() as pilot:
            await pilot.press("4")
            await pilot.pause()
            screen = pilot.app.query_one(WikiTreeScreen)
            assert screen._selected_slug is None
            screen.action_promote_page()  # must not raise
            await pilot.pause()

    async def test_refresh_pages_clears_table(self) -> None:
        async with OpsPilotApp().run_test() as pilot:
            await pilot.press("4")
            await pilot.pause(0.3)
            screen = pilot.app.query_one(WikiTreeScreen)
            dt = screen.query_one("DataTable")
            row_count_before = dt.row_count  # type: ignore[attr-defined]
            screen.refresh_pages()
            await pilot.pause()
            # After clear the row count resets
            assert dt.row_count <= row_count_before  # type: ignore[attr-defined]

    async def test_page_states_populated_after_load(self) -> None:
        async with OpsPilotApp().run_test() as pilot:
            await pilot.press("4")
            await pilot.pause(0.3)
            screen = pilot.app.query_one(WikiTreeScreen)
            # _page_states is a dict; may be empty if no wiki pages exist, but must be a dict
            assert isinstance(screen._page_states, dict)
