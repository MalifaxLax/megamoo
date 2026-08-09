/*
 * JavaScript script host — user code in a Web Worker.
 *
 * Sandbox honesty
 * ---------------
 * This is a *blocklist*, not a hard boundary.  The worker shares the
 * page's origin; what stops a script reaching the network is that the
 * relevant globals are deleted before user code runs.  Notably `Worker`
 * itself must go, or a script spawns a nested worker and gets a fresh
 * global with `fetch` restored — the classic escape from this pattern.
 *
 * That is enough for scripts you wrote yourself.  It is *not* enough for
 * scripts traded between players: a hostile one that finds a reference
 * this list missed can reach the game as the logged-in player.  For
 * shared script packs, prefer the Lua host, where isolation is a property
 * of the interpreter rather than a list somebody has to keep correct.
 *
 * The client says as much when a JS script is installed.
 */
(function () {
'use strict';

/**
 * Worker bootstrap, stringified into a blob.
 *
 * Runs before user code: strips the globals below, installs the `moo`
 * API, then evaluates the script.
 */
const BOOTSTRAP = `
'use strict';

// Order matters: Worker goes first. A nested worker would get a pristine
// global object with everything below restored, making the rest pointless.
for (const name of [
  'Worker', 'SharedWorker', 'ServiceWorker',
  'fetch', 'XMLHttpRequest', 'WebSocket', 'EventSource',
  'importScripts', 'indexedDB', 'caches', 'BroadcastChannel',
  'Notification', 'navigator', 'RTCPeerConnection',
]) {
  try { delete self[name]; } catch (e) { /* non-configurable: nothing to do */ }
  try {
    Object.defineProperty(self, name, {
      get() { throw new Error(name + ' is not available to scripts'); },
      configurable: false,
    });
  } catch (e) { /* already gone */ }
}

let nextCall = 1;
const pending = new Map();

/** Ask the page to do something on our behalf. */
function request(method, args) {
  const id = nextCall++;
  return new Promise((resolve, reject) => {
    pending.set(id, { resolve, reject });
    self.postMessage({ kind: 'call', id, method, args });
  });
}

const handlers = Object.create(null);
let nextRef = 1;

function storeHandler(fn) {
  const ref = 'h' + (nextRef++);
  handlers[ref] = fn;
  return ref;
}

// The API user code sees. Deliberately the same shape as the Lua host's
// \`moo\` table, so a script's logic ports between the two languages.
const moo = {
  send:      (command) => request('send', { command }),
  sendGmcp:  (pkg, data) => request('sendGmcp', { package: pkg, data }),
  echo:      (text) => request('echo', { text }),
  connected: () => request('connected', {}),
  gridFrame: () => request('gridFrame', {}),

  trigger(pattern, handler, opts) {
    return request('trigger', {
      pattern: pattern instanceof RegExp ? pattern.source : pattern,
      regex: pattern instanceof RegExp,
      flags: pattern instanceof RegExp ? pattern.flags : (opts && opts.flags),
      ref: storeHandler(handler),
    });
  },

  alias(pattern, handler, opts) {
    return request('alias', {
      pattern: pattern instanceof RegExp ? pattern.source : pattern,
      regex: pattern instanceof RegExp,
      flags: pattern instanceof RegExp ? pattern.flags : (opts && opts.flags),
      ref: storeHandler(handler),
    });
  },

  timer:       (ms, handler) => request('timer', { ms, ref: storeHandler(handler) }),
  cancelTimer: (handle) => request('cancelTimer', { handle }),

  storage: {
    get: (key) => request('storageGet', { key }),
    set: (key, value) => request('storageSet', { key, value }),
  },

  panel:       (id, spec) => request('panel', { id, spec }),
  removePanel: (id) => request('removePanel', { id }),

  /** Subscribe to a client event ('gmcp:Room.Info', 'connect', ...). */
  on(event, handler) {
    (moo._events[event] || (moo._events[event] = [])).push(handler);
  },
  _events: Object.create(null),
};

self.moo = moo;

self.onmessage = async (msg) => {
  const data = msg.data;

  if (data.kind === 'result') {
    const entry = pending.get(data.id);
    if (!entry) return;
    pending.delete(data.id);
    if (data.error) entry.reject(new Error(data.error));
    else entry.resolve(data.value);
    return;
  }

  if (data.kind === 'event') {
    const { event, payload } = data;
    try {
      // Trigger/alias/timer callbacks come back by reference.
      if ((event === 'trigger' || event === 'alias') && payload.ref) {
        const fn = handlers[payload.ref];
        if (fn) await fn(payload.line, payload.captures);
        return;
      }
      if (event === 'timer' && payload.ref) {
        const fn = handlers[payload.ref];
        if (fn) await fn(payload.handle);
        return;
      }
      for (const fn of moo._events[event] || []) await fn(payload);
    } catch (err) {
      self.postMessage({ kind: 'error', message: String(err && err.stack || err) });
    }
    return;
  }

  if (data.kind === 'source') {
    try {
      // Indirect eval: user code runs in global scope, so it cannot see
      // this bootstrap's locals (pending, handlers, ...).
      (0, eval)(data.source);
    } catch (err) {
      self.postMessage({ kind: 'error', message: String(err && err.stack || err) });
    }
  }
};
`;

const host = {
  id: 'js',
  label: 'JavaScript',

  async create(scriptId, source, callbacks) {
    const blob = new Blob([BOOTSTRAP], { type: 'application/javascript' });
    const url = URL.createObjectURL(blob);
    const worker = new Worker(url);
    // The blob is captured by the running worker; the URL itself is no
    // longer needed and would otherwise leak for the page's lifetime.
    URL.revokeObjectURL(url);

    worker.onmessage = async (msg) => {
      const data = msg.data;
      if (data.kind === 'call') {
        let value = null;
        let error = null;
        try {
          value = await callbacks.call(data.method, data.args);
        } catch (err) {
          error = String(err);
        }
        worker.postMessage({ kind: 'result', id: data.id, value, error });
        return;
      }
      if (data.kind === 'error') {
        callbacks.error(data.message);
      }
    };

    worker.onerror = (event) => {
      callbacks.error(event.message || 'worker error');
    };

    worker.postMessage({ kind: 'source', source });

    return {
      async dispatch(event, payload) {
        worker.postMessage({ kind: 'event', event, payload });
      },
      destroy() {
        worker.terminate();
      },
    };
  },
};

if (window.MegaMOOScripting) window.MegaMOOScripting.registerHost(host);

})();
