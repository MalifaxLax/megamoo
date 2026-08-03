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
  // Lua leads: it is the one safe to run somebody else's script in.
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
      'JavaScript runs in a locked-down Worker — network access is removed, '
      + 'but the isolation is a blocklist, not a guarantee. For a script '
      + 'someone else wrote, prefer Lua.';
    warningEl.hidden = false;
  } else {
    warningEl.hidden = true;
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
