"""Playwright UI tests.

Run with: uv run pytest tests/test_ui.py --headed  (to see the browser)
"""

import re

from playwright.sync_api import expect


def send_command(page, cmd):
    """Type a command and press Enter, wait for the response."""
    input_el = page.locator("input[placeholder='direct command...']")
    input_el.fill(cmd)
    input_el.press("Enter")
    # Wait for WebSocket state update to propagate
    page.wait_for_timeout(500)


class TestMuteDoesNotHidePatterns:
    def test_mute_bass_keeps_drums_visible(self, server, page):
        page.goto(server)
        page.wait_for_timeout(500)

        send_command(page, "load examples/example.json")

        # Both patterns should be visible in the detail view
        detail_blocks = page.locator(".detail-pattern-block")
        expect(detail_blocks).to_have_count(2)

        # Get pattern names shown in detail view
        names = detail_blocks.locator(".pattern-name")
        expect(names.nth(0)).to_have_text("drums")
        expect(names.nth(1)).to_have_text("bass")

        # Mute bass
        send_command(page, "mute bass")

        # Both patterns should STILL be visible
        expect(detail_blocks).to_have_count(2)
        expect(names.nth(0)).to_have_text("drums")
        expect(names.nth(1)).to_have_text("bass")

    def test_mute_shows_indicator_in_overview(self, server, page):
        page.goto(server)
        page.wait_for_timeout(500)

        send_command(page, "load examples/example.json")
        send_command(page, "mute bass")

        # Bass should have .muted class in overview
        bass_item = page.locator(".pattern-list-item", has_text="bass")
        expect(bass_item).to_have_class(re.compile(r"muted"))

        # Drums should NOT have .muted class
        drums_item = page.locator(".pattern-list-item", has_text="drums")
        expect(drums_item).not_to_have_class(re.compile(r"muted"))


class TestVelocityBrightness:
    def test_different_velocities_have_different_opacity(self, server, page):
        page.goto(server)
        page.wait_for_timeout(500)

        send_command(page, "new test 8 9")
        send_command(page, "put test 0 kick 127")
        send_command(page, "put test 1 kick 30")

        # Find filled cells in the test pattern
        filled = page.locator(
            ".detail-pattern-block:has(.pattern-name:text('test')) .grid-cell.filled"
        )
        expect(filled).to_have_count(2)

        # High velocity cell should have higher opacity than low velocity
        loud_opacity = float(filled.nth(0).evaluate("el => getComputedStyle(el).opacity"))
        quiet_opacity = float(filled.nth(1).evaluate("el => getComputedStyle(el).opacity"))
        assert loud_opacity > quiet_opacity, (
            f"Loud ({loud_opacity}) should be brighter than quiet ({quiet_opacity})"
        )
        assert quiet_opacity >= 0.3, f"Quiet cell too dim: {quiet_opacity}"


class TestTransportUI:
    def test_play_button_toggles(self, server, page):
        page.goto(server)
        page.wait_for_timeout(500)

        send_command(page, "new beat 16 9")

        # Click play button
        play_btn = page.locator("button", has_text="Play")
        play_btn.click()
        page.wait_for_timeout(500)

        # Should show Stop now
        stop_btn = page.locator("button", has_text="Stop")
        expect(stop_btn).to_be_visible()

        # Click stop
        stop_btn.click()
        page.wait_for_timeout(500)
        expect(page.locator("button", has_text="Play")).to_be_visible()

    def test_bpm_display_updates(self, server, page):
        page.goto(server)
        page.wait_for_timeout(500)

        send_command(page, "bpm 140")

        # BPM is shown in an input within the transport bar
        bpm_input = page.locator(".transport-bpm input[type='number']")
        expect(bpm_input).to_have_value("140")


class TestPatternGridUI:
    def test_pattern_appears_in_detail_and_overview(self, server, page):
        page.goto(server)
        page.wait_for_timeout(500)

        send_command(page, "new drums 16 9")
        send_command(page, "put drums 0 kick 100")

        # Pattern should appear in detail view
        detail_block = page.locator(".detail-pattern-block", has_text="drums")
        expect(detail_block).to_be_visible()

        # Pattern should appear in overview
        overview_item = page.locator(".pattern-list-item", has_text="drums")
        expect(overview_item).to_be_visible()

    def test_new_pattern_shows_filled_cells(self, server, page):
        page.goto(server)
        page.wait_for_timeout(500)

        send_command(page, "new test 8 9")
        send_command(page, "put test 0,2,4,6 kick 100")

        filled = page.locator(
            ".detail-pattern-block:has(.pattern-name:text('test')) .grid-cell.filled"
        )
        expect(filled).to_have_count(4)


class TestOverviewUI:
    def test_select_command_highlights_pattern(self, server, page):
        page.goto(server)
        page.wait_for_timeout(500)

        send_command(page, "load examples/example.json")
        send_command(page, "select bass")

        # Bass should have the selected class after select command
        bass_item = page.locator(".pattern-list-item", has_text="bass")
        expect(bass_item).to_have_class(re.compile(r"selected"))


class TestCommandUI:
    def test_command_input_clears_after_submit(self, server, page):
        page.goto(server)
        page.wait_for_timeout(500)

        input_el = page.locator("input[placeholder='direct command...']")
        input_el.fill("new test 8 9")
        input_el.press("Enter")
        page.wait_for_timeout(300)

        # Input should be cleared after submission
        expect(input_el).to_have_value("")

    def test_command_output_appears_in_log(self, server, page):
        page.goto(server)
        page.wait_for_timeout(500)

        send_command(page, "new test 8 9")

        # Output should appear in the log container
        log = page.locator(".log-container").first
        expect(log).to_contain_text("Created")
