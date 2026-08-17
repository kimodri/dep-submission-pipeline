import tempfile
import unittest
from pathlib import Path

from analytics.fixtures import load_fixture_dashboard_datasets
from dashboard.build import build_site


class DashboardBuildTests(unittest.TestCase):
    def test_builds_all_pages_assets_and_relative_links(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "site"
            build_site(load_fixture_dashboard_datasets(), output)

            expected = (
                output / "index.html",
                output / "builders" / "index.html",
                output / "reviewers" / "index.html",
                output / "assets" / "css" / "dashboard.css",
                output / "assets" / "js" / "dashboard.js",
                output / "assets" / "vendor" / "plotly.min.js",
                output / "assets" / "images" / "dep-logo.png",
                output / "assets" / "fonts" / "montserrat-variable.ttf",
                output / "assets" / "fonts" / "roboto-variable.ttf",
                output / "assets" / "fonts" / "noto-sans-variable.ttf",
            )
            for path in expected:
                self.assertTrue(path.is_file(), path)

            overview = (output / "index.html").read_text(encoding="utf-8")
            builders = (output / "builders" / "index.html").read_text(encoding="utf-8")
            reviewers = (output / "reviewers" / "index.html").read_text(encoding="utf-8")
            self.assertIn('href="assets/css/dashboard.css"', overview)
            self.assertIn('href="../assets/css/dashboard.css"', builders)
            self.assertIn('href="../index.html"', reviewers)
            self.assertIn("Builder Submission Dashboard", overview)
            self.assertIn("Intervention Queue", builders)
            self.assertNotIn('<th scope="col">Owner</th>', builders)
            self.assertNotIn('<th scope="col">Next action</th>', builders)
            self.assertIn("Reviewer Workload", reviewers)
            self.assertIn("Generated ", overview)
            self.assertIn('assets/images/dep-logo.png', overview)
            self.assertIn('../assets/images/dep-logo.png', builders)
            self.assertIn('width="42" height="42"', overview)
            self.assertIn('width="34" height="34"', overview)
            self.assertNotIn("Demo data", overview)
            self.assertIn('aria-current="page"', builders)

    def test_generated_site_does_not_contain_environment_secret_names(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "site"
            build_site(load_fixture_dashboard_datasets(), output)

            html = "\n".join(
                path.read_text(encoding="utf-8") for path in output.rglob("*.html")
            )
            self.assertNotIn("MOTHERDUCK_TOKEN", html)
            self.assertNotIn("DEP_GITHUB_TOKEN", html)
            self.assertNotIn("md:", html)
