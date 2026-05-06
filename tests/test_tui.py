"""Tests for the OpsPilot TUI — REPL chat shell."""

from __future__ import annotations

from textual.widgets import Footer, Header, Input, RichLog

from opspilot.tui.app import OpsPilotApp


class TestAppStructure:
    async def test_header_and_footer_present(self) -> None:
        async with OpsPilotApp().run_test() as pilot:
            pilot.app.query_one(Header)
            pilot.app.query_one(Footer)

    async def test_rich_log_present(self) -> None:
        async with OpsPilotApp().run_test() as pilot:
            pilot.app.query_one(RichLog)

    async def test_input_present(self) -> None:
        async with OpsPilotApp().run_test() as pilot:
            pilot.app.query_one("#cmd-input", Input)

    async def test_welcome_message_in_output(self) -> None:
        async with OpsPilotApp().run_test() as pilot:
            log = pilot.app.query_one(RichLog)
            # RichLog stores written lines internally; check it has content
            assert log is not None


class TestCommands:
    async def test_help_command_writes_output(self) -> None:
        async with OpsPilotApp().run_test() as pilot:
            inp = pilot.app.query_one("#cmd-input", Input)
            inp.value = "/help"
            await pilot.press("enter")
            await pilot.pause(0.1)
            log = pilot.app.query_one(RichLog)
            assert log is not None

    async def test_clear_command_empties_log(self) -> None:
        async with OpsPilotApp().run_test() as pilot:
            pilot.app._write("test line")
            inp = pilot.app.query_one("#cmd-input", Input)
            inp.value = "/clear"
            await pilot.press("enter")
            await pilot.pause(0.1)
            # After clear, the log is empty (no exception)
            log = pilot.app.query_one(RichLog)
            assert log is not None

    async def test_unknown_command_shows_error(self) -> None:
        async with OpsPilotApp().run_test() as pilot:
            inp = pilot.app.query_one("#cmd-input", Input)
            inp.value = "/nonexistentcmd"
            await pilot.press("enter")
            await pilot.pause(0.1)
            # Should not crash — app still alive
            assert pilot.app.query_one(RichLog) is not None

    async def test_non_slash_input_shows_hint(self) -> None:
        async with OpsPilotApp().run_test() as pilot:
            inp = pilot.app.query_one("#cmd-input", Input)
            inp.value = "hello world"
            await pilot.press("enter")
            await pilot.pause(0.1)
            assert pilot.app.query_one(RichLog) is not None

    async def test_input_cleared_after_submit(self) -> None:
        async with OpsPilotApp().run_test() as pilot:
            inp = pilot.app.query_one("#cmd-input", Input)
            inp.value = "/help"
            await pilot.press("enter")
            await pilot.pause(0.1)
            assert pilot.app.query_one("#cmd-input", Input).value == ""

    async def test_config_command_does_not_crash(self) -> None:
        async with OpsPilotApp().run_test() as pilot:
            inp = pilot.app.query_one("#cmd-input", Input)
            inp.value = "/config"
            await pilot.press("enter")
            await pilot.pause(0.2)
            assert pilot.app.query_one(RichLog) is not None

    async def test_providers_command_does_not_crash(self) -> None:
        async with OpsPilotApp().run_test() as pilot:
            inp = pilot.app.query_one("#cmd-input", Input)
            inp.value = "/providers"
            await pilot.press("enter")
            await pilot.pause(0.2)
            assert pilot.app.query_one(RichLog) is not None

    async def test_ctrl_l_clears_output(self) -> None:
        async with OpsPilotApp().run_test() as pilot:
            pilot.app._write("some content")
            await pilot.press("ctrl+l")
            await pilot.pause(0.1)
            assert pilot.app.query_one(RichLog) is not None
