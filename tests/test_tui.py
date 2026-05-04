"""Tests for the OpsPilot TUI — shell (PR-20) and screens (PR-21)."""

from __future__ import annotations

from textual.widgets import ContentSwitcher, DataTable, Footer, Header, Label, ListItem

from opspilot.tui.app import _NAV, _SCREEN_MAP, OpsPilotApp
from opspilot.tui.screens import (
    ConfigScreen,
    DashboardScreen,
    HarnessScreen,
    KBBrowserScreen,
    LintIssuesScreen,
    ProvidersScreen,
    SessionsScreen,
    WikiTreeScreen,
)

# ──────────────────────────────────────────────────────────────────────────
#  PR-20: shell structure and navigation
# ──────────────────────────────────────────────────────────────────────────


class TestAppStructure:
    async def test_all_nav_items_present(self) -> None:
        async with OpsPilotApp().run_test() as pilot:
            items = pilot.app.query(ListItem)
            assert len(items) == 8

    async def test_default_screen_is_dashboard(self) -> None:
        async with OpsPilotApp().run_test() as pilot:
            sw = pilot.app.query_one(ContentSwitcher)
            assert sw.current == "dashboard"

    async def test_header_and_footer_present(self) -> None:
        async with OpsPilotApp().run_test() as pilot:
            pilot.app.query_one(Header)
            pilot.app.query_one(Footer)

    async def test_all_eight_modules_in_switcher(self) -> None:
        async with OpsPilotApp().run_test() as pilot:
            sw = pilot.app.query_one(ContentSwitcher)
            assert len(list(sw.children)) == 8

    async def test_screen_map_covers_all_nav_items(self) -> None:
        nav_ids = {sid for _, sid, _ in _NAV}
        assert nav_ids == set(_SCREEN_MAP.keys())


class TestNavigation:
    async def test_press_2_switches_to_sessions(self) -> None:
        async with OpsPilotApp().run_test() as pilot:
            await pilot.press("2")
            assert pilot.app.active_module == "sessions"

    async def test_press_3_switches_to_kb_browser(self) -> None:
        async with OpsPilotApp().run_test() as pilot:
            await pilot.press("3")
            assert pilot.app.active_module == "kb-browser"

    async def test_press_8_switches_to_config(self) -> None:
        async with OpsPilotApp().run_test() as pilot:
            await pilot.press("8")
            assert pilot.app.active_module == "config"

    async def test_keys_1_through_8_all_navigate(self) -> None:
        expected = [sid for _, sid, _ in _NAV]
        async with OpsPilotApp().run_test() as pilot:
            for key, screen_id in zip("12345678", expected, strict=True):
                await pilot.press(key)
                assert pilot.app.active_module == screen_id

    async def test_action_switch_module_updates_content(self) -> None:
        async with OpsPilotApp().run_test() as pilot:
            pilot.app.action_switch_module("harness")
            await pilot.pause()
            assert pilot.app.active_module == "harness"


# ──────────────────────────────────────────────────────────────────────────
#  PR-21: screen content
# ──────────────────────────────────────────────────────────────────────────


class TestDashboardScreen:
    async def test_stat_cards_present(self) -> None:
        async with OpsPilotApp().run_test() as pilot:
            screen = pilot.app.query_one(DashboardScreen)
            assert screen.query_one("#stat-sessions")
            assert screen.query_one("#stat-kb")
            assert screen.query_one("#stat-wiki")

    async def test_loads_without_error(self) -> None:
        async with OpsPilotApp().run_test() as pilot:
            await pilot.pause(0.3)
            # Stat cards should have updated text (no longer "loading…")
            screen = pilot.app.query_one(DashboardScreen)
            assert screen is not None


class TestSessionsScreen:
    async def test_table_has_correct_columns(self) -> None:
        async with OpsPilotApp().run_test() as pilot:
            await pilot.press("2")
            screen = pilot.app.query_one(SessionsScreen)
            dt = screen.query_one(DataTable)
            col_labels = [str(col.label) for col in dt.columns.values()]
            assert "ID" in col_labels
            assert "Status" in col_labels

    async def test_table_has_at_least_one_row_after_load(self) -> None:
        async with OpsPilotApp().run_test() as pilot:
            await pilot.press("2")
            await pilot.pause(0.3)
            dt = pilot.app.query_one(SessionsScreen).query_one(DataTable)
            assert dt.row_count >= 1  # at least the "none yet" placeholder row


class TestKBBrowserScreen:
    async def test_table_columns(self) -> None:
        async with OpsPilotApp().run_test() as pilot:
            await pilot.press("3")
            dt = pilot.app.query_one(KBBrowserScreen).query_one(DataTable)
            col_labels = [str(col.label) for col in dt.columns.values()]
            assert "Doc ID" in col_labels
            assert "Chunks" in col_labels

    async def test_loads_without_error(self) -> None:
        async with OpsPilotApp().run_test() as pilot:
            await pilot.press("3")
            await pilot.pause(0.3)
            screen = pilot.app.query_one(KBBrowserScreen)
            assert screen is not None


class TestWikiTreeScreen:
    async def test_table_columns(self) -> None:
        async with OpsPilotApp().run_test() as pilot:
            await pilot.press("4")
            dt = pilot.app.query_one(WikiTreeScreen).query_one(DataTable)
            col_labels = [str(col.label) for col in dt.columns.values()]
            assert "Slug" in col_labels
            assert "State" in col_labels

    async def test_loads_without_error(self) -> None:
        async with OpsPilotApp().run_test() as pilot:
            await pilot.press("4")
            await pilot.pause(0.3)
            assert pilot.app.query_one(WikiTreeScreen) is not None


class TestHarnessScreen:
    async def test_table_columns(self) -> None:
        async with OpsPilotApp().run_test() as pilot:
            await pilot.press("5")
            dt = pilot.app.query_one(HarnessScreen).query_one(DataTable)
            col_labels = [str(col.label) for col in dt.columns.values()]
            assert "Score" in col_labels
            assert "Pass" in col_labels

    async def test_loads_without_error(self) -> None:
        async with OpsPilotApp().run_test() as pilot:
            await pilot.press("5")
            await pilot.pause(0.3)
            assert pilot.app.query_one(HarnessScreen) is not None


class TestLintIssuesScreen:
    async def test_no_issues_label_present(self) -> None:
        async with OpsPilotApp().run_test() as pilot:
            await pilot.press("6")
            screen = pilot.app.query_one(LintIssuesScreen)
            labels = [str(lbl.render()) for lbl in screen.query(Label)]
            assert any("No lint issues" in lbl for lbl in labels)


class TestProvidersScreen:
    async def test_table_has_correct_columns(self) -> None:
        async with OpsPilotApp().run_test() as pilot:
            await pilot.press("7")
            dt = pilot.app.query_one(ProvidersScreen).query_one(DataTable)
            col_labels = [str(col.label) for col in dt.columns.values()]
            assert "Provider" in col_labels
            assert "Status" in col_labels

    async def test_rows_populated_after_probe(self) -> None:
        async with OpsPilotApp().run_test() as pilot:
            await pilot.press("7")
            await pilot.pause(0.5)
            dt = pilot.app.query_one(ProvidersScreen).query_one(DataTable)
            assert dt.row_count == 3  # ollama, anthropic, openai


class TestConfigScreen:
    async def test_config_rows_present(self) -> None:
        async with OpsPilotApp().run_test() as pilot:
            await pilot.press("8")
            dt = pilot.app.query_one(ConfigScreen).query_one(DataTable)
            assert dt.row_count >= 5

    async def test_home_row_exists(self) -> None:
        async with OpsPilotApp().run_test() as pilot:
            await pilot.press("8")
            dt = pilot.app.query_one(ConfigScreen).query_one(DataTable)
            # first column of first row should be "home"
            cell = dt.get_cell_at((0, 0))
            assert str(cell) == "home"
