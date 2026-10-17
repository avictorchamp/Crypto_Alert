"""Browser-friendly landing page for the Crypto Alert API.

The API implementation remains in app.main; this module only adds a root page.
"""
from fastapi.responses import HTMLResponse
from app.main import app


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def home():
    return HTMLResponse(
        content="""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Crypto Alert</title>
  <style>
    :root { color-scheme: dark; --bg:#0b1220; --panel:#121d30; --text:#edf3ff; --muted:#9fb0ca; --line:#263650; --accent:#67e8b1; }
    * { box-sizing:border-box; }
    body { margin:0; font:16px/1.5 system-ui,-apple-system,Segoe UI,sans-serif; background:var(--bg); color:var(--text); }
    main { width:min(900px, calc(100% - 32px)); margin:48px auto; }
    header { padding:28px; border:1px solid var(--line); border-radius:20px; background:linear-gradient(135deg,#15243a,#101827); }
    h1 { margin:0 0 8px; font-size:clamp(28px,5vw,42px); }
    p { color:var(--muted); margin:8px 0; }
    .pill { display:inline-block; border:1px solid #246c55; color:var(--accent); border-radius:99px; padding:4px 10px; font-size:13px; }
    section { margin-top:22px; }
    h2 { font-size:18px; }
    .grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:12px; }
    a.card { display:block; padding:18px; border:1px solid var(--line); border-radius:14px; background:var(--panel); color:var(--text); text-decoration:none; }
    a.card:hover { border-color:var(--accent); transform:translateY(-1px); }
    a.card strong { display:block; margin-bottom:5px; }
    code { color:var(--accent); }
    footer { margin-top:28px; font-size:13px; color:var(--muted); }
  </style>
</head>
<body>
<main>
  <header>
    <span class="pill">API SERVICE ONLINE</span>
    <h1>Crypto Alert</h1>
    <p>Market monitoring and Telegram alerts. Trading execution is disabled; signals are for manual review only.</p>
    <p>Open a service endpoint below to inspect live status and market-monitoring data.</p>
  </header>
  <section>
    <h2>System</h2>
    <div class="grid">
      <a class="card" href="/health"><strong>Health</strong><span>Service health, scheduler and configured thresholds</span></a>
      <a class="card" href="/status"><strong>Status</strong><span>Latest scan timestamps and runtime status</span></a>
      <a class="card" href="/docs"><strong>API Documentation</strong><span>Interactive API endpoint reference</span></a>
      <a class="card" href="/openapi.json"><strong>OpenAPI JSON</strong><span>Machine-readable API specification</span></a>
    </div>
  </section>
  <section>
    <h2>Market monitoring</h2>
    <div class="grid">
      <a class="card" href="/watchlist"><strong>Watchlist</strong><span>Tracked coins and watchlist memory</span></a>
      <a class="card" href="/portfolio"><strong>Portfolio</strong><span>Read-only portfolio data</span></a>
      <a class="card" href="/positions"><strong>Positions</strong><span>Read-only position data</span></a>
      <a class="card" href="/scan"><strong>Run scan</strong><span>Manually run a full scan; may take several seconds</span></a>
    </div>
  </section>
  <footer>Crypto Alert · Signals are informational only. No automatic trading is performed.</footer>
</main>
</body>
</html>""",
        status_code=200,
    )
