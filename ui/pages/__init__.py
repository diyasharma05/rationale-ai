"""Page registry.

The nav order is defined here, next to the pages themselves, rather than as a
literal list in app.py that has to be kept in step with a six-branch if/elif.
"""
from . import (dashboard, data_explorer, investigation, ledger, lineage,
               outbox,
               live_feed, under_the_hood)

PAGES = {
    "Dashboard": dashboard.render,
    "Live Feed": live_feed.render,
    "Data": data_explorer.render,
    "Investigation": investigation.render,
    "Lineage": lineage.render,
    "Outbox": outbox.render,
    "Decision Ledger": ledger.render,
    "Under the Hood": under_the_hood.render,
}

# Pages that are scoped to a single analysis month, and so get the window
# picker in the top bar. The Live Feed runs its own replay clock and the
# Ledger and Under the Hood are cross-period views.
WINDOWED = ("Dashboard", "Data", "Investigation")
