"""
Web‑based room swap application using only Python's standard library.

Now includes a startup configuration step (CLI wizard or command‑line args)
so the person running the script can set:
  • Total rent
  • Number of participants
  • Participant names

No third‑party packages required. After configuration, the HTTP server starts.

**Quick start (interactive wizard):**
    python roomswap.py

**Command‑line usage:**
    python roomswap.py --total 3606 --names "Karim,Hassan,Benjamin,Hassaan"

Optional:
    python roomswap.py --total 5000 --num 3  # will prompt for 3 names

Then open http://localhost:8000 in a browser.
"""
from __future__ import annotations

import html
import http.cookies
import http.server
import random
import urllib.parse
import subprocess
import threading
import re
import argparse
from http import HTTPStatus
from typing import Dict, List, Optional

# ---------------------------------------------------------------------
# Global data/state
# ---------------------------------------------------------------------
PEOPLE: List[str] = []                     # will be populated at startup
ROOMS: List[str] = []                      # room names
ASSIGNMENT: Dict[str, str] = {}            # maps person -> room
PRICES: Dict[str, float] = {}              # maps room -> price
STATES: Dict[str, Optional[str]] = {}      # maps person -> 'satisfied'/'unsatisfied'/None
AVAILABLE_NAMES: set[str] = set()          # names not yet claimed in UI
PENDING_SWAPS: List[Dict[str, object]] = []
TOTAL_RENT: float = 0.0

# ---------------------------------------------------------------------
# Initialization / configuration helpers
# ---------------------------------------------------------------------

def init_allocation(total_rent: float) -> None:
    """Randomly assign rooms and initialise uniform prices for the current PEOPLE list."""
    global ROOMS, ASSIGNMENT, PRICES, AVAILABLE_NAMES, STATES, PENDING_SWAPS, TOTAL_RENT
    if not PEOPLE:
        raise RuntimeError("PEOPLE is empty. Configure participants before init_allocation().")

    TOTAL_RENT = float(total_rent)
    n = len(PEOPLE)
    ROOMS = [f"unit_{i+1}" for i in range(n)]
    random.shuffle(ROOMS)
    ASSIGNMENT = {person: ROOMS[i] for i, person in enumerate(PEOPLE)}
    base_price = round(TOTAL_RENT / n, 2)
    PRICES = {room: base_price for room in ROOMS}
    # Fix any rounding discrepancy to keep the sum equal to TOTAL_RENT
    discrepancy = round(TOTAL_RENT - sum(PRICES.values()), 2)
    if abs(discrepancy) > 1e-9:
        PRICES[ROOMS[-1]] = round(PRICES[ROOMS[-1]] + discrepancy, 2)

    AVAILABLE_NAMES = set(PEOPLE)
    STATES = {p: None for p in PEOPLE}
    PENDING_SWAPS = []


# ---------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------

def html_page(title: str, body: str) -> str:
    return f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{html.escape(title)}</title>
    <style>
        :root {{
            --bg: #0f172a;        /* slate-900 */
            --panel: #111827;     /* gray-900 */
            --muted: #9ca3af;     /* gray-400 */
            --text: #e5e7eb;      /* gray-200 */
            --accent: #22c55e;    /* green-500 */
            --accent2: #3b82f6;   /* blue-500 */
            --danger: #ef4444;    /* red-500 */
            --border: #1f2937;    /* gray-800 */
        }}
        * {{ box-sizing: border-box; }}
        body {{ margin:0; background: var(--bg); color: var(--text); font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial; }}
        header {{ padding: 16px 24px; border-bottom: 1px solid var(--border); background: linear-gradient(180deg, #0b1220, #0f172a); position: sticky; top: 0; }}
        h1 {{ margin: 0; font-size: 24px; letter-spacing: .5px; }}
        main {{ max-width: 1000px; margin: 24px auto; padding: 0 16px 48px; }}
        .card {{ background: var(--panel); border: 1px solid var(--border); border-radius: 16px; padding: 16px; margin-bottom: 16px; box-shadow: 0 10px 30px rgba(0,0,0,0.25); }}
        table {{ border-collapse: collapse; width: 100%; margin-top: 8px; }}
        th, td {{ border-bottom: 1px solid var(--border); padding: 10px 8px; text-align: left; }}
        th {{ color: var(--muted); font-weight: 600; text-transform: uppercase; font-size: 12px; letter-spacing: .08em; }}
        .row {{ display: flex; gap: 12px; flex-wrap: wrap; }}
        .row > * {{ flex: 1 1 240px; }}
        input, select {{ width: 100%; padding: 10px 12px; background: #0b1220; color: var(--text); border: 1px solid var(--border); border-radius: 10px; }}
        input[type=number] {{ appearance: textfield; }}
        button {{ cursor: pointer; padding: 10px 14px; border-radius: 10px; border: 1px solid var(--border); color: var(--text); background: #0b1220; transition: transform .02s ease; }}
        button:hover {{ transform: translateY(-1px); }}
        .btn-primary {{ background: var(--accent2); border-color: #1d4ed8; }}
        .btn-accept {{ background: var(--accent); border-color: #16a34a; }}
        .btn-decline {{ background: var(--danger); border-color: #b91c1c; }}
        .badge {{ display:inline-block; padding: 4px 8px; border-radius: 999px; font-size: 12px; }}
        .satisfied {{ background: rgba(34,197,94,.15); color: #86efac; }}
        .unsatisfied {{ background: rgba(239,68,68,.15); color: #fca5a5; }}
        .undecided {{ background: rgba(148,163,184,.15); color: #cbd5e1; }}
        .muted {{ color: var(--muted); }}
        .grid-2 {{ display:grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
        @media (max-width: 720px) {{ .grid-2 {{ grid-template-columns: 1fr; }} }}
    </style>
</head>
<body>
    <header><h1>{html.escape(title)}</h1></header>
    <main>{body}</main>
</body>
</html>
"""


# ---------------------------------------------------------------------
# HTTP Handler
# ---------------------------------------------------------------------
class RoomSwapHandler(http.server.BaseHTTPRequestHandler):
    """HTTP request handler for the room swap application."""

    # -------- Cookie helpers --------
    def _get_username(self) -> Optional[str]:
        cookie_header = self.headers.get('Cookie')
        if not cookie_header:
            return None
        cookies = http.cookies.SimpleCookie()
        cookies.load(cookie_header)
        if 'username' in cookies:
            return cookies['username'].value
        return None

    def _set_cookie(self, username: str) -> None:
        cookie = http.cookies.SimpleCookie()
        cookie['username'] = username
        cookie['username']['path'] = '/'
        self.send_header('Set-Cookie', cookie.output(header='', sep=''))

    # -------- Routing --------
    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        if path == '/choose':
            username = query.get('user', [None])[0]
            if username and username in AVAILABLE_NAMES:
                AVAILABLE_NAMES.remove(username)
                self.send_response(HTTPStatus.SEE_OTHER)
                self._set_cookie(username)
                self.send_header('Location', '/')
                self.end_headers()
                return
            body = '<p>Invalid or unavailable user name.</p><p><a href="/">Return</a></p>'
            self._send_html('Error', body)
            return

        # Default
        self._render_index()

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        length = int(self.headers.get('Content-Length', 0))
        body_data = self.rfile.read(length).decode('utf-8')
        post = urllib.parse.parse_qs(body_data)

        username = self._get_username()
        if not username or username not in PEOPLE:
            self.send_response(HTTPStatus.FORBIDDEN)
            self._send_html('Forbidden', '<p>Please choose your identity first.</p>')
            return

        if path == '/set_state':
            state = post.get('state', [None])[0]
            if state in {'satisfied', 'unsatisfied'}:
                STATES[username] = state
            self.send_response(HTTPStatus.SEE_OTHER)
            self.send_header('Location', '/')
            self.end_headers()
            return

        if path == '/propose_swap':
            target = post.get('target', [None])[0]
            price_str = post.get('price', [None])[0]
            if (target is None or price_str is None or target not in PEOPLE or target == username):
                self.send_response(HTTPStatus.BAD_REQUEST)
                self._send_html('Error', '<p>Invalid swap request.</p>')
                return
            try:
                if price_str.strip() == '' or float(price_str) == 0:
                    offered_price = PRICES[ASSIGNMENT[target]]
                else:
                    offered_price = float(price_str)
                if offered_price < 0:
                    raise ValueError
            except (ValueError, KeyError):
                self.send_response(HTTPStatus.BAD_REQUEST)
                self._send_html('Error', '<p>Invalid price value.</p>')
                return
            PENDING_SWAPS.append({'proposer': username,'target': target,'offered_price': offered_price})
            self.send_response(HTTPStatus.SEE_OTHER)
            self.send_header('Location', '/')
            self.end_headers()
            return

        if path == '/respond_swap':
            action = post.get('action', [None])[0]
            proposer = post.get('proposer', [None])[0]
            # locate matching proposal
            idx = None
            for i, req in enumerate(PENDING_SWAPS):
                if req['proposer'] == proposer and req['target'] == username:
                    idx = i
                    break
            if idx is None:
                self.send_response(HTTPStatus.BAD_REQUEST)
                self._send_html('Error', '<p>No such pending request.</p>')
                return
            req = PENDING_SWAPS.pop(idx)
            offered_price = float(req['offered_price'])

            # snapshot
            old_assignment = ASSIGNMENT.copy()
            proposer_room = old_assignment[proposer]
            target_room = old_assignment[username]
            price_proposer_room = PRICES[proposer_room]
            price_target_room = PRICES[target_room]

            if action == 'accept':
                new_price_proposer_old_room = price_proposer_room + price_target_room - offered_price
                ASSIGNMENT[proposer], ASSIGNMENT[username] = target_room, proposer_room
                PRICES[target_room] = round(offered_price, 2)
                PRICES[proposer_room] = round(new_price_proposer_old_room, 2)

                rooms_involved = {proposer_room, target_room}
                def involves_rooms(r):
                    pr = old_assignment.get(r['proposer'])
                    tr = old_assignment.get(r['target'])
                    return (pr in rooms_involved) or (tr in rooms_involved)
                PENDING_SWAPS[:] = [r for r in PENDING_SWAPS if not involves_rooms(r)]
            else:
                total_pair = price_proposer_room + price_target_room
                PRICES[target_room] = round(offered_price, 2)
                PRICES[proposer_room] = round(total_pair - offered_price, 2)

            self.send_response(HTTPStatus.SEE_OTHER)
            self.send_header('Location', '/')
            self.end_headers()
            return

        self.send_response(HTTPStatus.NOT_FOUND)
        self._send_html('Not Found', '<p>Unknown action.</p>')

    # -------- Page renderers --------
    def _send_html(self, title: str, body: str) -> None:
        page = html_page(title, body)
        self.send_header('Content-type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(page.encode('utf-8'))

    def _render_index(self) -> None:
        username = self._get_username()
        if username is None or username not in PEOPLE:
            # login/identity claim page
            options = ''.join(
                f'<option value="{html.escape(name)}">{html.escape(name)}</option>'
                for name in sorted(AVAILABLE_NAMES)
            ) or '<option disabled>(no names available)</option>'
            chooser = (
                '<div class="card">'
                f'<p class="muted">Total rent: <strong>{TOTAL_RENT:.2f}</strong> • Participants: <strong>{len(PEOPLE)}</strong></p>'
                '<form method="get" action="/choose" class="row">'
                f'<select name="user">{options}</select>'
                '<button class="btn-primary" type="submit">Join session</button>'
                '</form>'
                '</div>'
            )
            body = chooser
            self.send_response(HTTPStatus.OK)
            self._send_html('Choose your identity', body)
            return

        # Dashboard for logged-in user
        # roster table
        rows = ''
        for person in PEOPLE:
            room = ASSIGNMENT[person]
            price = PRICES[room]
            state = STATES.get(person) or 'undecided'
            badge_class = 'satisfied' if state == 'satisfied' else 'unsatisfied' if state == 'unsatisfied' else 'undecided'
            rows += (
                '<tr>'
                f'<td>{html.escape(person)}</td>'
                f'<td>{html.escape(room)}</td>'
                f'<td>{price:.2f}</td>'
                f'<td><span class="badge {badge_class}">{html.escape(state)}</span></td>'
                '</tr>'
            )
        table = (
            '<div class="card">'
            f'<p class="muted">Total rent: <strong>{TOTAL_RENT:.2f}</strong> • Participants: <strong>{len(PEOPLE)}</strong></p>'
            '<table>'
            '<thead><tr><th>Person</th><th>Room</th><th>Price</th><th>Status</th></tr></thead>'
            f'<tbody>{rows}</tbody>'
            '</table>'
            '</div>'
        )

        state_form = (
            '<div class="card">'
            '<h3>Update your satisfaction</h3>'
            '<form method="post" action="/set_state" class="row">'
            '<select name="state">'
            '<option value="satisfied">satisfied</option>'
            '<option value="unsatisfied">unsatisfied</option>'
            '</select>'
            '<button class="btn-primary" type="submit">Save</button>'
            '</form>'
            '</div>'
        )

        # swap form
        other_people_options = ''.join(
            f'<option value="{html.escape(p)}">{html.escape(p)}</option>' for p in PEOPLE if p != username
        ) or '<option disabled>(no one available)</option>'
        swap_form = (
            '<div class="card">'
            '<h3>Propose a room swap</h3>'
            '<form method="post" action="/propose_swap">'
            '<div class="grid-2">'
            f'<div><label class="muted">Target user</label><select name="target">{other_people_options}</select></div>'
            '<div><label class="muted">Offer price</label><input type="number" name="price" step="0.01" min="0" placeholder="0 = target\'s current" required></div>'
            '</div>'
            '<div style="margin-top:12px"><button class="btn-primary" type="submit">Send offer</button></div>'
            '</form>'
            '</div>'
        )

        # Pending offers for this user
        pending_html = ''
        user_requests = [req for req in PENDING_SWAPS if req['target'] == username]
        if user_requests:
            pending_html += '<div class="card"><h3>Pending offers for you</h3>'
            for req in user_requests:
                proposer = req['proposer']
                price = req['offered_price']
                pending_html += (
                    '<div style="display:flex; align-items:center; justify-content:space-between; gap:8px; padding:8px 0; border-bottom:1px solid var(--border)">'
                    f'<div><strong>{html.escape(proposer)}</strong> offers <strong>{price:.2f}</strong> for your room.</div>'
                    '<form method="post" action="/respond_swap" style="display:flex; gap:8px;">'
                    f'<input type="hidden" name="proposer" value="{html.escape(proposer)}">'
                    f'<input type="hidden" name="price" value="{price}">'
                    '<button name="action" value="accept" class="btn-accept" type="submit">Accept</button>'
                    '<button name="action" value="decline" class="btn-decline" type="submit">Decline</button>'
                    '</form>'
                    '</div>'
                )
            pending_html += '</div>'

        # Global order book
        pending_table = ''
        if PENDING_SWAPS:
            rows_pending = ''
            for req in PENDING_SWAPS:
                proposer = req['proposer']
                target_user = req['target']
                offered_price = req['offered_price']
                proposer_unit = ASSIGNMENT.get(proposer, '')
                target_unit = ASSIGNMENT.get(target_user, '')
                rows_pending += (
                    '<tr>'
                    f'<td>{html.escape(proposer)}</td>'
                    f'<td>{html.escape(proposer_unit)}</td>'
                    f'<td>{html.escape(target_user)}</td>'
                    f'<td>{html.escape(target_unit)}</td>'
                    f'<td>{offered_price:.2f}</td>'
                    '</tr>'
                )
            pending_table = (
                '<div class="card">'
                '<h3>Pending offers (order book)</h3>'
                '<table>'
                '<thead><tr><th>Proposer</th><th>Proposer Unit</th><th>Target</th><th>Target Unit</th><th>Offered Price</th></tr></thead>'
                f'<tbody>{rows_pending}</tbody>'
                '</table>'
                '</div>'
            )

        body = table + state_form + swap_form + pending_html + pending_table
        self.send_response(HTTPStatus.OK)
        self._send_html('Room Swap Dashboard', body)


# ---------------------------------------------------------------------
# Server bootstrap with configuration (CLI args or interactive wizard)
# ---------------------------------------------------------------------

def _start_localtunnel(port: int) -> None:
    """Try to expose the local server via localtunnel (best-effort)."""
    try:
        proc = subprocess.Popen(
            ['npx', 'localtunnel', '--port', str(port)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        for line in proc.stdout or []:
            m = re.search(r'https?://\S+', line)
            if m:
                url = m.group(0)
                print(f"\nLocaltunnel URL: {url}\n")
                break
    except Exception as e:
        print(f"Could not start localtunnel: {e}")


def run(host: str = '0.0.0.0', port: int = 8000) -> None:
    server = http.server.HTTPServer((host, port), RoomSwapHandler)
    print(f"Starting room swap server at http://{host}:{port} ...")
    try:
        threading.Thread(target=_start_localtunnel, args=(port,), daemon=True).start()
    except Exception:
        pass
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped by user.")
        server.server_close()


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description='Room swap server (configurable).')
    p.add_argument('--total', type=float, help='Total rent (e.g., 3606)')
    p.add_argument('--names', type=str, help='Comma-separated participant names (e.g., "A,B,C")')
    p.add_argument('--num', type=int, help='Number of participants (use with interactive name prompts)')
    p.add_argument('--host', type=str, default='0.0.0.0', help='Host to bind (default 0.0.0.0)')
    p.add_argument('--port', type=int, default=8000, help='Port to bind (default 8000)')
    return p.parse_args()


def _interactive_wizard(ns: argparse.Namespace) -> tuple[float, List[str]]:
    # total rent
    total = ns.total
    while total is None:
        try:
            raw = input('Enter total rent (e.g., 3606): ').strip()
            if not raw:
                continue
            total = float(raw)
            if total <= 0:
                print('Total must be positive.'); total = None
        except ValueError:
            print('Please enter a valid number.')

    # names
    names: List[str] = []
    if ns.names:
        names = [n.strip() for n in ns.names.split(',') if n.strip()]
    elif ns.num:
        for i in range(ns.num):
            while True:
                nm = input(f'Name #{i+1}: ').strip()
                if nm:
                    names.append(nm)
                    break
    else:
        # prompt free-form, comma-separated
        raw = ''
        while not names:
            raw = input('Enter names (comma-separated): ').strip()
            names = [n.strip() for n in raw.split(',') if n.strip()]
            if len(names) < 2:
                print('Please enter at least two names.')
                names = []

    # final sanity
    dedup = []
    seen = set()
    for n in names:
        if n.lower() not in seen:
            dedup.append(n)
            seen.add(n.lower())
    if len(dedup) != len(names):
        print('Note: duplicate names were removed.')
    if total <= 0 or len(dedup) < 2:
        raise SystemExit('Invalid configuration.')
    return total, dedup


def main() -> None:
    global PEOPLE
    ns = _parse_args()
    total, names = _interactive_wizard(ns)

    PEOPLE = names
    init_allocation(total)

    print('\nConfiguration complete:')
    print(f'  Total rent: {TOTAL_RENT:.2f}')
    print(f'  Participants ({len(PEOPLE)}): {", ".join(PEOPLE)}')
    print('\nOpen http://localhost:%d in your browser.' % ns.port)

    run(ns.host, ns.port)


if __name__ == '__main__':
    main()
