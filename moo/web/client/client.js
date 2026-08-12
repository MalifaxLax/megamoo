/*
 * MegaMOO web client — core.
 *
 * Owns the socket, the scrollback, the input line, and the event bus that
 * everything else (the map, user scripts) hangs off.
 *
 * Wire protocol (see moo/web/connection.py):
 *
 *   server -> client   {type:"text",   data:"<html>"}
 *                      {type:"text",   data:"<html>", grid:true}
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

const MAX_NODES = 4000;   // scrollback cap; old output is dropped wholesale

/* -------------------------------------------------------------------------
 * Output filters
 * -------------------------------------------------------------------------
 * A filter sees each completed line as plain text and may suppress it or
 * ask for it to be marked.  Registered by commands.js for \trigger; the
 * hook is kept generic so the core never has to know that exists.
 *
 *   fn(text) -> {gag: true} | {highlight: '<class>'} | null
 * ------------------------------------------------------------------------- */

const outputFilters = new Set();

function runOutputFilters(text) {
  let gag = false;
  let highlight = null;
  for (const fn of Array.from(outputFilters)) {
    try {
      const verdict = fn(text);
      if (!verdict) continue;
      if (verdict.gag) gag = true;
      if (verdict.highlight && !highlight) highlight = verdict.highlight;
    } catch (err) {
      console.error('[megamoo] output filter threw:', err);
    }
  }
  return { gag, highlight };
}

/**
 * Cut every *complete* line out of `container`, leaving the unterminated
 * tail in place.
 *
 * Ranges rather than string surgery: a newline can fall inside a <span>,
 * and extractContents() splits the enclosing elements and keeps the
 * markup intact on both sides of the cut, which slicing the HTML string
 * cannot do.
 */
function takeCompleteLines(container) {
  const lines = [];
  for (;;) {
    const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
    let hit = null;
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      const index = node.data.indexOf('\n');
      if (index !== -1) { hit = { node, index }; break; }
    }
    if (!hit) return lines;
    const range = document.createRange();
    range.setStart(container, 0);
    range.setEnd(hit.node, hit.index + 1);   // the newline goes with its line
    lines.push(range.extractContents());
  }
}

const term = {
  /** True when the view is parked at the bottom and should follow output. */
  pinned: true,

  /**
   * The trailing, not-yet-terminated line of plain output.
   *
   * Text accumulates here and only *leaves* once a newline completes the
   * line, which is what gives a trigger something whole to judge before
   * the player sees it.  It stays in the DOM meanwhile, so a prompt
   * written without a newline still appears at once rather than looking
   * like a hung client.
   */
  open: null,

  /**
   * Append server HTML.
   *
   * `html` is trusted *as markup* because moo/web/color.py is its only
   * producer: it escapes all text content and emits nothing but <span>
   * tags with class or a validated hex colour.  Nothing a player types
   * reaches this as markup.  Script output goes through `note()` instead,
   * which never interprets HTML.
   *
   * `grid` marks a block the server composed against a terminal's
   * character cell -- the splash, a full-screen frame.  It gets a block
   * element of its own so it can be laid out at terminal proportions: a
   * span would not do, because line-height on an inline box does not
   * govern the line boxes around it, and art has to own its own lines to
   * come out the shape it was drawn.
   */
  write(html, grid, image, banner) {
    // Composed blocks are not line-oriented, so they are neither buffered
    // nor offered to the filters: a trigger that gagged one row of ASCII
    // art would only wreck the drawing that row was part of.
    if (grid || image || banner) {
      this._closeOpen();
      const node = document.createElement(grid || banner ? 'div' : 'span');
      if (grid) node.className = 'grid';
      // Belongs to the splash, so it is centred under it rather than sitting
      // at the left margin where the conversation starts.
      if (banner) node.className = 'banner';
      node.innerHTML = html;

      // A world that ships a splash image gets it in the banner's place.
      // The ASCII is still built above and kept in `node`, so if the file is
      // missing, misnamed or corrupt the banner appears instead of a broken
      // image icon -- the same banner every other client shows.
      if (image && image.src) {
        const fig = document.createElement('div');
        fig.className = 'splash';
        const img = document.createElement('img');
        // alt, not a decorative empty string: the logo carries the game's
        // name, and that name is not written anywhere else on this screen.
        img.alt = image.alt || '';
        img.onerror = () => fig.replaceWith(node);
        img.src = image.src;
        fig.appendChild(img);
        this._append(fig);
        this._blockLines(node);
        return;
      }
      this._append(node);
      this._blockLines(node);
      return;
    }

    const open = this._openNode();
    // Appending rather than replacing is safe for the same reason the old
    // whole-message innerHTML write was: color.py closes every span it
    // opens before the message ends, so each message stands alone.
    open.insertAdjacentHTML('beforeend', html);
    for (const line of takeCompleteLines(open)) this._emitLine(line);
    this.atLineStart = !open.textContent;
    if (this.pinned) this.toBottom();
  },

  /** The open tail, created on first use and always the last child. */
  _openNode() {
    if (!this.open) {
      this.open = document.createElement('span');
      scrollback.appendChild(this.open);
    }
    return this.open;
  },

  /**
   * Stop adding to the open tail.
   *
   * Whatever is in it stays exactly where it is -- it is an unterminated
   * line, so there is nothing complete for a filter to judge, and a
   * prompt is never gagged.  An empty one would be a stray node, so that
   * goes.
   */
  _closeOpen() {
    if (this.open && !this.open.textContent) this.open.remove();
    this.open = null;
  },

  /**
   * Judge one completed line, and show it unless a filter said not to.
   *
   * The 'line' event fires either way.  A gag hides a line from the
   * player; hiding it from scripts as well would put \trigger gag and the
   * script API in a fight over the same stream.
   */
  _emitLine(fragment) {
    const text = fragment.textContent.replace(/\n$/, '');
    bus.emit('line', text);
    const verdict = runOutputFilters(text);
    if (verdict.gag) return;
    // The line keeps its own trailing newline and stays inline, so every
    // line no filter touches renders exactly as it did before output was
    // buffered at all.
    const span = document.createElement('span');
    if (verdict.highlight) span.className = verdict.highlight;
    span.appendChild(fragment);
    this._append(span);
  },

  /**
   * Publish a composed block's text on the bus, unfiltered.
   *
   * The filters skip these, but a 'line' subscription should still see
   * the same stream it saw before output was buffered -- the splash
   * included.
   */
  _blockLines(node) {
    const text = node.textContent || '';
    if (!text) return;
    const parts = text.split('\n');
    if (parts[parts.length - 1] === '') parts.pop();
    for (const line of parts) bus.emit('line', line);
  },

  /** Append plain text as its own line (client notices, script echo).
   *
   * An echo is the exception. A prompt the server left open -- "Enter your
   * username or NEW to create a new account: ", sent with no newline -- is
   * waiting to be finished by what you type, and a block element cannot
   * finish it: the answer dropped to the line below and the prompt sat
   * there looking unanswered. When the line is still open the echo goes in
   * inline, completing it the way a terminal does.
   *
   * The "> " marker goes with it. At the start of a line it separates what
   * you typed from what the game said, and it earns its place; halfway
   * through a prompt it just reads as noise.
   */
  note(text, kind) {
    // Nothing further will join the open tail: an echo finishes the line
    // it left open, and any other notice starts a new one below it.
    this._closeOpen();
    if (kind === 'echo' && !this.atLineStart) {
      const span = document.createElement('span');
      span.className = 'echo-inline';
      span.textContent = text + '\n';
      this._append(span);
      return;
    }
    const div = document.createElement('div');
    div.className = 'line line--' + (kind || 'client');
    div.textContent = text;
    this._append(div);
  },

  /** Append plain text carrying one extra class (the \test colour sweep). */
  styled(text, className) {
    this._closeOpen();
    const div = document.createElement('div');
    div.className = className ? 'line ' + className : 'line';
    div.textContent = text;
    this._append(div);
  },

  /** True when the last thing appended ended a line, so the next thing
   *  starts one. Anything that leaves a line open -- a prompt -- clears it. */
  atLineStart: true,

  _append(node) {
    // Ahead of the open tail, so a line that completes now cannot jump
    // past the partial one still being assembled. A null ref appends.
    scrollback.insertBefore(node, this.open);
    const text = node.textContent || '';
    if (text) this.atLineStart = text.endsWith('\n');
    while (scrollback.childNodes.length > MAX_NODES) {
      if (scrollback.firstChild === this.open) break;
      scrollback.removeChild(scrollback.firstChild);
    }
    if (this.pinned) this.toBottom();
  },

  clear() {
    scrollback.replaceChildren();
    this.open = null;
    this.atLineStart = true;
    this.toBottom();
  },

  toBottom() {
    scrollback.scrollTop = scrollback.scrollHeight;
    this.pinned = true;
  },
};

// `pinned` decides whether arriving output follows the view down. There
// is no button to get back: typing does it, the way a terminal does.
scrollback.addEventListener('scroll', () => {
  const distance =
    scrollback.scrollHeight - scrollback.scrollTop - scrollback.clientHeight;
  term.pinned = distance < 40;
});

// Backtick-marked words are click targets, matching what telnet clients
// get from MXP: moo/network.py wraps them in <send href="go NAME">, so
// "go" is the verb here too.
scrollback.addEventListener('click', (event) => {
  const target = event.target.closest('.clickable');
  if (!target) return;
  if (window.getSelection().toString()) return;   // a drag-select, not a click
  input.submit('go ' + target.textContent.trim());
});

/* Line extraction now happens in term.write, which buffers the markup
 * itself rather than a parallel plain-text copy of it: a filter that can
 * suppress a line has to run before that line is in the document, and the
 * old strip-to-text pass ran after. */

/* =========================================================================
 * Connection
 * ========================================================================= */

// ?ws= lets the page be served from somewhere other than the game (a dev
// server, a static host) and still find the socket.  Read once rather
// than per call, so \connect can re-point it within the same origin.
let wsOverride = new URLSearchParams(location.search).get('ws') || null;

function socketUrl() {
  if (wsOverride) return wsOverride;
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
    showUpdateNotice();
  }
}

/**
 * Announce that the page is running superseded code.
 *
 * It appears in the header rather than the scrollback, because game
 * output keeps coming and a line saying "you are running old code" is
 * buried within seconds -- being buried is exactly how a stale page goes
 * on being mistaken for a broken feature. And in the header rather than
 * a band above the stage, because that band cost the scrollback and the
 * map a row of height for something that is never urgent.
 */
function showUpdateNotice() {
  const notice = document.getElementById('stale-reload');
  if (notice) notice.hidden = false;
}

document.getElementById('stale-reload')
  ?.addEventListener('click', () => location.reload());

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
      // write() emits 'line' itself, once per completed line, after the
      // output filters have had their say about it.
      term.write(msg.data, msg.grid, msg.image, msg.banner);
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
    // Sending is the other half of "typing returns you to the present":
    // a command issued while reading back belongs at the bottom, next to
    // the answer it is about to get.
    term.toBottom();

    // Never echo or record a masked line: that is the whole point of the
    // mask, and history would otherwise leak the password to the next
    // person at the keyboard.
    if (this.masked) {
      net.send({ type: 'input', data: text });
      // The line still ends, even though nothing of it is shown. A
      // terminal emits this newline itself when you press Enter, and the
      // server counts on it: without one here the password prompt stayed
      // open and the room description arrived on the same line as
      // "Password:". Adding it server-side instead gave telnet, which
      // already had its own, two blank lines and the browser one.
      if (!term.atLineStart) term.note('', 'echo');
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

/** Fields that own their own keystrokes: the script editor, chiefly. */
function isEditable(el) {
  return el instanceof Element
    && el !== cmdInput
    && (/^(input|textarea|select)$/i.test(el.tagName) || el.isContentEditable);
}

// Typing anywhere on the page should reach the command line — a MUD
// habit — and should snap the view back to the newest output, the way a
// terminal does. That snap is what replaced the jump-to-latest button:
// reading back is a scroll, and the next thing you type ends it.
// Modifier combos (copy, find, devtools) are left alone.
document.addEventListener('keydown', (event) => {
  if (event.ctrlKey || event.metaKey || event.altKey) return;
  if (isEditable(event.target)) return;
  // Paging is a deliberate move through the scrollback, so it must not
  // be undone by the very keystroke that made it.
  if (['PageUp', 'PageDown', 'Home', 'End'].includes(event.key)) return;
  if (event.key.length !== 1
      && event.key !== 'Backspace' && event.key !== 'Enter') return;
  if (event.target !== cmdInput) {
    if (window.getSelection().toString()) return;   // don't steal a copy
    cmdInput.focus();
  }
  term.toBottom();
});

// A click on the page puts the caret back in the command line. Unlike
// typing it does not scroll: clicking is how you read back — following a
// link, selecting a line — and yanking the view to the bottom would
// fight that.
document.addEventListener('pointerup', (event) => {
  if (event.button !== 0) return;
  // On a phone the caret arrives with a keyboard over half the screen,
  // so let a tap on the input itself be the thing that asks for it.
  if (event.pointerType === 'touch') return;
  const el = event.target;
  if (!(el instanceof Element) || el === cmdInput) return;
  if (el.closest('button, a, select, textarea, input, dialog, [contenteditable]')) return;
  if (window.getSelection().toString()) return;   // a drag-select, not a click
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

  /**
   * Write a plain-text line carrying one extra CSS class.
   *
   * The class is validated rather than trusted: this is reachable from
   * the input line via \test, and `class` is an attribute worth being
   * careful with even where the text itself can never be markup.
   */
  echoClass(text, className) {
    const name = String(className);
    term.styled(String(text), /^[\w-]+$/.test(name) ? name : '');
  },

  /** Empty the scrollback. */
  clear() { term.clear(); },

  /** Scroll the output: 'up', 'down', or 'end'. */
  scroll(direction) {
    if (direction === 'end') { term.toBottom(); return; }
    scrollback.scrollBy({
      top: scrollback.clientHeight * (direction === 'up' ? -0.9 : 0.9),
    });
  },

  /**
   * Judge each completed output line before the player sees it.
   *
   * Return {gag: true} to drop the line or {highlight: '<class>'} to mark
   * it; anything else shows it unchanged.  The line is published on the
   * bus either way — see term._emitLine.
   */
  filterOutput(handler) {
    outputFilters.add(handler);
    return () => outputFilters.delete(handler);
  },

  /** Where the socket points, so a caller can check it before changing it. */
  get endpoint() { return socketUrl(); },

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

  /**
   * Reconnect, optionally re-pointing the socket.
   *
   * `url` is taken on trust here and vetted by the caller: everything a
   * socket sends is trusted *as markup* by term.write, so the decision
   * about which hosts may feed it belongs with whoever is asking, not
   * buried in the transport.  \connect allows same-origin only.
   */
  reconnect(url) {
    if (url) wsOverride = String(url);
    net.deliberate = false;
    if (net.socket) net.socket.close();   // 'close' schedules the retry
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

// Commands attach first so their interceptor is registered first: input
// interceptors run in insertion order, and a script's alias pattern must
// not get the chance to swallow \help before it is dispatched.
if (window.MegaMOOCommands) window.MegaMOOCommands.attach(api);
if (window.Automap) window.Automap.attach(api);
if (window.Inventory) window.Inventory.attach(api);
if (window.MegaMOOScripting) window.MegaMOOScripting.attach(api);

input.disable();
net.connect();

})();
