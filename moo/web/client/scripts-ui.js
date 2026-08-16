/*
 * Script manager UI.
 *
 * Without this the scripting API is only reachable from devtools, which
 * is not a feature a player has.  Lists installed scripts, toggles and
 * deletes them, and edits one at a time.
 *
 * Everything here is trusted page code; script *source* is only ever put
 * into a textarea's value, never parsed or rendered as markup.
 */
(function () {
'use strict';

const Scripting = window.MegaMOOScripting;
if (!Scripting) return;

const dialog     = document.getElementById('scripts-dialog');
const openButton = document.getElementById('scripts-open');
const listEl     = document.getElementById('scripts-list');
const nameEl     = document.getElementById('script-name');
const langEl     = document.getElementById('script-language');
const sourceEl   = document.getElementById('script-source');
const warningEl  = document.getElementById('script-warning');
const saveButton = document.getElementById('script-save');
const newButton  = document.getElementById('script-new');

/** The script currently loaded in the editor, or null for a new one. */
let editingId = null;

/* =========================================================================
 * Language picker
 * ========================================================================= */

function fillLanguages() {
  langEl.replaceChildren(...Scripting.hosts.map((host) => {
    const option = document.createElement('option');
    option.value = host.id;
    option.textContent = host.label;
    return option;
  }));
  // Lua leads: its isolation is a property of the interpreter rather
  // than a maintained blocklist. It is not the safer choice in every
  // respect -- see updateWarning -- but it is on the axis that matters
  // for a script somebody else wrote.
  langEl.value = Scripting.hosts.some((h) => h.id === 'lua') ? 'lua'
    : (Scripting.hosts[0]?.id ?? '');
  updateWarning();
}

/**
 * Say plainly which sandbox the chosen language gets.
 *
 * The JS host's isolation is a maintained blocklist; Lua's is a property
 * of the interpreter.  A player about to paste in a script somebody sent
 * them deserves to know which one they are choosing.
 */
function updateWarning() {
  if (langEl.value === 'js') {
    warningEl.textContent =
      'JavaScript runs in a Worker with the network functions removed — '
      + 'but that is a blocklist, not a guarantee, and a script can still '
      + 'reach the network by other means. It cannot see your password or '
      + 'this page. For a script someone else wrote, prefer Lua.';
    warningEl.hidden = false;
  } else {
    // Lua is not silent. Its isolation is better -- a real interpreter
    // with no network and no DOM, rather than a blocklist -- but it runs
    // on the page's own thread, so a loop that never ends freezes the
    // whole client rather than a worker you can switch off. Saying only
    // "safe" was the reassurance that needed correcting: it is safer in
    // the way that matters for someone else's code, and worse in the one
    // way a player can actually be stuck.
    warningEl.textContent =
      'Lua runs in a real interpreter with no network and no access to '
      + 'this page — the safer choice for a script someone else wrote. '
      + 'It does run on the client\'s own thread, so a script that loops '
      + 'forever will freeze the client until you reload.';
    warningEl.hidden = false;
  }
}

langEl.addEventListener('change', updateWarning);

/* =========================================================================
 * List
 * ========================================================================= */

function renderList() {
  const records = Scripting.list();

  if (!records.length) {
    const empty = document.createElement('li');
    empty.className = 'scripts-empty';
    empty.textContent = 'No scripts yet.';
    listEl.replaceChildren(empty);
    return;
  }

  listEl.replaceChildren(...records.map((record) => {
    const li = document.createElement('li');
    li.className = 'scripts-item';
    if (record.id === editingId) li.classList.add('scripts-item--editing');

    const toggle = document.createElement('input');
    toggle.type = 'checkbox';
    toggle.checked = record.enabled !== false;
    toggle.title = 'Enabled';
    toggle.addEventListener('change', async () => {
      await Scripting.setEnabled(record.id, toggle.checked);
      renderList();
    });

    const name = document.createElement('button');
    name.type = 'button';
    name.className = 'scripts-item-name';
    name.textContent = record.name;
    name.addEventListener('click', () => edit(record.id));

    const lang = document.createElement('span');
    lang.className = 'scripts-item-lang';
    lang.textContent = record.language;

    const remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'scripts-item-remove';
    remove.textContent = 'Delete';
    remove.addEventListener('click', async () => {
      await Scripting.remove(record.id);
      if (editingId === record.id) startNew();
      renderList();
    });

    li.append(toggle, name, lang, remove);
    return li;
  }));
}

/* =========================================================================
 * Editor
 * ========================================================================= */

function edit(id) {
  const record = Scripting.list().find((r) => r.id === id);
  if (!record) return;
  editingId = record.id;
  nameEl.value = record.name;
  langEl.value = record.language;
  sourceEl.value = record.source;
  updateWarning();
  renderList();
}

function startNew() {
  editingId = null;
  nameEl.value = '';
  sourceEl.value = '';
  renderList();
}

saveButton.addEventListener('click', async () => {
  const source = sourceEl.value;
  if (!source.trim()) return;
  const id = await Scripting.put({
    id: editingId || undefined,
    name: nameEl.value.trim() || 'untitled',
    language: langEl.value,
    source,
  });
  editingId = id;
  renderList();
});

newButton.addEventListener('click', startNew);

/* =========================================================================
 * Open / close
 * ========================================================================= */

openButton.addEventListener('click', () => {
  fillLanguages();
  renderList();
  dialog.showModal();
});

// Typing in the dialog must not be stolen by the client's
// focus-the-command-line-on-any-keypress handler.
dialog.addEventListener('keydown', (event) => event.stopPropagation());

fillLanguages();

})();
