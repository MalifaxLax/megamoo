/*
 * Lua script host — user code in a real Lua 5.4 VM (wasmoon).
 *
 * Why Lua is the one to hand a shared script pack: the VM starts with
 * only what we put in it.  There is no `fetch` to delete, no nested-worker
 * escape, no global object shared with the page — isolation is a property
 * of the interpreter rather than a blocklist somebody has to keep
 * correct.  The cost is ~420KB (interpreter + wasm), loaded lazily the
 * first time a Lua script actually runs, and no devtools view inside the
 * VM — which is why errors below carry a Lua traceback.
 *
 * Scripts see a `moo` table mirroring the JS host's `moo` object, so the
 * same logic ports between languages.
 */
(function () {
'use strict';

const VENDOR = 'vendor/wasmoon/';

let enginePromise = null;

/** Load wasmoon once, on first use. */
function loadEngine() {
  if (enginePromise) return enginePromise;
  enginePromise = new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.src = VENDOR + 'wasmoon.js';
    script.onload = () => {
      if (!window.wasmoon) {
        reject(new Error('wasmoon loaded but did not register'));
        return;
      }
      // The wasm sits next to the JS; be explicit rather than relying on
      // wasmoon's own resolution, which depends on document.currentScript
      // and breaks if the client is ever served from a nested path.
      resolve(new window.wasmoon.LuaFactory(VENDOR + 'glue.wasm'));
    };
    script.onerror = () => reject(new Error('failed to load ' + script.src));
    document.head.appendChild(script);
  });
  return enginePromise;
}

/**
 * Lua preamble.
 *
 * Installs the `moo` table over the host functions injected below, plus
 * the dispatcher the page calls into.  Written in Lua rather than built
 * from JS so handlers stay Lua values -- crossing the boundary per
 * registration would turn every trigger into a marshalling problem.
 */
const PRELUDE = `
-- Private handles taken before the standard library is trimmed below.
local traceback = debug.traceback
local os_time, os_date = os.time, os.date
local os_clock, os_difftime = os.clock, os.difftime

local handlers = {}
local events = {}
local next_ref = 1

local function store(fn)
  local ref = 'h' .. next_ref
  next_ref = next_ref + 1
  handlers[ref] = fn
  return ref
end

moo = {}

function moo.send(command)      return __call('send', {command = command}) end
function moo.echo(text)         return __call('echo', {text = tostring(text)}) end
function moo.connected()        return __call('connected', {}) end
function moo.grid_frame()       return __call('gridFrame', {}) end

function moo.send_gmcp(pkg, data)
  return __call('sendGmcp', {package = pkg, data = data or {}})
end

function moo.trigger(pattern, handler, opts)
  opts = opts or {}
  return __call('trigger', {
    pattern = pattern, ref = store(handler),
    regex = opts.regex or false, flags = opts.flags,
  })
end

function moo.alias(pattern, handler, opts)
  opts = opts or {}
  return __call('alias', {
    pattern = pattern, ref = store(handler),
    regex = opts.regex or false, flags = opts.flags,
  })
end

function moo.timer(ms, handler)
  return __call('timer', {ms = ms, ref = store(handler)})
end

function moo.cancel_timer(handle)
  return __call('cancelTimer', {handle = handle})
end

moo.storage = {
  get = function(key) return __call('storageGet', {key = key}) end,
  set = function(key, value) return __call('storageSet', {key = key, value = value}) end,
}

function moo.panel(id, spec)    return __call('panel', {id = id, spec = spec}) end
function moo.remove_panel(id)   return __call('removePanel', {id = id}) end

function moo.on(event, handler)
  events[event] = events[event] or {}
  table.insert(events[event], handler)
end

-- Called by the page for every client event. Errors are caught and
-- reported with a traceback: there is no devtools view inside the VM, so
-- an uncaught error here would vanish silently.
function __dispatch(event, payload)
  local function run(fn, ...)
    local ok, err = xpcall(fn, traceback, ...)
    if not ok then __error(tostring(err)) end
  end

  if (event == 'trigger' or event == 'alias') and payload and payload.ref then
    local fn = handlers[payload.ref]
    if fn then run(fn, payload.line, payload.captures) end
    return
  end

  if event == 'timer' and payload and payload.ref then
    local fn = handlers[payload.ref]
    if fn then run(fn, payload.handle) end
    return
  end

  for _, fn in ipairs(events[event] or {}) do
    run(fn, payload)
  end
end

-- Trim the standard library to what a game script legitimately needs.
--
-- None of these can reach the page or the network -- there is no JS
-- bridge in this VM -- but they are not free either: io and package
-- operate on the Emscripten virtual filesystem, and load/loadstring on a
-- malformed binary chunk is a well-known way to crash a Lua VM. Removing
-- them keeps the isolation argument for Lua an actual property rather
-- than a matter of what happens to be harmless in practice.
io = nil
package = nil
require = nil
dofile = nil
loadfile = nil
load = nil
loadstring = nil
collectgarbage = nil

-- The watchdog, installed before debug is taken away.
--
-- wasmoon runs this VM synchronously on the page's own thread, so a
-- script that loops forever freezes the whole client -- and because
-- saved scripts auto-run at load, a bad one re-freezes it on every
-- reload until storage is cleared. There is no way to interrupt
-- synchronous wasm from outside, so the interrupt has to come from
-- inside the VM.
--
-- A count hook fires every N virtual instructions; raising an error in
-- it unwinds the script the same way any runtime error would, and the
-- host reports it. sethook is captured into a local first, so the
-- budget survives debug being cleared below, and a script cannot reach
-- the hook to remove its own leash.
--
-- The budget is generous: 200 million instructions is far past any
-- honest script and still trips in well under a second of spinning.
local _sethook = debug.sethook
debug = nil

local function _watchdog()
  error('script stopped: it ran too long without finishing '
        .. '(possible infinite loop)', 2)
end

-- Re-armed at the start of every entry into the VM, not set once.
--
-- A count hook counts continuously, so setting it once would make this a
-- *lifetime* budget: a perfectly well-behaved script with a timer would
-- accumulate instructions over hours and eventually be killed for having
-- run a long time rather than for hanging. Re-arming per call makes it
-- what it should be -- a budget for one uninterrupted stretch of work.
function __rearm()
  _sethook(_watchdog, '', 200000000)
end

__rearm()
os = {time = os_time, date = os_date, clock = os_clock, difftime = os_difftime}
`;

const host = {
  id: 'lua',
  label: 'Lua',

  async create(scriptId, source, callbacks) {
    const factory = await loadEngine();
    const lua = await factory.createEngine();

    // The only doors out of the VM.
    lua.global.set('__call', (method, args) =>
      callbacks.call(method, args ? JSON.parse(JSON.stringify(args)) : {}));
    lua.global.set('__error', (message) => callbacks.error(String(message)));

    await lua.doString(PRELUDE);

    const rearm = lua.global.get('__rearm');

    try {
      if (rearm) rearm();
      await lua.doString(source);
    } catch (err) {
      callbacks.error(String(err));
    }

    const dispatch = lua.global.get('__dispatch');

    return {
      async dispatch(event, payload) {
        if (!dispatch) return;
        try {
          // Fresh budget per event -- a trigger that hangs must not be
          // charged for the work every earlier trigger did.
          if (rearm) rearm();
          await dispatch(event, payload);
        } catch (err) {
          callbacks.error(String(err));
        }
      },
      destroy() {
        try {
          lua.global.close();
        } catch (err) {
          console.warn('[megamoo] lua close failed:', err);
        }
      },
    };
  },
};

if (window.MegaMOOScripting) window.MegaMOOScripting.registerHost(host);

})();
