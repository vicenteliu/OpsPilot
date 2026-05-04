"""Tests for the OpsPilot TUI shell (PR-20)."""

from __future__ import annotations

from textual.widgets import ContentSwitcher, Footer, Header, ListItem

from opspilot.tui.app import OpsPilotApp, _NAV, _SCREEN_MAP


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
            for key, screen_id in zip("12345678", expected):
                await pilot.press(key)
                assert pilot.app.active_module == screen_id

    async def test_action_switch_module_updates_content(self) -> None:
        async with OpsPilotApp().run_test() as pilot:
            pilot.app.action_switch_module("harness")
            await pilot.pause()
            assert pilot.app.active_module == "harness"
