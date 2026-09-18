"""Architectural boundaries, enforced.

A refactor is only worth doing if it stays done. These ~40 lines are what
stop the layering decaying back into one file the week after the demo.
"""
import ast
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
PAGES = sorted((ROOT / "ui" / "pages").glob("*.py"))
SERVICES = sorted((ROOT / "services").glob("*.py"))
COMPONENTS = sorted((ROOT / "ui" / "components").glob("*.py"))


def imports(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module.split(".")[0])
    return out


def string_constants(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)]


@pytest.mark.parametrize("path", SERVICES, ids=lambda p: p.name)
def test_services_do_not_import_streamlit(path):
    """Services are view models, not views. Keeping Streamlit out is what
    makes them callable from pytest, from eval.py and from the API."""
    assert "streamlit" not in imports(path)


@pytest.mark.parametrize("path", COMPONENTS, ids=lambda p: p.name)
def test_components_do_not_reach_into_services_or_the_app(path):
    """A component renders what it is given. If it can fetch its own data it
    stops being reusable and starts being a page."""
    assert "services" not in imports(path)


@pytest.mark.parametrize("path", PAGES, ids=lambda p: p.name)
def test_pages_do_not_build_sql(path):
    """Query construction belongs in engine/. The Data page used to
    f-string its own SELECT, including the date slider."""
    for s in string_constants(path):
        upper = s.upper()
        assert not ("SELECT " in upper and " FROM " in upper), \
            f"{path.name} builds SQL: {s[:60]!r}"


def test_only_the_shell_and_nav_may_rerun():
    """st.rerun() is control flow. Scattering it is how three copies of the
    same deep-link block appeared in the first place."""
    allowed = {"app.py", "context.py"}
    offenders = []
    for path in list(PAGES) + list(COMPONENTS) + [ROOT / "app.py",
                                                  ROOT / "ui" / "context.py"]:
        if path.name in allowed:
            continue
        if "st.rerun()" in path.read_text(encoding="utf-8"):
            offenders.append(path.name)
    # live_feed re-runs at app scope to stop its own replay timer, which is a
    # genuine exception: the fragment cannot re-decorate itself.
    assert set(offenders) <= {"live_feed.py"}, offenders


def test_app_shell_stays_small():
    """app.py is bootstrap, sidebar, control bar and router. It was 1654
    lines; if it creeps back past ~300 something has been put in the wrong
    place."""
    n = len((ROOT / "app.py").read_text(encoding="utf-8").splitlines())
    assert n < 300, f"app.py has grown to {n} lines"


def test_every_page_exposes_render():
    from ui.pages import PAGES as REGISTRY
    assert len(REGISTRY) == 7
    for name, fn in REGISTRY.items():
        assert callable(fn), name
