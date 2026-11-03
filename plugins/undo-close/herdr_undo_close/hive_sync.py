"""Keep hive's records right when a restored chat was a hive bee.

hive stores each bee's tab id. A bee resumed in a new tab would otherwise be
"closed" by `hive close` without its tab closing. `hive sync` re-reads the
tab ids, but only once the resumed claude has started and Herdr reports its
session, so it runs in the background after a short wait.
"""

import glob
import json
import os
import shutil
import subprocess
from typing import Any, Dict, Iterable, List

SYNC_DELAY_S = 20


def state_dirs():
    # type: () -> List[str]
    home = os.path.expanduser("~")
    env = os.environ.get("HIVE_STATE_DIR")
    candidates = ([env] if env else []) + [os.path.join(home, ".local/state/herd"),
                                            os.path.join(home, ".local/state/hive")]
    return [d for d in candidates if os.path.isdir(d)]


def queens_of(sessions):
    # type: (Iterable[str]) -> List[str]
    """Hive slugs with one of these chat sessions as a bee."""
    wanted = set(s for s in sessions if s)
    slugs = set()
    if not wanted:
        return []
    for d in state_dirs():
        for path in glob.glob(os.path.join(d, "*.json")):
            try:
                with open(path) as f:
                    data = json.load(f)
            except (OSError, ValueError):
                continue
            workers = data.get("workers") if isinstance(data, dict) else None
            if isinstance(workers, list) and any(
                    isinstance(w, dict) and w.get("session_id") in wanted for w in workers):
                slugs.add(os.path.splitext(os.path.basename(path))[0])
    return sorted(slugs)


def resumed_sessions(result):
    # type: (Dict[str, Any]) -> List[str]
    return [p.get("session_id") for p in result.get("relaunched") or []
            if p.get("kind") == "agent" and p.get("session_id")]


def schedule_sync(result):
    # type: (Dict[str, Any]) -> List[str]
    """Start a delayed `hive sync` for each queen of a resumed bee. Returns
    the slugs scheduled. Never raises: a restore that worked stays worked."""
    hive = shutil.which("hive") or os.path.expanduser("~/.local/bin/hive")
    if not os.path.exists(hive):
        return []
    slugs = queens_of(resumed_sessions(result))
    for slug in slugs:
        try:
            subprocess.Popen(["/bin/sh", "-c", 'sleep %d; exec "$0" sync --orch "$1"' % SYNC_DELAY_S, hive, slug],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        except OSError:
            pass
    return slugs
