from datetime import datetime
from pathlib import Path
import shutil
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader, select_autoescape
from plotly.offline import get_plotlyjs

from analytics.datasets import DashboardDatasets, validate_dashboard_datasets
from dashboard.pages import builders_context, overview_context, reviewers_context


DASHBOARD_ROOT = Path(__file__).resolve().parent
PAGE_SPECS = (
    ("overview", "overview.html", Path("index.html"), overview_context),
    ("builders", "builders.html", Path("builders/index.html"), builders_context),
    ("reviewers", "reviewers.html", Path("reviewers/index.html"), reviewers_context),
)


def _navigation(asset_prefix: str) -> list[dict[str, str]]:
    return [
        {"id": "overview", "label": "Overview", "href": f"{asset_prefix}index.html"},
        {
            "id": "builders",
            "label": "Builders",
            "href": f"{asset_prefix}builders/index.html",
        },
        {
            "id": "reviewers",
            "label": "Reviewers",
            "href": f"{asset_prefix}reviewers/index.html",
        },
    ]


def _environment() -> Environment:
    return Environment(
        loader=FileSystemLoader(DASHBOARD_ROOT / "templates"),
        autoescape=select_autoescape(("html", "xml")),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def build_site(datasets: DashboardDatasets, output_dir: Path) -> None:
    datasets = validate_dashboard_datasets(datasets)
    output_dir = Path(output_dir)
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)

    assets_dir = output_dir / "assets"
    shutil.copytree(DASHBOARD_ROOT / "static", assets_dir)
    vendor_dir = assets_dir / "vendor"
    vendor_dir.mkdir(parents=True)
    (vendor_dir / "plotly.min.js").write_text(get_plotlyjs(), encoding="utf-8")

    generated_at = datetime.now(ZoneInfo("Asia/Manila")).strftime(
        "%B %-d, %Y at %-I:%M %p PHT"
    )
    environment = _environment()

    for page_id, template_name, destination, context_builder in PAGE_SPECS:
        asset_prefix = "" if destination.parent == Path(".") else "../"
        context = {
            "page_id": page_id,
            "asset_prefix": asset_prefix,
            "navigation": _navigation(asset_prefix),
            "generated_at": generated_at,
            **context_builder(datasets),
        }
        rendered = environment.get_template(template_name).render(**context)
        output_path = output_dir / destination
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered, encoding="utf-8")
