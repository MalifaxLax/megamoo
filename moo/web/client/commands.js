/*
 * Client commands — the backslash layer, ported from MegaTerm.
 *
 * A line beginning with `\` is the client's own, never the game's: it is
 * claimed before the socket sees it and answered locally.  The command
 * set and its spelling follow MegaTerm's (MegaMOO/Commands/) so muscle
 * memory carries between the native client and this one.
 *
 * Three of MegaTerm's could not port literally, because they assume a
 * native app with a session book and a telnet socket it can point
 * anywhere:
 *
 *   \connect   a browser cannot open telnet, and this page has exactly
 *              one game — it reconnects, and takes an optional WebSocket
 *              URL, restricted to this origin (see canRepoint below).
 *   \quit      there is no application to terminate; it disconnects.
 *   \save      aliases and triggers persist as they are set, so there is
 *   \default   nothing to save and no second session to choose between.
 *              Both are still recognised, and say so, rather than coming
 *              back as "unknown command" to someone with the habit.
 *
 * \edit is deliberately absent.  MegaTerm opens a verb in its own editor
 * over a channel this client does not have; it is a feature to build, not
 * a command to port.
 */
(function () {
'use strict';

/** Recognised at the start of an input line. Matches MegaTerm's default. */
const PREFIX = '\\';

const STORE_ALIASES = 'megamoo.aliases';
const STORE_TRIGGERS = 'megamoo.triggers';

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
 * May the socket be re-pointed at `url`?
 *
 * Only within this origin.  Everything arriving on the socket is trusted
 * *as markup* by the terminal — that is safe precisely because the server
 * at the other end is the one that escaped it.  A socket aimed somewhere
 * else is script execution on this page and a convincing fake password
 * prompt, and "type this to fix your connection" is an old trick.  The
 * cross-origin case that is legitimate — a page served from a CDN with
 * the game elsewhere — is configured once in the ?ws= query parameter at
 * load, where it is the deployment's decision rather than a typed one.
 */
function canRepoint(url) {
  try {
    const target = new URL(url);
    if (target.host === location.host) return true;
    return target.host === new URL(api.endpoint, location.href).host;
  } catch {
    return false;
  }
}

const handlers = {

  /* ---- connection ---- */

  connect(args) {
    const url = args[0];
    if (!url) {
      note('*** Reconnecting...');
      api.reconnect();
      return;
    }
    if (!/^wss?:\/\//i.test(url)) {
      note('*** A WebSocket URL is expected, starting ws:// or wss://.');
      note(`    Usage: ${PREFIX}connect [ws://host:port/ws]`);
      return;
    }
    if (!canRepoint(url)) {
      note('*** Refusing: that is a different host, and everything a socket');
      note('    sends is trusted as markup by this terminal. If you really');
      note('    mean to play elsewhere, reload the page with ?ws=<url>.');
      return;
    }
    note(`*** Connecting to ${url}...`);
    api.reconnect(url);
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
    note('*** Nothing to save: aliases and triggers are stored as you set them.');
  },

  default: function setDefault() {
    note('*** This client serves one game; there is no default session to set.');
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
    note(`  ${p}connect [wsUrl]              - Reconnect (this origin only)`);
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
  const canonical = { con: 'connect', def: 'default' }[name] || name;

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
    recompile();

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
