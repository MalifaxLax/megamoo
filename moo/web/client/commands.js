/*
 * Client commands — the backslash layer, ported from MegaTerm.
 *
 * A line beginning with `\` is the client's own, never the game's: it is
 * claimed before the socket sees it and answered locally.  The command
 * set and its spelling follow MegaTerm's (MegaMOO/Commands/) so muscle
 * memory carries between the native client and this one.
 *
 * \connect keeps MegaTerm's session book:
 *
 *     \con ml <host> <port> <user> <pass>    name a session and connect
 *     \save                                  remember it under that name
 *     \con ml                                connect by name thereafter
 *     \default ml                            and then a bare \con does too
 *
 * A browser still cannot open telnet, so a session resolves to a
 * WebSocket URL (ws://host:port/ws) rather than a telnet socket.  The
 * one thing that does not port is pointing at another *machine* on the
 * fly: everything a socket sends is trusted as markup by term.write, so
 * canRepoint refuses it and offers the ?ws= page-load instead, which
 * starts a fresh document rather than feeding this one from somewhere
 * new.  Any port on this machine is allowed, since that is your own
 * second world rather than someone else's server.
 *
 *   \quit      there is no application to terminate; it disconnects.
 *
 * \edit is deliberately absent.  MegaTerm opens a verb in its own editor
 * over a channel this client does not have; it is a feature to build, not
 * a command to port.
 */
(function () {
'use strict';

/**
 * Recognised at the start of an input line. MegaTerm's default, and like
 * MegaTerm's it is configurable -- see \prefix and STORE_PREFIX.
 *
 * A `let` read at call time rather than captured: every usage string in
 * this file interpolates it from inside a handler, so changing it takes
 * effect on the next line typed without anything having to be rebuilt.
 */
let PREFIX = '\\';

/** Where \prefix keeps its choice. MegaTerm's is `command_prefix`. */
const STORE_PREFIX = 'megamoo.prefix';

/**
 * Characters the game owns, which the client must not shadow.
 *
 * `/` is eval -- `/2+2`, `/sac` -- and parser.py parses it as a verb in
 * its own right. `'` is say and `:` is emote, both real verbs reachable
 * by punctuation. A client that claimed one of these would swallow the
 * game command silently, which is the worst way to lose a feature.
 */
const RESERVED_PREFIXES = new Set(['/', "'", ':', '"']);

const STORE_ALIASES = 'megamoo.aliases';
const STORE_TRIGGERS = 'megamoo.triggers';

/**
 * handle -> {host, port, username, password}.
 *
 * ON STORING CREDENTIALS.  This is localStorage: plain text, readable by
 * any script on this origin, and it outlives the tab.  MegaTerm keeps the
 * same fields in ~/.megamoo-client.json, which is at least a file with
 * user permissions rather than a browser origin.  The socket is also ws://
 * and not wss:// in every world shipped so far, so a saved password
 * crosses the network in clear as well as resting in clear.  \save says so
 * the first time it is asked to store one.
 */
const STORE_SESSIONS = 'megamoo.sessions';

/** Handle that a bare \con uses, as MegaTerm's default_name does. */
const STORE_DEFAULT = 'megamoo.defaultSession';

/**
 * Highlight styles, as an allowlist mapping a name to a CSS class.
 *
 * Backgrounds rather than colours: game text arrives already wrapped in
 * its own colour spans, and those win over any colour set on an ancestor
 * — so a foreground highlight would be invisible on exactly the coloured
 * lines people most want to mark.
 */
const HIGHLIGHTS = {
  yellow: 'hl-yellow',
  red: 'hl-red',
  green: 'hl-green',
  cyan: 'hl-cyan',
  blue: 'hl-blue',
  magenta: 'hl-magenta',
  grey: 'hl-grey',
  gray: 'hl-grey',
};

let api = null;

/* =========================================================================
 * State
 * ========================================================================= */

/** name -> expansion. First word only, as in MegaTerm. */
let aliases = {};

/** [{name, type, pattern, action, value, enabled}] */
let triggers = [];

/** Compiled counterparts of `triggers`, rebuilt whenever that changes. */
let compiled = [];

/** handle -> {host, port, username, password}. See STORE_SESSIONS. */
let sessions = {};

/**
 * The session in play, or null.
 *
 * Held separately from `sessions` so \con can connect without committing
 * anything to storage: you try a host, and \save is what writes it down.
 * That is MegaTerm's order too, and it means a mistyped password is not
 * persisted by the act of failing to log in with it.
 */
let current = null;

/** Credentials waiting for the socket to come up. See scheduleAutoLogin. */
let pendingLogin = null;

/**
 * Handle a bare \con goes to, or null.
 *
 * Null is the meaningful default here rather than an oversight: with none
 * set, \con keeps the behaviour this client had before sessions existed
 * and reconnects where it already is, which is right for a page served by
 * the very game it is talking to.
 */
let defaultHandle = null;

let speechOn = false;

function load(key, fallback) {
  try {
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw) : fallback;
  } catch {
    return fallback;        // corrupt or unavailable storage is not fatal
  }
}

function save(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch (err) {
    note(`*** Could not save: ${err}`);
  }
}

/**
 * Recompile the trigger patterns.
 *
 * A pattern that no longer compiles is dropped from the compiled set but
 * kept in the stored one: it is still listed, still editable and still
 * removable, which a silently discarded trigger would not be.
 */
function recompile() {
  compiled = [];
  for (const t of triggers) {
    if (!t.enabled) continue;
    try {
      compiled.push({ trigger: t, re: new RegExp(t.pattern) });
    } catch (err) {
      note(`*** Trigger '${t.name}' has an invalid pattern and is inactive: ${err.message}`);
    }
  }
}

function note(text) {
  if (api) api.echo(text);
  else console.log('[megamoo]', text);
}

/* =========================================================================
 * Argument splitting
 * -------------------------------------------------------------------------
 * Ported from CommandHandlers.shellSplit so a quoted regex containing
 * spaces means the same thing in both clients.
 * ========================================================================= */

function shellSplit(input) {
  const args = [];
  let current = '';
  let single = false;
  let double = false;
  let escaped = false;

  for (const ch of input) {
    if (escaped) { current += ch; escaped = false; continue; }
    if (ch === '\\' && !single) { escaped = true; continue; }
    if (ch === "'" && !double) { single = !single; continue; }
    if (ch === '"' && !single) { double = !double; continue; }
    if (ch === ' ' && !single && !double) {
      if (current) { args.push(current); current = ''; }
      continue;
    }
    current += ch;
  }
  if (current) args.push(current);
  return args;
}

/* =========================================================================
 * Triggers
 * ========================================================================= */

/**
 * Judge one line of game output.
 *
 * Runs as the client's output filter, so it is called once per completed
 * line before that line is shown, and its answer decides whether it is
 * shown at all.
 */
function evalLine(text) {
  let gag = false;
  let highlight = null;

  for (const { trigger, re } of compiled) {
    if (trigger.type !== 'text') continue;
    // Reset every time: a /g pattern would otherwise remember where the
    // previous line ended and skip a match on this one.
    re.lastIndex = 0;
    if (!re.test(text)) continue;

    if (trigger.action === 'gag') gag = true;
    else if (trigger.action === 'highlight') {
      if (!highlight) highlight = HIGHLIGHTS[trigger.value] || HIGHLIGHTS.yellow;
    } else if (trigger.action === 'send') {
      api.send(trigger.value);
    }
  }

  // Spoken here rather than from a 'line' subscription: this is the only
  // place that knows the line survived the gag.
  if (speechOn && !gag && text.trim()) speak(text);

  return { gag, highlight };
}

/** GMCP triggers match a package name and can only send. */
function evalGmcp(pkg) {
  for (const { trigger, re } of compiled) {
    if (trigger.type !== 'gmcp') continue;
    re.lastIndex = 0;
    if (re.test(pkg) && trigger.action === 'send') api.send(trigger.value);
  }
}

/* =========================================================================
 * Speech
 * ========================================================================= */

function speechAvailable() {
  return typeof window.speechSynthesis !== 'undefined';
}

function speak(text) {
  try {
    window.speechSynthesis.speak(new SpeechSynthesisUtterance(text));
  } catch (err) {
    console.warn('[megamoo] speech failed:', err);
  }
}

/* =========================================================================
 * Handlers
 * ========================================================================= */

/**
 * Is `host` a misspelling of "localhost" rather than a real elsewhere?
 *
 * One edit away, by the cheap length-difference-plus-mismatch test rather
 * than a full Levenshtein: this only has to catch a slip like `localost`
 * or `lcoalhost`, and being wrong in either direction costs nothing worse
 * than a suggestion. Never treats the name as loopback -- it only changes
 * what the refusal says.
 */
function nearlyLocalhost(host) {
  const a = String(host).toLowerCase();
  const b = 'localhost';
  if (a === b || Math.abs(a.length - b.length) > 1) return false;
  if (a.length === b.length) {                 // one substitution or swap
    let diff = 0;
    for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) diff++;
    return diff > 0 && diff <= 2;
  }
  const [longer, shorter] = a.length > b.length ? [a, b] : [b, a];
  for (let i = 0; i < longer.length; i++) {    // one insertion or deletion
    if (longer.slice(0, i) + longer.slice(i + 1) === shorter) return true;
  }
  return false;
}

/**
 * May the live socket be re-pointed at `url`?
 *
 * Same origin only, and this is not a stylistic choice — the *server*
 * enforces it. moo/web/server.py:_origin_allowed compares the browser's
 * `Origin` against `Host` and answers **403** to anything else, so that no
 * page a logged-in player wanders onto can open a socket and drive their
 * game as them. A cross-origin re-point is not a thing the client may
 * decide to permit; it is a thing the far end refuses.
 *
 * It is also the rule this page wants for itself. Everything arriving on
 * the socket is trusted *as markup* by the terminal, which is safe exactly
 * because the server at the other end is the one that escaped it. A socket
 * aimed elsewhere is script execution here and a convincing fake password
 * prompt.
 *
 * `host`, so the port counts: a different port is a different origin to
 * the check at the far end, whatever it is to a person. Reaching another
 * of your worlds is done by going to *its* page — see connectTo — which
 * needs no exception here, because a page served by the world it talks to
 * is same-origin once it loads.
 */
function canRepoint(url) {
  try {
    return new URL(url).host === location.host;
  } catch {
    return false;
  }
}

/** A session's WebSocket endpoint. The path is fixed by moo/web/server.py. */
function sessionUrl(s) {
  return `ws://${s.host}:${s.port}/ws`;
}

/** Known handles, for the "no such session" reply. */
function sessionList() {
  const names = Object.keys(sessions).sort();
  return names.length ? names.join(', ') : '(none saved)';
}

/**
 * Read the World: field into \con's argument list.
 *
 * The field takes either a saved handle on its own, or a handle followed
 * by an address:
 *
 *     bml                     a saved world
 *     bml localhost:8890      name one and connect
 *
 * `host:port` rather than \con's `host port` because a colon is how a
 * person writes an address into a box, while the command line already
 * splits on spaces and cannot. Anything after the address is passed on
 * untouched, so the credentials \con accepts work here too.
 *
 * Returns an argv array for handlers.connect, or {error} to report.
 */
function parseWorldField(text) {
  const parts = String(text).trim().split(/\s+/).filter(Boolean);
  if (!parts.length) return null;
  const handle = parts[0];
  if (parts.length === 1) return [handle];

  const addr = parts[1];
  // lastIndexOf, so a bracketed IPv6 literal keeps its own colons.
  const cut = addr.lastIndexOf(':');
  const host = cut === -1 ? '' : addr.slice(0, cut);
  const port = cut === -1 ? '' : addr.slice(cut + 1);
  if (!host || !port) {
    return { error: `Expected <handle> <host>:<port>, as in `
                    + `"${handle} localhost:8890".` };
  }
  return [handle, host, port, ...parts.slice(2)];
}

/**
 * Fill the header's world picker from the session book.
 *
 * Called wherever `sessions` changes rather than polled: the datalist is
 * the only place a saved handle is discoverable without typing a command,
 * so a stale one is a world you cannot see you have.
 *
 * Tolerates the elements being absent — the command layer is loaded by
 * anything that includes commands.js, and it should not depend on a
 * particular page's chrome existing.
 */
function refreshWorldUI() {
  const list = document.getElementById('world-list');
  const field = document.getElementById('world-name');
  if (!list || !field) return;
  list.textContent = '';
  for (const name of Object.keys(sessions).sort()) {
    const option = document.createElement('option');
    option.value = name;
    list.appendChild(option);
  }
  // Only when empty: refilling under someone mid-type would fight them.
  if (!field.value) {
    field.value = (current && current.handle) || defaultHandle || '';
  }
}

/**
 * Send the stored credentials once the socket is up.
 *
 * Timed rather than driven off the login prompt, which is what MegaTerm
 * does (SessionState.scheduleAutoLogin): the prompt is a bare string that
 * a world is free to reword, and a matcher that guesses wrong would type
 * a password into whatever else was on screen.  A delay types it into
 * nothing at worst.
 *
 * The username is echoed so the transcript reads like a normal login. The
 * password never is: it would otherwise sit in the scrollback, in
 * screenshots, and in anything the player copies out of it.
 */
function scheduleAutoLogin(creds) {
  if (!creds || !creds.username) return;
  setTimeout(() => {
    if (!api.connected) return;
    // api.echo(_, 'echo'), not note(): 'echo' is what the input row uses
    // for a line you typed, and it goes *into* the prompt the server left
    // open, in the same colour a typed answer has. note() defaults to the
    // client's own notice style -- faint, italic, and on a line of its
    // own -- so the name appeared under the prompt rather than on it.
    api.echo(creds.username, 'echo');
    api.send(creds.username);
    if (!creds.password) return;
    setTimeout(() => {
      if (!api.connected) return;
      api.send(creds.password);
      // The password is never shown, but the line it answered still has to
      // end -- the masked input path does exactly this, and for the same
      // reason: without it "Password:" stays open and the room description
      // arrives on the same line as the prompt.
      //
      // Exactly one, matching that path. A second echo here looked like it
      // would add the blank line the login wanted, and did -- on top of the
      // break this one already makes, which is one line too many. Whatever
      // spacing follows a password is the server's to send, so that both
      // clients get the same of it.
      api.echo('', 'echo');
    }, 500);
  }, 1000);
}

/**
 * Point the client at `s`, by whichever route actually reaches it.
 *
 * Same origin: re-point the live socket, which keeps the scrollback.
 *
 * Anywhere else: **go to that world's own page**.  Re-pointing cannot work
 * across origins however much the client would like it to -- the server
 * answers 403 to a socket whose `Origin` is not its `Host`, and the ?ws=
 * link this used to offer had exactly the same problem, since the document
 * still came from here.  A world serves its own client, so arriving there
 * makes the socket same-origin and the question disappears rather than
 * being argued with.
 *
 * The cost is a page load: the scrollback goes, and localStorage is
 * per-origin, so the world you land on keeps its own session book rather
 * than this one's.  Both are said out loud below instead of surprising
 * someone who typed a name and lost their screen.
 */
function connectTo(s, handle) {
  const url = sessionUrl(s);
  current = Object.assign({}, s, { handle });

  if (canRepoint(url)) {
    note(`*** Connecting to ${handle} (${url})...`);
    pendingLogin = s.username ? { username: s.username, password: s.password } : null;
    api.reconnect(url);
    return;
  }

  // A near-miss of "localhost" is a typo, not another world. Caught before
  // navigating, because leaving the page over a slip is a poor trade.
  if (nearlyLocalhost(s.host)) {
    note(`*** No such host "${s.host}" — did you mean localhost?`);
    note(`    ${PREFIX}con ${handle} localhost ${s.port}`);
    return;
  }

  // The handle rides along, and *only* the handle. It is a name you chose,
  // not a secret, so it is safe in a URL -- which a password never is:
  // query strings reach history, bookmarks, logs and referrers. The world's
  // own page looks the name up in its own storage and logs in from there,
  // so credentials are read on the origin that already had them and never
  // travel between the two.
  const href = `http://${s.host}:${s.port}/?session=${encodeURIComponent(handle)}`;
  note(`*** ${handle} is a different world, so it is opened as its own page.`);
  note(`    ${href}`);
  location.assign(href);
}

const handlers = {

  /* ---- connection ---- */

  connect(args) {
    const first = args[0];

    // No argument: the default session if one is set -- MegaTerm's rule --
    // and otherwise reconnect where we already are.
    if (!first) {
      if (defaultHandle && sessions[defaultHandle]) {
        connectTo(sessions[defaultHandle], defaultHandle);
        return;
      }
      note('*** Reconnecting...');
      pendingLogin = current && current.username
        ? { username: current.username, password: current.password }
        : null;
      api.reconnect();
      return;
    }

    // An explicit URL still works, and still only within this origin.
    if (/^wss?:\/\//i.test(first)) {
      if (!canRepoint(first)) {
        note('*** Refusing: that is a different origin. The server answers');
        note('    403 to a socket whose Origin is not its Host, and this');
        note('    terminal trusts what a socket sends as markup. To play');
        note(`    elsewhere, ${PREFIX}con <handle> <host> <port> — that opens`);
        note('    the world\'s own page instead of re-pointing this one.');
        return;
      }
      note(`*** Connecting to ${first}...`);
      pendingLogin = null;
      api.reconnect(first);
      return;
    }

    // \con <handle> -- a saved session.
    if (args.length === 1) {
      const s = sessions[first];
      if (!s) {
        note(`*** No session named '${first}'. Saved: ${sessionList()}`);
        note(`    ${PREFIX}con ${first} <host> <port> [user] [pass] names one.`);
        return;
      }
      connectTo(s, first);
      return;
    }

    // \con <handle> <host> <port> [user] [pass] -- name one and connect.
    // Not stored yet: \save is what writes it down, so a wrong password is
    // not persisted by the act of failing to log in with it.
    if (args.length >= 3) {
      const port = Number(args[2]);
      if (!Number.isInteger(port) || port < 1 || port > 65535) {
        note('*** Port must be a whole number between 1 and 65535.');
        // Nearly always the handle being left off: `\con localhost 8890
        // user pass` reads as handle=localhost, host=8890, and then a
        // username where the port should be. Saying "port must be a
        // number" while pointing at a word that was never meant to be one
        // is true and no help at all.
        const maybePort = Number(args[1]);
        if (Number.isInteger(maybePort) && maybePort > 0 && maybePort <= 65535) {
          note('    The first word names the session, so that reads as');
          note(`    host "${args[1]}" and port "${args[2]}". You want:`);
          note(`    ${PREFIX}con <handle> ${args[0]} ${args[1]}`
               + (args.length > 3 ? ' ...' : ''));
        } else {
          note(`    Usage: ${PREFIX}con <handle> <host> <port> [user] [pass]`);
        }
        return;
      }
      // Re-pointing a handle keeps the credentials you already saved for
      // it, so changing a port does not mean retyping a password.
      const saved = sessions[first] || {};
      connectTo({
        host: args[1],
        port,
        username: args.length >= 4 ? args[3] : saved.username,
        password: args.length >= 5 ? args[4] : saved.password,
      }, first);
      return;
    }

    note(`*** Usage: ${PREFIX}connect [handle] [host] [port] [user] [pass]`);
    note(`           ${PREFIX}connect [ws://host:port/ws]`);
    note(`    Saved: ${sessionList()}`);
  },

  disconnect() {
    if (!api.connected) { note('*** Not connected.'); return; }
    note('*** Disconnecting...');
    api.disconnect();
  },

  quit() {
    // A browser tab is not ours to close: window.close() is refused for
    // any page the script did not itself open.
    note('*** A browser tab cannot close itself — disconnecting instead.');
    api.disconnect();
  },

  save() {
    if (!current) {
      note('*** Nothing to save: no session in play.');
      note(`    ${PREFIX}con <handle> <host> <port> [user] [pass] first.`);
      note('    Aliases and triggers are stored as you set them.');
      return;
    }
    const { handle, host, port, username, password } = current;
    const first = !sessions[handle];
    sessions[handle] = { host, port, username, password };
    save(STORE_SESSIONS, sessions);
    refreshWorldUI();
    note(`*** Saved '${handle}' -> ${host}:${port}`
         + (username ? ` as ${username}` : ''));
    if (password && first) {
      // Said once per handle, not on every re-save, so it stays a warning
      // rather than noise -- but said at all, because "the browser
      // remembers it" reads as something safer than it is.
      note('    Note: the password is kept in this browser\'s localStorage in');
      note('    plain text, and ws:// sends it unencrypted. Fine for a local');
      note('    world; think twice on a shared machine or a public server.');
    }
    note(`    ${PREFIX}con ${handle} connects to it from now on.`);
  },

  forget(args) {
    const handle = args[0];
    if (!handle) {
      note(`*** Usage: ${PREFIX}forget <handle>.  Saved: ${sessionList()}`);
      return;
    }
    if (!sessions[handle]) {
      note(`*** No session named '${handle}'. Saved: ${sessionList()}`);
      return;
    }
    delete sessions[handle];
    save(STORE_SESSIONS, sessions);
    refreshWorldUI();
    note(`*** Forgot '${handle}', password included.`);
    if (defaultHandle === handle) {
      // Otherwise a bare \con would point at a session that is gone.
      defaultHandle = null;
      save(STORE_DEFAULT, null);
      note('    It was the default; that is cleared too.');
    }
  },

  prefix(args) {
    const want = args[0];
    if (!want) {
      note(`*** Command prefix is "${PREFIX}".`);
      note(`    ${PREFIX}prefix <char> changes it.`);
      return;
    }
    if ([...want].length !== 1) {
      note('*** A prefix is a single character.');
      return;
    }
    if (/[\w\s]/.test(want)) {
      // A letter or digit would eat ordinary game commands: with `k` as
      // the prefix, `kill orc` is a client command that does not exist.
      note('*** A letter, digit or space cannot be a prefix -- it would');
      note('    swallow ordinary commands typed to the game.');
      return;
    }
    if (RESERVED_PREFIXES.has(want)) {
      const why = want === '/' ? 'eval' : want === ':' ? 'emote' : 'say';
      note(`*** "${want}" is a game command (${why}); the client claiming it`);
      note('    would shadow it silently. Pick another character.');
      return;
    }
    PREFIX = want;
    save(STORE_PREFIX, want);
    note(`*** Command prefix is now "${want}" -- ${want}help lists commands.`);
  },

  sessions() {
    const names = Object.keys(sessions).sort();
    if (!names.length) {
      note('*** No saved sessions.');
      note(`    ${PREFIX}con <handle> <host> <port> [user] [pass] then ${PREFIX}save.`);
      return;
    }
    note('*** Saved sessions:');
    for (const n of names) {
      const s = sessions[n];
      // The password is never printed, only acknowledged.
      const who = s.username ? `  ${s.username}` : '';
      const pw = s.password ? ' +password' : '';
      const marks = [];
      if (current && current.handle === n) marks.push('current');
      if (defaultHandle === n) marks.push('default');
      const tail = marks.length ? `  <- ${marks.join(', ')}` : '';
      note(`    ${n.padEnd(12)} ${s.host}:${s.port}${who}${pw}${tail}`);
    }
  },

  default: function setDefault(args) {
    const handle = args[0];
    if (!handle) {
      if (defaultHandle && sessions[defaultHandle]) {
        const s = sessions[defaultHandle];
        note(`*** Default: ${defaultHandle} -> ${s.host}:${s.port}`);
      } else if (defaultHandle) {
        // Survives its session being forgotten out from under it only if
        // that happened in another tab; say so rather than silently ignore.
        note(`*** Default is '${defaultHandle}', which is no longer saved.`);
      } else {
        note('*** No default set; a bare \\con reconnects where you are.');
      }
      note(`    ${PREFIX}default <handle> sets it.  Saved: ${sessionList()}`);
      return;
    }
    if (handle === '-' || handle === 'none') {
      defaultHandle = null;
      save(STORE_DEFAULT, null);
      note('*** Default cleared; a bare \\con reconnects where you are.');
      return;
    }
    if (!sessions[handle]) {
      note(`*** No session named '${handle}'. Saved: ${sessionList()}`);
      note(`    Save it first: ${PREFIX}con ${handle} <host> <port> ... then ${PREFIX}save.`);
      return;
    }
    defaultHandle = handle;
    save(STORE_DEFAULT, handle);
    const s = sessions[handle];
    note(`*** Default is now '${handle}' -> ${s.host}:${s.port}.`);
    note(`    A bare ${PREFIX}con goes there.`);
  },

  /* ---- display ---- */

  clear() {
    api.clear();
  },

  su() { api.scroll('up'); },
  sd() { api.scroll('down'); },
  se() { api.scroll('end'); },

  speech() {
    if (!speechAvailable()) {
      note('*** This browser has no speech synthesis.');
      return;
    }
    speechOn = !speechOn;
    if (speechOn) {
      note('*** Speech enabled.');
      speak('Speech enabled.');
    } else {
      window.speechSynthesis.cancel();
      note('*** Speech disabled.');
    }
  },

  /* ---- aliases ---- */

  alias(args) {
    const names = Object.keys(aliases).sort();

    if (!args.length) {
      if (!names.length) { note('*** No aliases defined.'); return; }
      for (const name of names) note(`  ${name} = ${aliases[name]}`);
      return;
    }
    if (args.length === 1) {
      const name = args[0];
      note(name in aliases
        ? `  ${name} = ${aliases[name]}`
        : `*** No alias '${name}'.`);
      return;
    }
    const name = args[0];
    const value = args.slice(1).join(' ');
    aliases[name] = value;
    save(STORE_ALIASES, aliases);
    note(`*** Alias set: ${name} = ${value}`);
  },

  unalias(args) {
    const name = args[0];
    if (!name) { note(`Usage: ${PREFIX}unalias <name>`); return; }
    if (!(name in aliases)) { note(`*** No alias '${name}'.`); return; }
    delete aliases[name];
    save(STORE_ALIASES, aliases);
    note(`*** Alias '${name}' removed.`);
  },

  /* ---- triggers ---- */

  trigger(args, raw) {
    const parts = shellSplit(raw);
    const sub = (parts[0] || '').toLowerCase();
    const rest = parts.slice(1);

    switch (sub) {
      case '': case 'help': return triggerHelp();
      case 'add': return triggerAdd(rest);
      case 'remove': return triggerRemove(rest);
      case 'enable': return triggerSetEnabled(rest, true);
      case 'disable': return triggerSetEnabled(rest, false);
      case 'list': return triggerList();
      case 'test': return triggerTest(rest);
      default: note(`*** Unknown trigger subcommand: ${sub}`);
    }
  },

  /* ---- help ---- */

  help() {
    const p = PREFIX;
    note(`  ${p}con [handle] [host] [port] [user] [pass] - Connect`);
    note(`  ${p}save                         - Remember the session in play`);
    note(`  ${p}sessions                     - List saved sessions`);
    note(`  ${p}default [handle]             - Where a bare ${p}con goes (- clears)`);
    note(`  ${p}forget <handle>              - Delete one, password included`);
    note(`  ${p}prefix [char]                - Change this "${p}" (not / ' : ")`);
    note(`  ${p}disconnect                   - Disconnect`);
    note(`  ${p}quit                         - Disconnect (a tab cannot self-close)`);
    note(`  ${p}clear                        - Clear output`);
    note(`  ${p}alias [name] [value...]      - Set or list aliases`);
    note(`  ${p}unalias <name>               - Remove an alias`);
    note(`  ${p}trigger <sub> ...            - Manage triggers (${p}trigger help)`);
    note(`  ${p}speech                       - Toggle text-to-speech`);
    note(`  ${p}su / ${p}sd / ${p}se              - Scroll up / down / end`);
    note(`  ${p}test [ansi|plain]            - Fill the scrollback for testing`);
    note(`  ${p}help                         - This help`);
    note('  Up / Down                      - Command history');
    note('  PageUp / PageDown              - Scroll output');
    note('  Scripts button                 - JavaScript and Lua scripting');
  },

  /* ---- test ---- */

  test(args) {
    const mode = args[0] || 'ansi';
    for (let i = 0; i < 100; i++) {
      const label = `Line ${String(i).padStart(3, '0')}: ` +
                    'The quick brown fox jumps over the lazy dog';
      if (mode === 'plain') api.echo(label);
      else api.echoClass(label, 'c' + ((i % 216) + 16));
    }
    note(`--- Done (${mode}). Scroll up to see them. ---`);
  },
};

/* ---- trigger subcommands ---- */

function triggerHelp() {
  const p = PREFIX;
  note(`  ${p}trigger add <name> text <pattern> <action> [value]`);
  note(`  ${p}trigger add <name> gmcp <package> send <command>`);
  note('    actions: send <command>, highlight <style>, gag');
  note(`    styles:  ${Object.keys(HIGHLIGHTS).join(', ')}`);
  note(`  ${p}trigger remove <name>`);
  note(`  ${p}trigger enable <name>`);
  note(`  ${p}trigger disable <name>`);
  note(`  ${p}trigger list`);
  note(`  ${p}trigger test <text...>`);
  note('    Patterns are regular expressions; quote one containing spaces.');
}

function triggerAdd(args) {
  if (args.length < 4) {
    note(`*** Usage: ${PREFIX}trigger add <name> <text|gmcp> <pattern> <action> [value]`);
    return;
  }
  const [name, rawType, pattern, rawAction] = args;
  const type = rawType.toLowerCase();
  const action = rawAction.toLowerCase();
  const value = args.length > 4 ? args.slice(4).join(' ') : '';

  if (type !== 'text' && type !== 'gmcp') {
    note("*** Trigger type must be 'text' or 'gmcp'.");
    return;
  }
  if (!['send', 'highlight', 'gag'].includes(action)) {
    note("*** Action must be 'send', 'highlight', or 'gag'.");
    return;
  }
  if ((action === 'send' || action === 'highlight') && !value) {
    note(`*** Action '${action}' requires a value.`);
    return;
  }
  if (action === 'highlight' && !(value in HIGHLIGHTS)) {
    note(`*** Unknown style '${value}'. Try: ${Object.keys(HIGHLIGHTS).join(', ')}`);
    return;
  }
  // gag and highlight need a line to act on, which a GMCP package is not.
  if (type === 'gmcp' && action !== 'send') {
    note("*** GMCP triggers can only 'send' — there is no line to gag or mark.");
    return;
  }
  try {
    new RegExp(pattern);
  } catch (err) {
    note(`*** Invalid regex pattern: ${err.message}`);
    return;
  }

  triggers = triggers.filter((t) => t.name !== name);
  triggers.push({ name, type, pattern, action, value, enabled: true });
  save(STORE_TRIGGERS, triggers);
  recompile();
  note(`*** Trigger '${name}' added: ${type} /${pattern}/ -> ${action}${value ? ' ' + value : ''}`);
}

function triggerRemove(args) {
  const name = args[0];
  if (!name) { note(`*** Usage: ${PREFIX}trigger remove <name>`); return; }
  const before = triggers.length;
  triggers = triggers.filter((t) => t.name !== name);
  if (triggers.length === before) { note(`*** No trigger named '${name}'.`); return; }
  save(STORE_TRIGGERS, triggers);
  recompile();
  note(`*** Trigger '${name}' removed.`);
}

function triggerSetEnabled(args, enabled) {
  const name = args[0];
  const word = enabled ? 'enable' : 'disable';
  if (!name) { note(`*** Usage: ${PREFIX}trigger ${word} <name>`); return; }
  const trigger = triggers.find((t) => t.name === name);
  if (!trigger) { note(`*** No trigger named '${name}'.`); return; }
  trigger.enabled = enabled;
  save(STORE_TRIGGERS, triggers);
  recompile();
  note(`*** Trigger '${name}' ${word}d.`);
}

function triggerList() {
  if (!triggers.length) { note('*** No triggers defined.'); return; }
  note(`*** Triggers (${triggers.length}):`);
  for (const t of triggers) {
    const status = t.enabled ? 'ON' : 'OFF';
    const value = t.value ? ` -> ${t.value}` : '';
    note(`  [${status}] ${t.name}: ${t.type} /${t.pattern}/ ${t.action}${value}`);
  }
}

/**
 * Dry-run the text triggers against a line the player supplies.
 *
 * Deliberately not evalLine: that one *acts* — it would fire every
 * matching send and speak the line.  A test with side effects is not a
 * test.
 */
function triggerTest(args) {
  if (!args.length) { note(`*** Usage: ${PREFIX}trigger test <text...>`); return; }
  const text = args.join(' ');
  note(`*** Testing: ${text}`);

  let matched = false;
  for (const { trigger, re } of compiled) {
    if (trigger.type !== 'text') continue;
    re.lastIndex = 0;
    if (!re.test(text)) continue;
    matched = true;
    if (trigger.action === 'gag') note(`  -> GAGGED by '${trigger.name}'`);
    else if (trigger.action === 'highlight') note(`  -> Highlighted ${trigger.value} by '${trigger.name}'`);
    else note(`  -> Send: ${trigger.value}`);
  }
  if (!matched) note('  -> No triggers matched.');
}

/* =========================================================================
 * Dispatch
 * ========================================================================= */

function runCommand(line) {
  const trimmed = line.trim();
  if (!trimmed) return;

  const split = trimmed.indexOf(' ');
  const name = (split === -1 ? trimmed : trimmed.slice(0, split)).toLowerCase();
  const raw = split === -1 ? '' : trimmed.slice(split + 1).trim();
  const args = raw ? raw.split(/\s+/) : [];

  // The abbreviations MegaTerm accepts.
  // `ses`, not `se` -- \se is scroll-to-end and was here first.
  const canonical = { con: 'connect', def: 'default', ses: 'sessions' }[name] || name;

  const handler = Object.hasOwn(handlers, canonical) ? handlers[canonical] : null;
  if (!handler) {
    note(`*** Unknown command: ${name}. Type ${PREFIX}help for help.`);
    return;
  }
  // `raw` as well as `args`: \trigger needs the unsplit string so it can
  // apply its own quoting rules.
  handler(args, raw);
}

/**
 * Expand a first-word alias, or return null if none applies.
 *
 * First word only, matching MegaTerm — `k orc` with `k = kill` sends
 * `kill orc`, but an alias never rewrites the middle of a line.
 */
function expandAlias(text) {
  const trimmed = text.trim();
  if (!trimmed) return null;
  const split = trimmed.indexOf(' ');
  const head = split === -1 ? trimmed : trimmed.slice(0, split);
  if (!Object.hasOwn(aliases, head)) return null;
  const tail = split === -1 ? '' : trimmed.slice(split + 1);
  return tail ? `${aliases[head]} ${tail}` : aliases[head];
}

/* =========================================================================
 * Public surface
 * ========================================================================= */

window.MegaMOOCommands = {

  attach(clientApi) {
    api = clientApi;

    aliases = load(STORE_ALIASES, {});
    triggers = load(STORE_TRIGGERS, []);
    sessions = load(STORE_SESSIONS, {});
    defaultHandle = load(STORE_DEFAULT, null);
    // Validated on the way back in, not just on the way out: storage is
    // editable by hand, and a prefix of "" or "kill" would make every
    // command either unreachable or ruinous.
    const storedPrefix = load(STORE_PREFIX, null);
    if (typeof storedPrefix === 'string' && [...storedPrefix].length === 1
        && !/[\w\s]/.test(storedPrefix) && !RESERVED_PREFIXES.has(storedPrefix)) {
      PREFIX = storedPrefix;
    }
    recompile();

    // Credentials are sent on the socket coming up, not at the moment the
    // command is typed: \con returns immediately and the connection is
    // still being made. Cleared on use so a later reconnect the player did
    // not ask for does not replay them.
    api.on('connect', () => {
      const creds = pendingLogin;
      pendingLogin = null;
      scheduleAutoLogin(creds);
    });

    // The header's World: field, which is \con with a button on it.
    const worldForm = document.getElementById('world-row');
    if (worldForm) {
      worldForm.addEventListener('submit', (event) => {
        event.preventDefault();       // never navigate; this is not a GET
        const field = document.getElementById('world-name');
        const parsed = parseWorldField(field.value);
        if (!parsed) {
          note(`*** Type a world name first. Saved: ${sessionList()}`);
          note(`    A new one takes an address: <handle> <host>:<port>`);
          return;
        }
        if (parsed.error) {
          note(`*** ${parsed.error}`);
          return;
        }
        // Straight through \con, so the field and the command cannot drift
        // apart on the origin rule, the auto-login or the error wording.
        handlers.connect(parsed);
        // Cleared, not left sitting there.  The field takes credentials --
        // "anything after the address is passed on untouched" -- and
        // refreshWorldUI only writes it when empty, so a typed password
        // stayed legible in the top bar for the rest of the session, in
        // screenshots and to anyone walking past.  The handle goes back in
        // on the next refresh.
        field.value = '';
        field.blur();                 // put the keyboard back on the game
        refreshWorldUI();
      });
    }

    // Arrived here from another world's page, which passed the handle it
    // was asked for. The credentials are read *here*, from this origin's
    // own storage -- the page we came from could not send them, and should
    // not have been able to.
    //
    // The socket already points at this world, since this page is the one
    // that serves it, so there is nothing to reconnect: this only has to
    // get the login sent.
    const asked = new URLSearchParams(location.search).get('session');
    if (asked) {
      // Consumed, so a reload does not silently log in again after someone
      // has deliberately disconnected.
      history.replaceState(null, '', location.pathname + location.hash);
      const arrived = sessions[asked];
      if (!arrived) {
        note(`*** Sent here for '${asked}', which is not saved on this page.`);
        note(`    Storage is per-world: ${PREFIX}con ${asked} <host> <port>`);
        note(`    [user] [pass] then ${PREFIX}save, and it will be next time.`);
      } else if (String(arrived.host).toLowerCase() !== location.hostname.toLowerCase()
                 || String(arrived.port) !== String(location.port)) {
        // ?session= arrives in a link, so it names *which* saved session to
        // replay.  Storage is per-origin, so a stranger cannot supply
        // credentials -- but without this they could choose which of your
        // own to send here: a link to this world carrying the handle of a
        // session saved for another one would hand this world that world's
        // password.  connectTo always navigates to a session's own
        // host:port, so a mismatch is never something the client itself
        // produced.
        note(`*** Sent here for '${asked}', which is saved for `
             + `${arrived.host}:${arrived.port}, not this world.`);
        note('    Not logging in with it.');
      } else {
        current = Object.assign({}, arrived, { handle: asked });
        if (arrived.username) {
          const creds = { username: arrived.username,
                          password: arrived.password };
          // Already up if the socket beat attach() to it; otherwise the
          // 'connect' listener registered above will take it.
          if (api.connected) scheduleAutoLogin(creds);
          else pendingLogin = creds;
        }
      }
    }

    refreshWorldUI();

    api.intercept((text) => {
      const line = text.trimStart();
      if (line.startsWith(PREFIX)) {
        runCommand(line.slice(PREFIX.length));
        return true;                       // never reaches the game
      }
      const expanded = expandAlias(text);
      if (expanded === null) return false;
      api.send(expanded);
      return true;                         // the original line is replaced
    });

    api.filterOutput(evalLine);
    api.on('gmcp', (msg) => evalGmcp(msg.package));

    // Speaking a reconnect's worth of backlog is not useful, and the
    // utterance queue outlives the page state that queued it.
    api.on('disconnect', () => {
      if (speechAvailable()) window.speechSynthesis.cancel();
    });
  },

  /** Exposed for the console and for tests. */
  get aliases() { return { ...aliases }; },
  get triggers() { return triggers.map((t) => ({ ...t })); },
};

})();
