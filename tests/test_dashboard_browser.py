import os
import tempfile
import threading
import unittest
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from analytics.fixtures import load_fixture_dashboard_datasets
from dashboard.build import build_site


@unittest.skipUnless(
    os.getenv("RUN_BROWSER_TESTS") == "1",
    "Set RUN_BROWSER_TESTS=1 after installing Playwright Chromium",
)
class DashboardBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright

        cls._temporary_directory = tempfile.TemporaryDirectory()
        cls.site_dir = Path(cls._temporary_directory.name) / "site"
        build_site(load_fixture_dashboard_datasets(), cls.site_dir)

        handler = lambda *args, **kwargs: SimpleHTTPRequestHandler(
            *args, directory=str(cls.site_dir), **kwargs
        )
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"

        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        cls.server.shutdown()
        cls.server.server_close()
        cls.server_thread.join(timeout=5)
        cls._temporary_directory.cleanup()

    def test_system_theme_toggle_persistence_and_plot_restyle(self):
        context = self.browser.new_context(color_scheme="dark")
        page = context.new_page()
        page.goto(self.base_url)
        page.wait_for_selector("#submission-status-chart.js-plotly-plot")
        page.evaluate("document.fonts.ready")

        self.assertEqual(page.locator("html").get_attribute("data-theme"), "dark")
        self.assertEqual(
            page.locator("body").evaluate("element => getComputedStyle(element).backgroundColor"),
            "rgb(11, 17, 32)",
        )
        self.assertIn(
            "Montserrat",
            page.locator("h1").evaluate("element => getComputedStyle(element).fontFamily"),
        )
        self.assertIn(
            "Roboto",
            page.locator("body").evaluate("element => getComputedStyle(element).fontFamily"),
        )
        self.assertEqual(page.locator(".brand-logo").first.evaluate("image => image.naturalWidth"), 914)
        self.assertEqual(page.locator(".sidebar .brand-logo").bounding_box()["width"], 42)
        self.assertEqual(page.get_by_text("Demo data").count(), 0)
        page.locator("[data-theme-toggle]").click()
        self.assertEqual(page.locator("html").get_attribute("data-theme"), "light")
        page.reload()
        self.assertEqual(page.locator("html").get_attribute("data-theme"), "light")
        plot_font = page.locator("#submission-status-chart").evaluate(
            "chart => chart.layout.font.color"
        )
        self.assertEqual(plot_font, "#6b7280")
        context.close()

    def test_filter_values_fit_at_supported_viewports(self):
        context = self.browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()
        page.goto(f"{self.base_url}/builders/index.html")
        status = page.locator("[data-table-status]")
        status.select_option(label="Unchecked/Unassigned")

        for width in (1440, 1024, 390):
            page.set_viewport_size({"width": width, "height": 900})
            self.assertEqual(status.input_value(), "unchecked/unassigned")
            self.assertGreaterEqual(status.bounding_box()["width"], 180)

        context.close()

    def test_mobile_drawer_keyboard_behavior_and_navigation(self):
        context = self.browser.new_context(viewport={"width": 390, "height": 844})
        page = context.new_page()
        page.goto(self.base_url)
        open_button = page.locator("[data-drawer-open]")
        open_button.click()
        self.assertEqual(open_button.get_attribute("aria-expanded"), "true")
        page.keyboard.press("Escape")
        self.assertEqual(open_button.get_attribute("aria-expanded"), "false")

        open_button.click()
        page.locator('.nav-link[href="builders/index.html"]').click()
        page.wait_for_url("**/builders/index.html")
        self.assertEqual(page.locator("body").get_attribute("data-page"), "builders")
        context.close()

    def test_builder_filters_show_distinct_no_results_state(self):
        context = self.browser.new_context()
        page = context.new_page()
        page.goto(f"{self.base_url}/builders/index.html")
        page.locator("[data-table-search]").fill("no-builder-has-this-name")

        self.assertTrue(page.locator("[data-filter-empty]").is_visible())
        self.assertEqual(page.locator("[data-visible-count]").text_content(), "0")
        self.assertTrue(page.locator("[data-intervention-table]").is_hidden())
        context.close()

    def test_builder_milestone_filter_combines_with_other_filters(self):
        context = self.browser.new_context()
        page = context.new_page()
        page.goto(f"{self.base_url}/builders/index.html")
        page.locator("[data-table-search]").fill("maria-reviewer")
        page.locator("[data-table-milestone]").select_option("m3")
        page.locator("[data-table-status]").select_option("passed")

        self.assertEqual(page.locator("[data-visible-count]").text_content(), "1")
        self.assertEqual(
            page.locator("[data-intervention-row]:visible .builder-link").text_content(),
            "isabel-ingest",
        )
        context.close()
