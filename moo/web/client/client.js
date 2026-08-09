/*
 * MegaMOO web client — core.
 *
 * Owns the socket, the scrollback, the input line, and the event bus that
 * everything else (the map, user scripts) hangs off.
 *
 * Wire protocol (see moo/web/connection.py):
 *
 *   server -> client   {type:"text",   data:"<html>"}
 *                      {type:"prompt", data:"> "}
 *                      {type:"echo",   enabled:false}
 *                      {type:"gmcp",   package:"Room.Info", data:{...}}
 *
 *   client -> server   {type:"input",  data:"look"}
 *                      {type:"gmcp",   package:"...", data:{...}}
 *
 * Out-of-band data
 * ----------------
 * *Every* GMCP package the server sends is republished on the bus, whether
 * or not this client knows what it means — as `gmcp` and as
 * `gmcp:<Package>`.  Scripts get the whole stream, so a new server-side
 * package needs no client change to become scriptable.
 */
(function () {
'use strict';

/* =========================================================================
 * Event bus
 * ========================================================================= */

/**
 * Minimal synchronous pub/sub.  A throwing handler is reported and
 * skipped: one bad user script must not stop the client from drawing the
 * rest of the frame.
 */
function Bus() {
  this._handlers = new Map();
}

Bus.prototype.on = function (event, fn) {
  if (!this._handlers.has(event)) this._handlers.set(event, new Set());
  this._handlers.get(event).add(fn);
  return () => this.off(event, fn);
};

Bus.prototype.off = function (event, fn) {
  const set = this._handlers.get(event);
  if (set) set.delete(fn);
};

Bus.prototype.emit = function (event, payload) {
  const set = this._handlers.get(event);
  if (!set) return;
  for (const fn of Array.from(set)) {
    try {
      fn(payload);
    } catch (err) {
      console.error(`[megamoo] handler for "${event}" threw:`, err);
      bus.emit('error', { source: event, error: String(err) });
    }
  }
};

const bus = new Bus();

/* =========================================================================
 * xterm-256 palette
 * -------------------------------------------------------------------------
 * moo/web/color.py emits class names only (c245, bg17) and leaves the
 * values to CSS.  Writing 512 rules by hand would be unmaintainable, so
 * the cube is generated from the standard xterm formula at load.
 * ========================================================================= */

function xterm256() {
  // 0-15: the system colours, matched to the named classes in client.css.
  const colors = [
    '#33383f', '#c25450', '#63a95f', '#bd9445',
    '#5178b5', '#a463b0', '#4fa3a8', '#b6bcc6',
    '#6a7381', '#f0655f', '#78d972', '#e8c15c',
    '#6fa4ee', '#cd82db', '#64d0d6', '#f2f5fa',
  ];
  // 16-231: a 6x6x6 cube on xterm's non-linear ramp.
  const ramp = [0, 95, 135, 175, 215, 255];
  const hex = (n) => n.toString(16).padStart(2, '0');
  for (let r = 0; r < 6; r++) {
    for (let g = 0; g < 6; g++) {
      for (let b = 0; b < 6; b++) {
        colors.push(`#${hex(ramp[r])}${hex(ramp[g])}${hex(ramp[b])}`);
      }
    }
  }
  // 232-255: the grayscale ramp.
  for (let i = 0; i < 24; i++) {
    const v = hex(8 + i * 10);
    colors.push(`#${v}${v}${v}`);
  }
  return colors;
}

function installPalette() {
  const rules = xterm256().flatMap((color, i) => [
    `.c${i}{color:${color}}`,
    `.bg${i}{background-color:${color}}`,
  ]);
  const style = document.createElement('style');
  style.textContent = rules.join('');
  document.head.appendChild(style);
}

/* =========================================================================
 * Terminal
 * ========================================================================= */

const scrollback = document.getElementById('scrollback');
const jumpButton = document.getElementById('scroll-latest');

const MAX_NODES = 4000;   // scrollback cap; old output is dropped wholesale

const term = {
  /** True when the view is parked at the bottom and should follow output. */
  pinned: true,

  /**
   * Append server HTML.
   *
   * `html` is trusted *as markup* because moo/web/color.py is its only
   * producer: it escapes all text content and emits nothing but <span>
   * tags with class or a validated hex colour.  Nothing a player types
   * reaches this as markup.  Script output goes through `note()` instead,
   * which never interprets HTML.
   */
  write(html) {
    const span = document.createElement('span');
    span.innerHTML = html;
    this._append(span);
  },

  /** Append plain text as its own line (client notices, script echo). */
  note(text, kind) {
    const div = document.createElement('div');
    div.className = 'line line--' + (kind || 'client');
    div.textContent = text;
    this._append(div);
  },

  _append(node) {
    scrollback.appendChild(node);
    while (scrollback.childNodes.length > MAX_NODES) {
      scrollback.removeChild(scrollback.firstChild);
    }
    if (this.pinned) this.toBottom();
  },

  toBottom() {
    scrollback.scrollTop = scrollback.scrollHeight;
    this.pinned = true;
    jumpButton.hidden = true;
  },
};

scrollback.addEventListener('scroll', () => {
  const distance =
    scrollback.scrollHeight - scrollback.scrollTop - scrollback.clientHeight;
  term.pinned = distance < 40;
  jumpButton.hidden = term.pinned;
});

jumpButton.addEventListener('click', () => term.toBottom());

// Backtick-marked words are click targets, matching what telnet clients
// get from MXP: moo/network.py wraps them in <send href="go NAME">, so
// "go" is the verb here too.
scrollback.addEventListener('click', (event) => {
  const target = event.target.closest('.clickable');
  if (!target) return;
  if (window.getSelection().toString()) return;   // a drag-select, not a click
  input.submit('go ' + target.textContent.trim());
});

/* -------------------------------------------------------------------------
 * Line extraction
 * -------------------------------------------------------------------------
 * Triggers match plain text, but the wire carries HTML, and a message
 * boundary is not a line boundary (a prompt arrives with no trailing
 * newline).  So: strip to text, buffer, and emit only completed lines.
 * ------------------------------------------------------------------------- */

const decoder = document.createElement('div');
let partialLine = '';

function htmlToText(html) {
  decoder.innerHTML = html;
  return decoder.textContent;
}

function feedLines(html) {
  partialLine += htmlToText(html);
  const parts = partialLine.split('\n');
  partialLine = parts.pop();          // trailing fragment stays pending
  for (const line of parts) {
    bus.emit('line', line);
  }
}

/* =========================================================================
 * Connection
 * ========================================================================= */

function socketUrl() {
  // ?ws= lets the page be served from somewhere other than the game
  // (a dev server, a static host) and still find the socket.
  const override = new URLSearchParams(location.search).get('ws');
  if (override) return override;
  const scheme = location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${scheme}//${location.host}/ws`;
}

/* -------------------------------------------------------------------------
 * Staleness detection
 * -------------------------------------------------------------------------
 * A dropped socket reconnects on its own without reloading the page, so
 * after a deploy a player can keep running the JavaScript they loaded
 * hours ago — and a stale client misbehaving is indistinguishable from a
 * server bug. The build stamp is read on load and on every reconnect; if
 * it moves, the page says so rather than leaving anyone to guess.
 * ------------------------------------------------------------------------- */

/** How often to re-check, in ms, independently of connection events. */
const BUILD_POLL_MS = 60000;

let loadedBuild = null;
let staleNoticeShown = false;

async function checkForNewBuild() {
  let build;
  try {
    const response = await fetch('build', { cache: 'no-store' });
    build = (await response.json()).build;
  } catch {
    return;                       // offline or an older server: not fatal
  }
  if (loadedBuild === null) {
    loadedBuild = build;
    return;
  }
  if (build !== loadedBuild && !staleNoticeShown) {
    staleNoticeShown = true;
    showStaleBanner();
  }
}

/**
 * Announce that the page is running superseded code.
 *
 * A banner rather than a scrollback line: game output keeps coming, so a
 * line saying "you are running old code" is buried within seconds -- and
 * being buried is exactly how a stale page goes on being mistaken for a
 * broken feature.
 */
function showStaleBanner() {
  const banner = document.getElementById('stale-banner');
  if (banner) banner.hidden = false;
}

const staleBanner = document.getElementById('stale-banner');
if (staleBanner) {
  document.getElementById('stale-reload')
    .addEventListener('click', () => location.reload());
  document.getElementById('stale-dismiss')
    .addEventListener('click', () => { staleBanner.hidden = true; });
}

// Polled as well as checked on reconnect: a page can sit open for hours
// without the socket ever dropping, and would otherwise never find out.
setInterval(checkForNewBuild, BUILD_POLL_MS);

const statusEl = document.getElementById('conn-status');

function setStatus(state, label) {
  statusEl.className = 'status status--' + state;
  statusEl.textContent = label;
}

const net = {
  socket: null,
  /** Backoff in ms; doubles per failure, reset on a successful open. */
  retryDelay: 1000,
  retryTimer: null,
  /** Set when the player asked to disconnect, to suppress auto-reconnect. */
  deliberate: false,

  connect() {
    clearTimeout(this.retryTimer);
    setStatus('connecting', 'connecting');

    let socket;
    try {
      socket = new WebSocket(socketUrl());
    } catch (err) {
      // A malformed ?ws= override lands here; retrying identically would
      // spin forever, so report it and stop.
      term.note(`Cannot open ${socketUrl()}: ${err}`);
      setStatus('offline', 'offline');
      return;
    }
    this.socket = socket;

    socket.addEventListener('open', () => {
      this.retryDelay = 1000;
      setStatus('online', 'connected');
      bus.emit('connect', null);
      input.enable();
      checkForNewBuild();
    });

    socket.addEventListener('message', (event) => {
      let msg;
      try {
        msg = JSON.parse(event.data);
      } catch {
        return;                        // not ours; ignore rather than throw
      }
      dispatch(msg);
    });

    socket.addEventListener('close', () => {
      this.socket = null;
      input.disable();
      bus.emit('disconnect', null);
      if (this.deliberate) {
        setStatus('offline', 'disconnected');
        return;
      }
      setStatus('offline', `reconnecting in ${Math.round(this.retryDelay / 1000)}s`);
      this.retryTimer = setTimeout(() => this.connect(), this.retryDelay);
      // Cap the backoff so a long outage still recovers promptly once the
      // server returns, rather than sitting out a multi-minute sleep.
      this.retryDelay = Math.min(this.retryDelay * 2, 15000);
    });

    socket.addEventListener('error', () => {
      // 'close' always follows; reconnection is handled there.
    });
  },

  send(obj) {
    if (!this.socket || this.socket.readyState !== WebSocket.OPEN) return false;
    this.socket.send(JSON.stringify(obj));
    return true;
  },
};

/* -------------------------------------------------------------------------
 * Inbound dispatch
 * ------------------------------------------------------------------------- */

function dispatch(msg) {
  switch (msg.type) {
    case 'text':
      term.write(msg.data);
      feedLines(msg.data);
      bus.emit('text', msg.data);
      break;

    case 'prompt':
      input.setPrompt(msg.data);
      bus.emit('prompt', msg.data);
      break;

    case 'echo':
      input.setMasked(!msg.enabled);
      break;

    case 'gmcp':
      // Republish the whole out-of-band stream, known packages or not.
      bus.emit('gmcp', { package: msg.package, data: msg.data });
      bus.emit('gmcp:' + msg.package, msg.data);
      break;

    default:
      bus.emit('unknown', msg);
  }
}

/* =========================================================================
 * Input line
 * ========================================================================= */

const form = document.getElementById('input-row');
const cmdInput = document.getElementById('cmd');
const promptEl = document.getElementById('prompt');

const HISTORY_MAX = 200;

const input = {
  history: [],
  /** Index into history while browsing; == length means "current entry". */
  cursor: 0,
  draft: '',
  masked: false,
  /** Handlers that may claim a line before it reaches the server. */
  interceptors: new Set(),

  enable() {
    cmdInput.disabled = false;
    if (document.activeElement === document.body) cmdInput.focus();
  },

  disable() {
    cmdInput.disabled = true;
  },

  setPrompt(text) {
    // A prompt of only whitespace would collapse the label; keep a marker.
    promptEl.textContent = text.trim() || '>';
  },

  setMasked(masked) {
    this.masked = masked;
    cmdInput.type = masked ? 'password' : 'text';
  },

  submit(text) {
    // Never echo or record a masked line: that is the whole point of the
    // mask, and history would otherwise leak the password to the next
    // person at the keyboard.
    if (this.masked) {
      net.send({ type: 'input', data: text });
      this.setMasked(false);
      return;
    }

    // Echo and record first, so a line an alias swallows still appears —
    // otherwise typing an alias looks like the client dropped the input.
    if (text) this.remember(text);
    term.note(text, 'echo');
    bus.emit('input', text);

    for (const fn of Array.from(this.interceptors)) {
      try {
        if (fn(text) === true) return;   // an alias claimed it
      } catch (err) {
        console.error('[megamoo] input interceptor threw:', err);
      }
    }

    if (!net.send({ type: 'input', data: text })) {
      term.note('Not connected — command not sent.');
    }
  },

  remember(text) {
    if (this.history[this.history.length - 1] !== text) {
      this.history.push(text);
      if (this.history.length > HISTORY_MAX) this.history.shift();
    }
    this.cursor = this.history.length;
  },

  /** Step through history; delta is -1 for older, +1 for newer. */
  browse(delta) {
    if (!this.history.length) return;
    if (this.cursor === this.history.length) this.draft = cmdInput.value;
    const next = Math.min(this.history.length,
                          Math.max(0, this.cursor + delta));
    if (next === this.cursor) return;
    this.cursor = next;
    cmdInput.value = next === this.history.length
      ? this.draft
      : this.history[next];
    // Put the caret at the end, not wherever it happened to be.
    requestAnimationFrame(() => {
      cmdInput.setSelectionRange(cmdInput.value.length, cmdInput.value.length);
    });
  },
};

form.addEventListener('submit', (event) => {
  event.preventDefault();
  const text = cmdInput.value;
  cmdInput.value = '';
  input.submit(text);
});

cmdInput.addEventListener('keydown', (event) => {
  if (event.key === 'ArrowUp') {
    event.preventDefault();
    input.browse(-1);
  } else if (event.key === 'ArrowDown') {
    event.preventDefault();
    input.browse(1);
  } else if (event.key === 'PageUp' || event.key === 'PageDown') {
    event.preventDefault();
    scrollback.scrollBy({
      top: scrollback.clientHeight * (event.key === 'PageUp' ? -0.9 : 0.9),
    });
  }
});

// Typing anywhere on the page should reach the command line — a MUD
// habit. Modifier combos (copy, find, devtools) are left alone.
document.addEventListener('keydown', (event) => {
  if (event.target === cmdInput) return;
  if (event.ctrlKey || event.metaKey || event.altKey) return;
  if (event.key.length !== 1 && event.key !== 'Backspace') return;
  if (window.getSelection().toString()) return;   // don't steal a copy
  cmdInput.focus();
});

/* =========================================================================
 * Public API
 * -------------------------------------------------------------------------
 * The surface user scripts are given (via the script manager, which
 * marshals these calls in and out of its sandboxed hosts) and the same
 * object the page's own modules use.  Kept deliberately small and free of
 * DOM handles: anything reachable from here is reachable from a script.
 * ========================================================================= */

const api = {
  /** Send a command exactly as if the player had typed it. */
  send(command) {
    return net.send({ type: 'input', data: String(command) });
  },

  /** Send a client->server GMCP package. */
  sendGmcp(pkg, data) {
    return net.send({ type: 'gmcp', package: String(pkg), data: data ?? {} });
  },

  /** Write a line to the scrollback. Plain text only — never markup. */
  echo(text, kind) {
    term.note(String(text), kind === 'echo' ? 'echo' : 'client');
  },

  on(event, handler) { return bus.on(event, handler); },
  off(event, handler) { bus.off(event, handler); },
  emit(event, payload) { bus.emit(event, payload); },

  /**
   * Claim input lines before they reach the server (aliases).
   * Return true from `handler` to consume the line.
   */
  intercept(handler) {
    input.interceptors.add(handler);
    return () => input.interceptors.delete(handler);
  },

  /** Current connection state, for scripts that need to poll rather than subscribe. */
  get connected() {
    return !!net.socket && net.socket.readyState === WebSocket.OPEN;
  },

  /** The client build this page loaded, for diagnosing a stale tab. */
  get build() { return loadedBuild; },

  reconnect() {
    net.deliberate = false;
    if (net.socket) net.socket.close();
    else net.connect();
  },

  disconnect() {
    net.deliberate = true;
    if (net.socket) net.socket.close();
  },
};

// Exposed for the other page modules (automap.js, scripting.js) and for
// poking at the client from devtools.
window.MegaMOO = api;

/* =========================================================================
 * Boot
 * ========================================================================= */

installPalette();

if (window.Automap) window.Automap.attach(api);
if (window.MegaMOOScripting) window.MegaMOOScripting.attach(api);

input.disable();
net.connect();

})();
