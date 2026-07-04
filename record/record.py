import json, os, glob
from playwright.sync_api import sync_playwright

BASE = os.path.dirname(os.path.abspath(__file__))
dash = json.load(open(os.path.join(BASE, "dash.json")))
windows = json.load(open(os.path.join(BASE, "windows.json")))

CHAT = ("You should stop “Monsoon Growth - OPC UP FY26” (SCHBLD022) — ROI -5.1, a dud that "
        "paid for sales that would have happened anyway. Scale “Growth Booster - OPC RJ FY26” "
        "instead (15.2×). Also: distributor Choudhury, Bakshi & Mahara is loading inventory — only "
        "56% sells through. → Do this: stop the UP scheme, recover the over-claims, scale Rajasthan.")
REPORT = ("This period, 3 of 6 active schemes are profitable, giving a portfolio health score of 69/100. "
          "The standout is Growth Booster - OPC RJ, returning about Rs 15 for every Rs 1 spent — scale it. "
          "The most urgent leak is Rs 54,348 across over-claims and money-losing schemes, recoverable before "
          "the next payout run. Putty schemes are also stacking to roughly a 12% effective discount versus a "
          "~5% headline. Recommended action: recover the over-claims now, cap per-invoice discounts, and "
          "redesign the loss-making Monsoon Growth - OPC UP scheme.")
CLAIM = {"mode": "llm", "verdict": "OVER-CLAIM",
         "note": ("Murthy, Khare and Lanka claimed Rs 8,400 against scheme SCHPHA008 but earned only "
                  "Rs 5,250 — Rs 3,150 over entitlement. → Do this: hold this claim and recover the gap "
                  "before payout."),
         "extracted": {"partner_name": "Murthy, Khare and Lanka", "scheme_id": "SCHPHA008", "claimed_amount": 8400}}

def handle(route):
    url = route.request.url
    if "/api/windows" in url:
        route.fulfill(content_type="application/json", body=json.dumps(windows)); return
    if "/api/dashboard" in url:
        win = "FY2024-25" if "FY2024-25" in url else "ttm"
        route.fulfill(content_type="application/json", body=json.dumps(dash[win])); return
    if "/api/report" in url:
        route.fulfill(content_type="application/json", body=json.dumps(
            {"mode": "llm", "health": 69, "narrative": REPORT, "headline_at_risk": "Rs 54,348"})); return
    if "/api/claim-check" in url:
        route.fulfill(content_type="application/json", body=json.dumps(CLAIM)); return
    if url.rstrip("/").endswith("/chat"):
        route.fulfill(content_type="application/json", body=json.dumps(
            {"session_id": "s-demo", "answer": CHAT, "mode": "llm"})); return
    route.continue_()

def smooth_to(pg, y):
    pg.evaluate(f"window.scrollTo({{top:{y},behavior:'smooth'}})")

with sync_playwright() as p:
    b = p.chromium.launch(args=["--force-color-profile=srgb"])
    ctx = b.new_context(viewport={"width": 1280, "height": 720},
                        device_scale_factor=2,
                        record_video_dir=os.path.join(BASE, "vid"),
                        record_video_size={"width": 1280, "height": 720})
    pg = ctx.new_page()
    pg.route("**/api/**", handle)
    pg.route("**/chat", handle)
    pg.goto("file://" + os.path.join(BASE, "index_record.html"))
    pg.wait_for_timeout(3000)

    # 1) Cockpit + KPIs (hero)  ~ to 18s
    pg.wait_for_timeout(15000)
    # 2) What needs you (scroll down slowly) ~ to 38s
    smooth_to(pg, 230); pg.wait_for_timeout(9000)
    smooth_to(pg, 430); pg.wait_for_timeout(10000)
    # 3) Clear wins + chart ~ to 52s
    smooth_to(pg, 760); pg.wait_for_timeout(13000)
    # 4) Copilot ask ~ to 76s
    smooth_to(pg, 0); pg.wait_for_timeout(1500)
    pg.fill("#q", "Which scheme should I stop, and who is loading inventory?")
    pg.wait_for_timeout(900)
    pg.click("#send")
    pg.wait_for_timeout(20000)
    # 5) Timeline switch to FY2024-25 ~ to 96s
    pg.select_option("#winSel", "FY2024-25")
    pg.wait_for_timeout(4000)
    smooth_to(pg, 300); pg.wait_for_timeout(12000)
    smooth_to(pg, 0); pg.wait_for_timeout(2000)
    pg.select_option("#winSel", "ttm")
    pg.wait_for_timeout(2000)
    # 6) Leadership report ~ to 112s
    pg.click("#reportBtn")
    pg.wait_for_timeout(14000)
    pg.click("#mClose")
    pg.wait_for_timeout(1000)
    # 7) Multimodal claim check ~ to 128s
    pg.set_input_files("#claimFile", os.path.join(BASE, "..", "..", "NovaCure_Sample_Claim_SCHPHA008.png"))
    pg.wait_for_timeout(13000)
    pg.click("#mClose")
    pg.wait_for_timeout(2500)

    path = pg.video.path()
    ctx.close()
    b.close()
    print("VIDEO_PATH", path)
print("DONE")
