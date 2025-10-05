"""
Web‑based room swap application using only Python's standard library.

This module implements a lightweight HTTP server that serves a simple
web interface for housemates to select their identity, indicate
satisfaction with their current room assignment, and negotiate room
swaps with each other.  It uses Python's built‑in ``http.server``
framework and does not depend on any external packages.  Because it
relies on cookies to track who is currently interacting with the
application, the same browser must be used throughout a session.

**Usage:** run this file with Python 3 and open
``http://localhost:8000`` in a web browser.  Each housemate can then
select their name (which becomes unavailable to others) and set their
state to *satisfied* or *unsatisfied*.  They can also propose room
swaps by offering a new price to the current occupant of another room.
Pending swap proposals are visible to the targeted user, who can
accept or decline them.  A successful swap updates the room
assignment and adjusts prices while keeping the total rent constant【89576418126231†L23-L27】.

Note that this example is intended for demonstration purposes and
lacks robust error handling, persistent storage, or authentication.
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
from http import HTTPStatus
from typing import Dict, List, Optional


# Global data structures.  These will be shared across all requests.

PEOPLE: List[str] = ["Karim", "Hassan", "Benjamin", "Hassaan"]
# Initial room names and prices; will be set in ``init_allocation``.
ROOMS: List[str] = []
ASSIGNMENT: Dict[str, str] = {}  # maps person to room
PRICES: Dict[str, float] = {}  # maps room to price
STATES: Dict[str, Optional[str]] = {p: None for p in PEOPLE}  # 'satisfied' or 'unsatisfied'
AVAILABLE_NAMES: set[str] = set(PEOPLE)
PENDING_SWAPS: List[Dict[str, object]] = []  # list of swap requests


def init_allocation(total_rent: float = 4000.0) -> None:
    """Randomly assign rooms and initialise uniform prices.

    This function populates ``ROOMS``, ``ASSIGNMENT`` and ``PRICES``
    with a fresh random allocation.  It should be called once at
    import time.
    """
    global ROOMS, ASSIGNMENT, PRICES, AVAILABLE_NAMES, STATES, PENDING_SWAPS
    n = len(PEOPLE)
    ROOMS = [f"unit_{i+1}" for i in range(n)]
    random.shuffle(ROOMS)
    ASSIGNMENT = {person: ROOMS[i] for i, person in enumerate(PEOPLE)}
    base_price = round(total_rent / n, 2)
    PRICES = {room: base_price for room in ROOMS}
    # Adjust for rounding discrepancy
    discrepancy = round(total_rent - sum(PRICES.values()), 2)
    if abs(discrepancy) > 1e-9:
        PRICES[ROOMS[-1]] += discrepancy
    # Reset states and availability
    AVAILABLE_NAMES = set(PEOPLE)
    STATES = {p: None for p in PEOPLE}
    PENDING_SWAPS = []


def html_page(title: str, body: str) -> str:
    """Return a complete HTML page given a title and body content."""
    return f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>{html.escape(title)}</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 2em; }}
        table {{ border-collapse: collapse; width: 100%; margin-bottom: 1em; }}
        th, td {{ border: 1px solid #ccc; padding: 8px; text-align: left; }}
        th {{ background-color: #f8f8f8; }}
        .satisfied {{ color: green; }}
        .unsatisfied {{ color: red; }}
        .button {{ padding: 6px 12px; margin: 4px; }}
    </style>
</head>
<body>
    <h1>{html.escape(title)}</h1>
    {body}
</body>
</html>
"""


class RoomSwapHandler(http.server.BaseHTTPRequestHandler):
    """HTTP request handler for the room swap application."""

    def _get_username(self) -> Optional[str]:
        """Retrieve the username from the request cookies, if present."""
        cookie_header = self.headers.get('Cookie')
        if not cookie_header:
            return None
        cookies = http.cookies.SimpleCookie()
        cookies.load(cookie_header)
        if 'username' in cookies:
            return cookies['username'].value
        return None

    def _set_cookie(self, username: str) -> None:
        """Send a Set-Cookie header to store the username."""
        cookie = http.cookies.SimpleCookie()
        cookie['username'] = username
        # Cookie is session-only (expires when browser closes)
        cookie['username']['path'] = '/'
        self.send_header('Set-Cookie', cookie.output(header='', sep=''))

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)
        if path == '/choose':
            # Handle identity selection
            username = query.get('user', [None])[0]
            if username and username in AVAILABLE_NAMES:
                AVAILABLE_NAMES.remove(username)
                self.send_response(HTTPStatus.SEE_OTHER)
                self._set_cookie(username)
                self.send_header('Location', '/')
                self.end_headers()
                return
            # Username unavailable or not provided
            body = '<p>Invalid or unavailable user name.</p>'
            body += '<p><a href="/">Return to home</a></p>'
            self._send_html('Error', body)
            return
        # Default: render index
        self._render_index()

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        length = int(self.headers.get('Content-Length', 0))
        body_data = self.rfile.read(length).decode('utf-8')
        post = urllib.parse.parse_qs(body_data)
        username = self._get_username()
        if not username or username not in PEOPLE:
            # Unauthenticated users cannot perform actions
            self.send_response(HTTPStatus.FORBIDDEN)
            self._send_html('Forbidden', '<p>Please choose your identity first.</p>')
            return
        if path == '/set_state':
            # Update satisfaction state
            state = post.get('state', [None])[0]
            if state in {'satisfied', 'unsatisfied'}:
                STATES[username] = state
            self.send_response(HTTPStatus.SEE_OTHER)
            self.send_header('Location', '/')
            self.end_headers()
            return
        if path == '/propose_swap':
            # Propose a swap. If the offered price is zero or blank,
            # default to the current price of the target's room. This
            # allows users to quickly offer the existing price instead
            # of manually entering 0.
            target = post.get('target', [None])[0]
            price_str = post.get('price', [None])[0]
            if (target is None or price_str is None or
                    target not in PEOPLE or target == username):
                self.send_response(HTTPStatus.BAD_REQUEST)
                self._send_html('Error', '<p>Invalid swap request.</p>')
                return
            # Determine the offered price. If the user enters "0" (or leaves
            # it blank), use the current price of the target room as
            # the starting offer. Otherwise parse the float.
            try:
                # Interpret empty or zero as defaulting to current price
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
            # Record the proposal
            PENDING_SWAPS.append({
                'proposer': username,
                'target': target,
                'offered_price': offered_price,
            })
            self.send_response(HTTPStatus.SEE_OTHER)
            self.send_header('Location', '/')
            self.end_headers()
            return
        if path == '/respond_swap':
            # Respond to a pending swap
            action = post.get('action', [None])[0]
            proposer = post.get('proposer', [None])[0]
            price_str = post.get('price', [None])[0]

            # Find the matching pending swap
            request_idx = None
            for idx, req in enumerate(PENDING_SWAPS):
                if req['proposer'] == proposer and req['target'] == username:
                    request_idx = idx
                    break
            if request_idx is None:
                self.send_response(HTTPStatus.BAD_REQUEST)
                self._send_html('Error', '<p>No such pending request.</p>')
                return

            # Pop the accepted/declined request
            req = PENDING_SWAPS.pop(request_idx)
            offered_price = float(req['offered_price'])

            # Snapshot assignments BEFORE any change so we can identify rooms I & J
            old_assignment = ASSIGNMENT.copy()

            proposer_room = old_assignment[proposer]
            target_room = old_assignment[username]
            price_proposer_room = PRICES[proposer_room]
            price_target_room = PRICES[target_room]

            if action == 'accept':
                # Perform the swap and set prices (sum preserved)
                new_price_proposer_old_room = price_proposer_room + price_target_room - offered_price
                ASSIGNMENT[proposer], ASSIGNMENT[username] = target_room, proposer_room
                PRICES[target_room] = round(offered_price, 2)
                PRICES[proposer_room] = round(new_price_proposer_old_room, 2)

                # ---- NEW: clean up all other pending offers that involve either room I or J
                rooms_involved = {proposer_room, target_room}

                def involves_rooms(r):
                    pr = old_assignment.get(r['proposer'])
                    tr = old_assignment.get(r['target'])
                    return (pr in rooms_involved) or (tr in rooms_involved)

                # mutate in place to keep the same list object
                PENDING_SWAPS[:] = [r for r in PENDING_SWAPS if not involves_rooms(r)]

            else:
                # DECLINE behavior (your binding-price rule):
                total_pair = price_proposer_room + price_target_room
                new_target_price = offered_price
                new_proposer_price = total_pair - offered_price
                PRICES[target_room] = round(new_target_price, 2)
                PRICES[proposer_room] = round(new_proposer_price, 2)

            self.send_response(HTTPStatus.SEE_OTHER)
            self.send_header('Location', '/')
            self.end_headers()
            return



        # Unknown POST target
        self.send_response(HTTPStatus.NOT_FOUND)
        self._send_html('Not Found', '<p>Unknown action.</p>')

    # Helper methods to build pages

    def _send_html(self, title: str, body: str) -> None:
        """Send an HTML page with the given title and body."""
        page = html_page(title, body)
        self.send_header('Content-type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(page.encode('utf-8'))

    def _render_index(self) -> None:
        """Render the main page based on whether the user is selected."""
        username = self._get_username()
        if username is None or username not in PEOPLE:
            # Show login page
            options = ''.join(
                f'<li><a href="/choose?user={html.escape(name)}">{html.escape(name)}</a></li>'
                for name in AVAILABLE_NAMES
            )
            if not options:
                options = '<li>No names available. Someone else may be using the app.</li>'
            body = '<p>Select your name to join the session:</p>'
            body += f'<ul>{options}</ul>'
            self.send_response(HTTPStatus.OK)
            self._send_html('Choose your identity', body)
            return
        # User page: show assignments, states and forms
        # Table of assignments and prices
        rows = ''
        for person in PEOPLE:
            room = ASSIGNMENT[person]
            price = PRICES[room]
            state = STATES.get(person) or 'undecided'
            state_class = 'satisfied' if state == 'satisfied' else 'unsatisfied' if state == 'unsatisfied' else ''
            rows += (
                f'<tr>'
                f'<td>{html.escape(person)}</td>'
                f'<td>{html.escape(room)}</td>'
                f'<td>{price:.2f}</td>'
                f'<td class="{state_class}">{html.escape(state)}</td>'
                f'</tr>'
            )
        table = (
            '<table>'
            '<thead><tr><th>Person</th><th>Room</th><th>Price</th><th>State</th></tr></thead>'
            f'<tbody>{rows}</tbody>'
            '</table>'
        )
        # State form
        state_form = (
            '<form method="post" action="/set_state">'
            '<label>Are you satisfied with your allocation? '
            '<select name="state">'
            '<option value="satisfied">satisfied</option>'
            '<option value="unsatisfied">unsatisfied</option>'
            '</select>'
            '</label>'
            '<button type="submit" class="button">Update</button>'
            '</form>'
        )
        # Swap proposal form
        # List other people
        other_people_options = ''.join(
            f'<option value="{html.escape(p)}">{html.escape(p)}</option>'
            for p in PEOPLE if p != username
        )
        swap_form = (
            '<form method="post" action="/propose_swap">'
            '<label>Propose swap with: '
            f'<select name="target">{other_people_options}</select>'
            '</label><br/>'
            '<label>Offer price: <input type="number" name="price" step="0.01" min="0" required></label>'
            '<button type="submit" class="button">Propose Swap</button>'
            '</form>'
        )
        # Pending swap requests for this user
        pending_html = ''
        user_requests = [req for req in PENDING_SWAPS if req['target'] == username]
        if user_requests:
            pending_html += '<h2>Pending swap proposals for you</h2>'
            for req in user_requests:
                proposer = req['proposer']
                price = req['offered_price']
                # Display details and accept/decline buttons
                pending_html += (
                    f'<p>{html.escape(proposer)} offers to pay {price:.2f} for your room. '
                    'You would move to their room with an adjusted price. '
                    '<form method="post" action="/respond_swap" style="display:inline">'
                    f'<input type="hidden" name="proposer" value="{html.escape(proposer)}">'
                    f'<input type="hidden" name="price" value="{price}">'  # for potential future use
                    '<button name="action" value="accept" class="button" type="submit">Accept</button>'
                    '<button name="action" value="decline" class="button" type="submit">Decline</button>'
                    '</form>'
                    '</p>'
                )
        # Build a global view of all pending swaps as an order book style table
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
                '<h2>Pending Offers (Order Book)</h2>'
                '<table>'
                '<thead><tr><th>Proposer</th><th>Proposer Unit</th>'
                '<th>Target</th><th>Target Unit</th><th>Offered Price</th></tr></thead>'
                f'<tbody>{rows_pending}</tbody>'
                '</table>'
            )
        body = (
            f'<p>You are logged in as <strong>{html.escape(username)}</strong>.</p>'
            f'{table}'
            '<h2>Set your satisfaction state</h2>'
            f'{state_form}'
            '<h2>Propose a room swap</h2>'
            f'{swap_form}'
            f'{pending_html}'
            f'{pending_table}'
        )
        self.send_response(HTTPStatus.OK)
        self._send_html('Room Swap Dashboard', body)


def run(host: str = '0.0.0.0', port: int = 8000) -> None:
    """Start the HTTP server on the given host and port."""
    apartment_price = 3606
    init_allocation(apartment_price)
    server = http.server.HTTPServer((host, port), RoomSwapHandler)
    print(f"Starting room swap server at http://{host}:{port} ...")
    # Attempt to expose the local server via localtunnel if available. This
    # spawns a background thread that executes the `npx localtunnel` command
    # using the provided port. It will print the generated public URL to
    # the console when ready. If localtunnel is not installed, the app
    # simply continues serving locally. See the article on free tunneling
    # services highlighting Localtunnel's simplicity and free availability【909932175077336†L262-L277】.
    def _start_localtunnel(pt: int) -> None:
        try:
            # Run localtunnel via npx. We request a randomly assigned
            # subdomain; localtunnel will display the public URL on stdout.
            proc = subprocess.Popen(
                ['npx', 'localtunnel', '--port', str(pt)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True
            )
            # Read lines until a URL is found or the process ends
            for line in proc.stdout:
                # localtunnel usually prints a line like 'your url is: https://xyz.loca.lt'
                m = re.search(r'https?://\S+', line)
                if m:
                    url = m.group(0)
                    print(f"\nLocaltunnel URL: {url}\n")
                    break
        except Exception as e:
            # If localtunnel isn't installed or fails, report the issue and continue
            print(f"Could not start localtunnel: {e}")

    # Launch localtunnel in a background thread (non-blocking)
    try:
        threading.Thread(target=_start_localtunnel, args=(port,), daemon=True).start()
    except Exception:
        # If threading fails, ignore and continue
        pass
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped by user.")
        server.server_close()


if __name__ == '__main__':
    run()