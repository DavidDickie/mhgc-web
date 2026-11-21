"""Stage 3 API conveniences for the UI: the per-seat stats series, the rulebook and the
catalogue's spy-mission help."""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.main import create_app
from tests import test_api

H = test_api.H
env = test_api.env          # the two-seat game fixture


def test_stats_series_per_seat(env):
    c, gid, t1, t2 = env["c"], env["gid"], env["t1"], env["t2"]
    assert c.get(f"/api/games/{gid}/stats").status_code == 401
    for _ in range(3):
        assert c.post(f"/api/games/{gid}/force", headers=H(t1)).status_code == 200
    s1 = c.get(f"/api/games/{gid}/stats", headers=H(t1)).json()
    assert s1["current"] == 3 and [r["turn"] for r in s1["turns"]] == [0, 1, 2, 3]
    row = s1["turns"][-1]
    assert set(row) >= {"values", "ranks", "vp", "economy", "events", "combats"}
    assert "POP" in row["values"] and "eu" in row["economy"]
    # each row is the seat's own report: it matches /view's results for that turn
    v = c.get(f"/api/games/{gid}/view?turn=2", headers=H(t1)).json()
    assert s1["turns"][2]["values"] == v["results"]["stats"]["values"]
    assert s1["turns"][2]["economy"] == v["results"]["economy"]
    # seat 2 gets its own numbers, and nothing of seat 1's beyond what its own view has
    s2 = c.get(f"/api/games/{gid}/stats", headers=H(t2)).json()
    v2 = c.get(f"/api/games/{gid}/view?turn=3", headers=H(t2)).json()
    assert s2["turns"][3]["economy"] == v2["results"]["economy"]
    # cached past turns survive a restart identically
    again = TestClient(create_app(env["dir"])).get(f"/api/games/{gid}/stats",
                                                   headers=H(t1)).json()
    assert json.dumps(again) == json.dumps(s1)


def test_rulebook_served_as_markdown(tmp_path):
    c = TestClient(create_app(tmp_path))
    r = c.get("/api/rulebook")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/markdown")
    assert r.text.startswith("# MEGA HYPER GALACTIC CONQUEST")


def test_catalogue_spy_help_and_ui_assets(tmp_path):
    c = TestClient(create_app(tmp_path))
    orders = {o["code"]: o for o in c.get("/api/orders/catalogue").json()["orders"]}
    assert orders["SOS"]["help"].startswith("Spy out system")
    assert all(o["help"] != "Spy mission" for o in orders.values())
    page = c.get("/").text
    assert "/static/app.js" in page
    assert c.get("/static/app.js").status_code == 200
    assert c.get("/static/style.css").status_code == 200


def test_catalogue_every_order_has_help(tmp_path):
    """The UI's "add any order" picker lists orders by their help line, so every order needs
    one.  The retired display options are not in the catalogue at all."""
    c = TestClient(create_app(tmp_path))
    cat = c.get("/api/orders/catalogue").json()
    from mhgc.orders import ORDER_SPECS
    assert {o["code"] for o in cat["orders"]} == set(ORDER_SPECS)
    for o in cat["orders"]:
        assert o["help"].strip(), o["code"]
        assert all(a["help"] for a in o["args"]), o["code"]
    by = {o["code"]: o for o in cat["orders"]}
    assert not {"AUTOFLEET", "NOAUTOFLEET", "TRACKSCAN", "NOTRACKSCAN"} & set(by)
    assert "pref" not in cat["categories"]
    tp = {a["name"]: a for a in by["TP"]["args"]}
    assert "combat troop" in tp["amount"]["help"]          # TP <system> C <CT number> <to>
    assert "another race" in {a["name"]: a for a in by["SL"]["args"]}["ship"]["help"]


def test_ui_order_form_reads_fields_by_name():
    """Regression: the order form read `form.elements[name]`, and for the field called "item"
    (L, U, UG, SL, FL, FU, FUG, TP) that is HTMLFormControlsCollection.item(), a method, so the
    value was silently dropped ("L 9835 2": missing argument: item).  Use namedItem()."""
    from pathlib import Path
    ui = Path(__file__).resolve().parent.parent / "app" / "ui"
    assert "elements.namedItem(" in (ui / "orders.js").read_text()
    for f in ui.glob("*.js"):
        code = [ln for ln in f.read_text().splitlines() if not ln.strip().startswith("//")]
        assert not any(".elements[" in ln for ln in code), f.name
