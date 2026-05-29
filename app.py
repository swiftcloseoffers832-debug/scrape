"""
BatchLeads Bot — Flask control panel
Run:  python app.py
Then open http://localhost:5000 in your browser.
"""

import asyncio
import io
import threading
import logging
from flask import Flask, jsonify, redirect, render_template_string, request, Response

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

from scraper import ScraperSession

app = Flask(__name__)
session = ScraperSession()

# Run asyncio event loop in background thread
_loop = asyncio.new_event_loop()

def _start_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_forever()

_bg_thread = threading.Thread(target=_start_loop, args=(_loop,), daemon=True)
_bg_thread.start()


def _run_coro(coro):
    future = asyncio.run_coroutine_threadsafe(coro, _loop)
    return future.result(timeout=10)


HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>BatchLeads Bot</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: system-ui, sans-serif; background: #0f172a; color: #e2e8f0; min-height: 100vh; display: flex; flex-direction: column; align-items: center; padding: 2rem 1rem; }
  h1 { font-size: 1.8rem; font-weight: 700; margin-bottom: .25rem; color: #38bdf8; }
  .sub { color: #94a3b8; font-size: .9rem; margin-bottom: 2rem; }
  .card { background: #1e293b; border-radius: 1rem; padding: 2rem; width: 100%; max-width: 640px; margin-bottom: 1.5rem; }
  .stat-row { display: flex; gap: 1.5rem; margin-bottom: 1.5rem; }
  .stat { flex: 1; background: #0f172a; border-radius: .75rem; padding: 1rem; text-align: center; }
  .stat-val { font-size: 2rem; font-weight: 700; color: #38bdf8; }
  .stat-label { font-size: .75rem; color: #64748b; text-transform: uppercase; letter-spacing: .05em; }
  .state-badge { display: inline-block; padding: .25rem .75rem; border-radius: 9999px; font-size: .8rem; font-weight: 600; text-transform: uppercase; letter-spacing: .05em; }
  .state-idle    { background: #334155; color: #94a3b8; }
  .state-waiting_login { background: #713f12; color: #fde68a; }
  .state-running { background: #14532d; color: #86efac; }
  .state-paused  { background: #713f12; color: #fde68a; }
  .state-done    { background: #1e3a5f; color: #93c5fd; }
  .state-error   { background: #7f1d1d; color: #fca5a5; }
  .msg { color: #94a3b8; font-size: .9rem; margin-top: .75rem; min-height: 1.2em; }
  .btn-row { display: flex; gap: .75rem; flex-wrap: wrap; margin-top: 1.5rem; }
  button { padding: .65rem 1.5rem; border: none; border-radius: .5rem; font-size: .95rem; font-weight: 600; cursor: pointer; transition: opacity .15s; }
  button:disabled { opacity: .35; cursor: not-allowed; }
  .btn-start  { background: #16a34a; color: #fff; }
  .btn-pause  { background: #d97706; color: #fff; }
  .btn-resume { background: #0284c7; color: #fff; }
  .btn-stop   { background: #dc2626; color: #fff; }
  .btn-dl     { background: #7c3aed; color: #fff; }
  input[type=number] { background: #0f172a; border: 1px solid #334155; border-radius: .5rem; color: #e2e8f0; padding: .5rem .75rem; width: 80px; font-size: .95rem; }
  label { font-size: .85rem; color: #94a3b8; margin-right: .5rem; }
  .settings { display: flex; align-items: center; margin-bottom: 1rem; }
  .log-box { background: #0f172a; border-radius: .5rem; padding: 1rem; font-size: .8rem; color: #64748b; font-family: monospace; max-height: 160px; overflow-y: auto; margin-top: 1rem; }
</style>
</head>
<body>
<h1>🏠 BatchLeads Bot</h1>
<p class="sub">Automated comparables scraper — one button to run</p>

<div class="card">
  <div class="stat-row">
    <div class="stat">
      <div class="stat-val" id="props">0</div>
      <div class="stat-label">Properties</div>
    </div>
    <div class="stat">
      <div class="stat-val" id="comps">0</div>
      <div class="stat-label">Comp Rows</div>
    </div>
    <div class="stat">
      <div class="stat-val" id="state-badge-wrap"><span class="state-badge state-idle" id="state-text">idle</span></div>
      <div class="stat-label">Status</div>
    </div>
  </div>

  <div class="msg" id="msg">Click START to launch the browser.</div>

  <div class="settings" style="margin-top:1.25rem">
    <label for="batch">Batch size</label>
    <input type="number" id="batch" value="15" min="5" max="30">
  </div>

  <div class="btn-row">
    <button class="btn-start"  id="btn-start"  onclick="doStart()">▶ START</button>
    <button class="btn-pause"  id="btn-pause"  onclick="doPause()"  disabled>⏸ PAUSE</button>
    <button class="btn-resume" id="btn-resume" onclick="doResume()" disabled>▶ RESUME</button>
    <button class="btn-stop"   id="btn-stop"   onclick="doStop()"   disabled>■ STOP</button>
    <button class="btn-dl"     id="btn-dl"     onclick="doDownload()" disabled>⬇ DOWNLOAD CSV</button>
  </div>

  <div class="log-box" id="logbox">Waiting…</div>
</div>

<script>
let lastMsg = '';
let logLines = [];

function updateUI(s) {
  document.getElementById('props').textContent = s.properties;
  document.getElementById('comps').textContent = s.comps;
  const txt = document.getElementById('state-text');
  txt.textContent = s.state;
  txt.className = 'state-badge state-' + s.state;

  if (s.message !== lastMsg) {
    lastMsg = s.message;
    logLines.unshift(new Date().toLocaleTimeString() + ' — ' + s.message);
    if (logLines.length > 30) logLines.pop();
    document.getElementById('logbox').textContent = logLines.join('\\n');
  }
  document.getElementById('msg').textContent = s.message;

  const running = s.state === 'running';
  const paused  = s.state === 'paused';
  const idle    = s.state === 'idle';
  const done    = s.state === 'done' || s.state === 'error';

  document.getElementById('btn-start').disabled  = !idle && !done;
  document.getElementById('btn-pause').disabled  = !running;
  document.getElementById('btn-resume').disabled = !paused;
  document.getElementById('btn-stop').disabled   = idle || done;
  document.getElementById('btn-dl').disabled     = s.comps === 0;
}

async function poll() {
  try {
    const r = await fetch('/api/status');
    const s = await r.json();
    updateUI(s);
  } catch(_) {}
  setTimeout(poll, 2000);
}

async function doStart() {
  const batch = document.getElementById('batch').value;
  await fetch('/api/start', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({batch_size: parseInt(batch)})});
}
async function doPause()  { await fetch('/api/pause',  {method:'POST'}); }
async function doResume() { await fetch('/api/resume', {method:'POST'}); }
async function doStop()   { await fetch('/api/stop',   {method:'POST'}); }
function doDownload() { window.location.href = '/api/download'; }

poll();
</script>
</body>
</html>
"""


@app.route("/")
def index():
    return render_template_string(HTML)


@app.route("/api/status")
def api_status():
    return jsonify(session.status)


@app.route("/api/start", methods=["POST"])
def api_start():
    data = request.get_json(silent=True) or {}
    batch_size = int(data.get("batch_size", 15))

    async def _start():
        await session._launch_browser()
        await session._wait_for_login()
        await session._inject_helpers()
        await session._click_first_comparables_tab()
        await session._scrape_loop(batch_size)
        await session._save_csv()
        session._set(state="done", message="Scraping complete")

    asyncio.run_coroutine_threadsafe(_start(), _loop)
    session._set(state="waiting_login", message="Launching browser…")
    return jsonify({"ok": True})


@app.route("/api/pause", methods=["POST"])
def api_pause():
    session.pause()
    return jsonify({"ok": True})


@app.route("/api/resume", methods=["POST"])
def api_resume():
    session.resume()
    return jsonify({"ok": True})


@app.route("/api/stop", methods=["POST"])
def api_stop():
    session.stop()
    return jsonify({"ok": True})


@app.route("/api/download")
def api_download():
    csv_content = session.get_csv()
    if not csv_content:
        return "No data yet", 404
    return Response(
        csv_content,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=comparables.csv"},
    )


if __name__ == "__main__":
    print("\n  BatchLeads Bot control panel → http://localhost:5000\n")
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)
