import json, os, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
from playwright.sync_api import sync_playwright

BASE = os.path.dirname(os.path.abspath(__file__))
FR = os.path.join(BASE, "frames"); os.makedirs(FR, exist_ok=True)
dash = json.load(open(os.path.join(BASE, "dash.json")))
windows = json.load(open(os.path.join(BASE, "windows.json")))
HTML = open(os.path.join(BASE, "index_record.html"), "rb").read()

CHAT = ("You should stop “Monsoon Growth - OPC UP FY26” (SCHBLD022) — ROI -5.1, a dud that paid for "
        "sales that would have happened anyway. Scale “Growth Booster - OPC RJ FY26” instead (15.2×). "
        "Also: distributor Choudhury, Bakshi & Mahara is loading inventory — only 56% sells through.")
REPORT = ("This period, 3 of 6 active schemes are profitable, for a portfolio health score of 69/100. "
          "The standout is Growth Booster - OPC RJ, returning about Rs 15 for every Rs 1 spent — scale it. "
          "The most urgent leak is Rs 54,348 across over-claims and money-losing schemes, recoverable before "
          "the next payout. Putty schemes also stack to ~12% effective discount vs a ~5% headline. "
          "Recommended action: recover the over-claims, cap per-invoice discounts, and redesign Monsoon Growth - OPC UP.")
CLAIM = {"mode": "llm", "verdict": "OVER-CLAIM",
         "note": ("Murthy, Khare and Lanka claimed Rs 8,400 against scheme SCHPHA008 but earned only Rs 5,250 "
                  "— Rs 3,150 over entitlement. → Do this: hold this claim and recover the gap before payout."),
         "extracted": {"partner_name": "Murthy, Khare and Lanka", "scheme_id": "SCHPHA008", "claimed_amount": 8400}}

def J(obj): return json.dumps(obj).encode()

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, body, ctype="application/json"):
        self.send_response(200); self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
    def do_GET(self):
        p = urlparse(self.path)
        if p.path in ("/", "/index.html"): return self._send(HTML, "text/html; charset=utf-8")
        if p.path == "/api/windows": return self._send(J(windows))
        if p.path == "/api/dashboard":
            win = parse_qs(p.query).get("win", ["ttm"])[0]
            win = "FY2024-25" if win == "FY2024-25" else "ttm"
            return self._send(J(dash[win]))
        if p.path == "/api/report":
            return self._send(J({"mode": "llm", "health": 69, "narrative": REPORT, "headline_at_risk": "Rs 54,348"}))
        return self._send(b"{}")
    def do_POST(self):
        ln = int(self.headers.get("Content-Length", 0) or 0)
        if ln: self.rfile.read(ln)
        p = urlparse(self.path)
        if p.path == "/api/claim-check": return self._send(J(CLAIM))
        if p.path == "/chat": return self._send(J({"session_id": "s", "answer": CHAT, "mode": "llm"}))
        return self._send(b"{}")

srv = ThreadingHTTPServer(("127.0.0.1", 8765), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
URL = "http://127.0.0.1:8765/"

def shot(pg, name): pg.screenshot(path=os.path.join(FR, name)); print("shot", name, flush=True)

with sync_playwright() as p:
    b = p.chromium.launch(args=["--no-sandbox","--disable-dev-shm-usage","--disable-gpu","--force-color-profile=srgb"])
    ctx = b.new_context(viewport={"width":1280,"height":720}, device_scale_factor=2)
    pg = ctx.new_page(); pg.set_default_timeout(15000)
    pg.goto(URL)
    pg.wait_for_function("document.getElementById('k-roi') && document.getElementById('k-roi').textContent.trim() !== '—'")
    pg.wait_for_timeout(1800)
    shot(pg, "f01_top.png")
    pg.evaluate("window.scrollTo(0,250)"); pg.wait_for_timeout(900); shot(pg, "f02_needs.png")
    pg.evaluate("window.scrollTo(0,460)"); pg.wait_for_timeout(900); shot(pg, "f03_needs2.png")
    pg.evaluate("window.scrollTo(0,820)"); pg.wait_for_timeout(1200); shot(pg, "f04_wins.png")
    pg.evaluate("window.scrollTo(0,0)"); pg.wait_for_timeout(700)
    pg.fill("#q", "Which scheme should I stop, and who is loading inventory?"); pg.wait_for_timeout(400)
    pg.click("#send"); pg.wait_for_timeout(1800); shot(pg, "f05_chat.png")
    pg.select_option("#winSel", "FY2024-25"); pg.wait_for_timeout(1600); shot(pg, "f06_fy.png")
    pg.evaluate("window.scrollTo(0,330)"); pg.wait_for_timeout(1000); shot(pg, "f07_fy_schemes.png")
    pg.evaluate("window.scrollTo(0,0)"); pg.select_option("#winSel", "ttm"); pg.wait_for_timeout(1400)
    pg.click("#reportBtn"); pg.wait_for_timeout(1800); shot(pg, "f08_report.png")
    pg.click("#mClose"); pg.wait_for_timeout(600)
    pg.set_input_files("#claimFile", os.path.join(BASE, "..", "..", "NovaCure_Sample_Claim_SCHPHA008.png"))
    pg.wait_for_timeout(2000); shot(pg, "f09_claim.png")
    pg.click("#mClose"); pg.wait_for_timeout(600)
    pg.evaluate("window.scrollTo(0,0)"); pg.wait_for_timeout(600); shot(pg, "f10_end.png")
    b.close()
print("ALL_FRAMES_DONE", flush=True)
