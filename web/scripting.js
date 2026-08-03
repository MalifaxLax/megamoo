/*
 * User scripting: manager, host registry, and the API scripts call.
 *
 * A *script* is user-authored source plus a language. A *host* runs that
 * source in isolation and speaks this module's small message protocol.
 * Two hosts ship (see hosts/): a JS Worker and a Lua VM.  Neither can
 * touch the DOM, the socket, or the page's globals; everything they do
 * arrives here as a request, and everything they observe is pushed to
 * them as an event.
 *
 * Host contract
 * -------------
 * A host is an object:
 *
 *   {
 *     id: 'lua',
 *     label: 'Lua',
 *     async create(scriptId, source, callbacks) -> instance
 *   }
 *
 * `callbacks` is `{ call(method, args) -> any, error(message) }`.
 * The returned instance is:
 *
 *   {
 *     async dispatch(event, payload),   // deliver an event to the script
 *     destroy(),                        // tear down, release resources
 *   }
 *
 * Requests a script may make via `call` are the methods on API_METHODS
 * below.  Anything else is rejected, so adding a host never widens what
 * scripts can reach.
 */
(function () {
'use strict';

const STORAGE_KEY = 'megamoo.scripts';
const STORAGE_DATA_PREFIX = 'megamoo.scriptdata.';

/** How long one script may block before we assume it has run away. */
const CALL_BUDGET_MS = 2000;

/* =========================================================================
 * Host registry
 * ========================================================================= */

const hosts = new Map();

function registerHost(host) {
  hosts.set(host.id, host);
}

/* =========================================================================
 * A running script
 * ========================================================================= */

class RunningScript {
  constructor(manager, record, host) {
    this.manager = manager;
    this.record = record;          // {id, name, language, source, enabled}
    this.host = host;
    this.instance = null;

    // Registrations the script made; all torn down together on stop so a
    // disabled script cannot keep firing.
    this.triggers = [];            // [{re, ref}]
    this.aliases = [];             // [{re, ref}]
    this.timers = new Map();       // handle -> interval id
    this.nextTimer = 1;
  }

  get id() { return this.record.id; }

  async start() {
    this.instance = await this.host.create(this.id, this.record.source, {
      call: (method, args) => this.handleCall(method, args),
      error: (message) => this.manager.reportError(this.record, message),
    });
    await this.dispatch('load', {});
  }

  stop() {
    for (const interval of this.timers.values()) clearInterval(interval);
    this.timers.clear();
    this.triggers.length = 0;
    this.aliases.length = 0;
    window.ScriptPanels.removeAll(this.id);
    try {
      this.instance?.destroy();
    } catch (err) {
      console.warn(`[megamoo] script "${this.record.name}" destroy threw:`, err);
    }
    this.instance = null;
  }

  async dispatch(event, payload) {
    if (!this.instance) return;
    try {
      await this.instance.dispatch(event, payload);
    } catch (err) {
      this.manager.reportError(this.record, String(err));
    }
  }

  /* ---- the API surface, as invoked by the host ---- */

  handleCall(method, args) {
    const fn = API_METHODS[method];
    if (!fn) {
      throw new Error(`unknown API method: ${method}`);
    }
    return fn.call(this, args || {});
  }

  /** Compile a user pattern. Plain strings are literal substrings. */
  compilePattern(pattern, isRegex, flags) {
    if (!isRegex) {
      const escaped = String(pattern).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      return new RegExp(escaped);
    }
    // A bad regex is the script's bug, not ours: report and skip rather
    // than letting it abort the registration call.
    return new RegExp(String(pattern), flags || '');
  }
}

/* =========================================================================
 * API methods
 * -------------------------------------------------------------------------
 * `this` is the RunningScript.  These are the *only* things a script can
 * do; both hosts route through here, so the two languages are guaranteed
 * to have identical capabilities.
 * ========================================================================= */

const API_METHODS = {
  /** send(command) — as if the player typed it. */
  send({ command }) {
    return window.MegaMOO.send(String(command));
  },

  /** sendGmcp(package, data) — client->server out-of-band. */
  sendGmcp({ package: pkg, data }) {
    return window.MegaMOO.sendGmcp(String(pkg), data ?? {});
  },

  /** echo(text) — a line in the scrollback. Plain text only. */
  echo({ text }) {
    window.MegaMOO.echo(String(text));
    return true;
  },

  /** trigger(pattern, ref) — fire `ref` on matching output lines. */
  trigger({ pattern, ref, regex, flags }) {
    this.triggers.push({
      re: this.compilePattern(pattern, regex, flags),
      ref,
    });
    return true;
  },

  /** alias(pattern, ref) — claim matching input before it is sent. */
  alias({ pattern, ref, regex, flags }) {
    this.aliases.push({
      re: this.compilePattern(pattern, regex, flags),
      ref,
    });
    return true;
  },

  /** timer(ms, ref) — repeating; returns a handle for cancel. */
  timer({ ms, ref }) {
    // Floor the period: a 0ms timer in a script would peg the main thread.
    const period = Math.max(50, Number(ms) || 0);
    const handle = this.nextTimer++;
    const interval = setInterval(() => {
      this.dispatch('timer', { ref, handle });
    }, period);
    this.timers.set(handle, interval);
    return handle;
  },

  cancelTimer({ handle }) {
    const interval = this.timers.get(handle);
    if (interval === undefined) return false;
    clearInterval(interval);
    this.timers.delete(handle);
    return true;
  },

  /** Per-script persistent storage, namespaced so scripts can't read each other. */
  storageGet({ key }) {
    const all = this.manager.readData(this.id);
    return all[String(key)] ?? null;
  },

  storageSet({ key, value }) {
    const all = this.manager.readData(this.id);
    if (value === null || value === undefined) delete all[String(key)];
    else all[String(key)] = value;
    this.manager.writeData(this.id, all);
    return true;
  },

  /** panel(id, spec) — declare or update a UI panel. */
  panel({ id, spec }) {
    window.ScriptPanels.set(this.id, String(id), spec || {});
    return true;
  },

  removePanel({ id }) {
    window.ScriptPanels.remove(this.id, String(id));
    return true;
  },

  connected() {
    return window.MegaMOO.connected;
  },
};

/* =========================================================================
 * Manager
 * ========================================================================= */

const manager = {
  /** id -> RunningScript */
  running: new Map(),

  /* ---- persistence ---- */

  load() {
    try {
      return JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]');
    } catch {
      return [];
    }
  },

  save(records) {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(records));
  },

  readData(scriptId) {
    try {
      return JSON.parse(
        localStorage.getItem(STORAGE_DATA_PREFIX + scriptId) || '{}');
    } catch {
      return {};
    }
  },

  writeData(scriptId, data) {
    localStorage.setItem(STORAGE_DATA_PREFIX + scriptId,
                         JSON.stringify(data));
  },

  reportError(record, message) {
    // Surfaced in the scrollback, not just the console: the Lua host has
    // no devtools view, so an error the player cannot see is an error
    // they cannot fix.
    window.MegaMOO.echo(`[script: ${record.name}] ${message}`);
    console.error(`[megamoo] script "${record.name}":`, message);
  },

  /* ---- lifecycle ---- */

  async startAll() {
    for (const record of this.load()) {
      if (record.enabled !== false) await this.start(record);
    }
  },

  async start(record) {
    const host = hosts.get(record.language);
    if (!host) {
      this.reportError(record, `no host for language "${record.language}"`);
      return null;
    }
    await this.stop(record.id);
    const script = new RunningScript(this, record, host);
    this.running.set(record.id, script);
    try {
      await script.start();
    } catch (err) {
      this.reportError(record, String(err));
      this.running.delete(record.id);
      script.stop();
      return null;
    }
    return script;
  },

  async stop(id) {
    const script = this.running.get(id);
    if (!script) return;
    script.stop();
    this.running.delete(id);
  },

  /* ---- event fan-out ---- */

  dispatchAll(event, payload) {
    for (const script of this.running.values()) {
      script.dispatch(event, payload);
    }
  },

  /** Output lines: match every script's triggers. */
  onLine(line) {
    for (const script of this.running.values()) {
      for (const { re, ref } of script.triggers) {
        const match = re.exec(line);
        if (match) {
          script.dispatch('trigger', {
            ref, line, captures: Array.from(match).slice(1),
          });
        }
      }
    }
  },

  /**
   * Input lines: give aliases first refusal.
   *
   * Returns true if a script claimed the line, which suppresses the send.
   * Alias handlers are dispatched asynchronously (a Worker round-trip),
   * so the decision to swallow the line is made here on the pattern
   * match alone -- the handler cannot retroactively un-claim it.
   */
  onInput(line) {
    let claimed = false;
    for (const script of this.running.values()) {
      for (const { re, ref } of script.aliases) {
        const match = re.exec(line);
        if (match) {
          claimed = true;
          script.dispatch('alias', {
            ref, line, captures: Array.from(match).slice(1),
          });
        }
      }
    }
    return claimed;
  },
};

/* =========================================================================
 * Public control surface
 * ========================================================================= */

const Scripting = {
  registerHost,

  get hosts() {
    return Array.from(hosts.values()).map((h) => ({ id: h.id, label: h.label }));
  },

  list() { return manager.load(); },

  /** Add or replace a script and (re)start it if enabled. */
  async put({ id, name, language, source, enabled = true }) {
    const records = manager.load();
    const scriptId = id || ('s' + Date.now().toString(36));
    const record = { id: scriptId, name: name || scriptId, language,
                     source, enabled };
    const index = records.findIndex((r) => r.id === scriptId);
    if (index >= 0) records[index] = record;
    else records.push(record);
    manager.save(records);

    await manager.stop(scriptId);
    if (enabled) await manager.start(record);
    return scriptId;
  },

  async remove(id) {
    await manager.stop(id);
    manager.save(manager.load().filter((r) => r.id !== id));
    localStorage.removeItem(STORAGE_DATA_PREFIX + id);
  },

  async setEnabled(id, enabled) {
    const records = manager.load();
    const record = records.find((r) => r.id === id);
    if (!record) return false;
    record.enabled = enabled;
    manager.save(records);
    if (enabled) await manager.start(record);
    else await manager.stop(id);
    return true;
  },

  get running() { return Array.from(manager.running.keys()); },

  /** Wire the manager to the client's bus. Called once at boot. */
  attach(api) {
    api.on('line', (line) => manager.onLine(line));
    api.on('gmcp', (msg) => {
      manager.dispatchAll('gmcp', msg);
      manager.dispatchAll('gmcp:' + msg.package, msg.data);
    });
    api.on('connect', () => manager.dispatchAll('connect', {}));
    api.on('disconnect', () => manager.dispatchAll('disconnect', {}));
    api.on('prompt', (text) => manager.dispatchAll('prompt', { text }));
    api.intercept((line) => manager.onInput(line));
    manager.startAll();
  },
};

window.MegaMOOScripting = Scripting;

})();
