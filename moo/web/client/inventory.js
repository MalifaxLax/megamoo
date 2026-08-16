/*
 * Inventory — what the player is carrying, under the map.
 *
 * Fed by GMCP `Char.Inventory`, which the server sends after a command
 * only when the answer has changed. The engine has no opinion about what
 * inventory *is*: it asks the character's `inv_data` verb, so a world
 * that counts hands, or hands and worn items, or pockets, gets what it
 * describes. A world that defines no such verb sends nothing and this
 * panel never appears.
 *
 * It lives in the left column beneath the map, which is the reason that
 * column can be reserved at all: the scrollback gives up the width once,
 * and both readouts use it.
 *
 * Items nest. An item with a `contents` array is a container, drawn with a
 * disclosure triangle; without one it is a leaf. That is the whole wire
 * vocabulary, and it is enough for a pouch in a pack in a hand. A closed
 * chest simply sends no `contents` and reads as a leaf, which is exactly
 * what the player knows about it.
 */
(function () {
'use strict';

const panel = document.getElementById('inventory');
const list  = document.getElementById('inventory-list');

/* Which containers the player has folded shut, by objnum.
 *
 * The collapsed set rather than the expanded one, so the default is open:
 * a panel that starts folded is a panel showing nothing, and the reason to
 * open it is to see what is in there. Persisted, because refolding the
 * same pack after every reload is the sort of small annoyance that ends
 * with the panel switched off. */
const STORAGE_KEY = 'megamoo.inventory.collapsed';
const collapsed = new Set();

function loadCollapsed() {
  try {
    const raw = JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]');
    if (Array.isArray(raw)) for (const num of raw) collapsed.add(num);
  } catch {
    // A corrupt preference is not worth a broken panel; start open.
  }
}

function saveCollapsed() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(Array.from(collapsed)));
  } catch {
    // Storage full or blocked: keep running, just not remembered.
  }
}

/* Show or hide the panel. The column it sits in is reserved by the
 * stylesheet whether or not anything is showing, so there is nothing to
 * keep in step -- see client.css. */
function showPanel(visible) {
  if (!panel) return;
  panel.hidden = !visible;
}

/*
 * Whether the room the player is standing in is one the readouts belong
 * in at all -- in character, and not marked no_map.
 *
 * The same rule the map follows, for the same reason: the OOC lobby and
 * chargen are not the world, and a room the builder took off the map is a
 * room where the fiction says you should not have a tidy readout of your
 * surroundings. Two panels answering that question differently is worse
 * than either answer, so this one follows Room.Info rather than deciding
 * for itself.
 *
 * False until a Room.Info says otherwise: unknown is not a reason to show
 * something, and login sends one straight away.
 */
let roomAllows = false;

/*
 * The items last received, kept so a toggle or a room change can redraw
 * without waiting on the server.
 *
 * `null` until the first Char.Inventory, which is not the same as an
 * empty list: empty means the world says you are carrying nothing and is
 * worth showing, null means it has not said yet and there is nothing to
 * put on screen.
 */
let current = null;

/**
 * One item and, if it is an open container with anything in it, its
 * contents underneath.
 *
 * `depth` is a fuse, not a feature. Containers are objnums on the wire and
 * nothing stops a world from describing a bag inside itself; a cycle here
 * would hang the tab rather than misdraw a panel, so it stops.
 */
function renderItem(item, showWhere, depth) {
  const li = document.createElement('li');
  const row = document.createElement('div');
  row.className = 'inv-row';

  const kids = Array.isArray(item.contents) ? item.contents : null;
  const num = typeof item.num === 'number' ? item.num : null;
  const open = kids && kids.length && !(num !== null && collapsed.has(num));

  if (kids && kids.length && depth < 8) {
    const toggle = document.createElement('button');
    toggle.type = 'button';
    toggle.className = 'inv-toggle';
    toggle.textContent = open ? '▼' : '▶';
    toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    toggle.title = open ? 'Collapse' : 'Expand';
    toggle.addEventListener('click', () => {
      if (num === null) return;
      if (collapsed.has(num)) collapsed.delete(num);
      else collapsed.add(num);
      saveCollapsed();
      render(current);
    });
    row.appendChild(toggle);
  } else {
    const bullet = document.createElement('span');
    bullet.className = 'inv-bullet';
    bullet.textContent = '•';
    bullet.setAttribute('aria-hidden', 'true');
    row.appendChild(bullet);
  }

  // textContent throughout: these strings are object names, which players
  // choose, and this panel is not a place to start trusting them as markup.
  const name = document.createElement('span');
  name.textContent = item.name || '';
  row.appendChild(name);

  if (showWhere && item.where) {
    const where = document.createElement('span');
    where.className = 'inv-where';
    where.textContent = item.where;
    row.appendChild(where);
  }

  li.appendChild(row);

  if (open && depth < 8) {
    const sub = document.createElement('ul');
    sub.className = 'inv-children';
    for (const child of kids) sub.appendChild(renderItem(child, false, depth + 1));
    li.appendChild(sub);
  }

  return li;
}

function render(items) {
  current = items;
  list.textContent = '';
  if (!items.length) {
    const li = document.createElement('li');
    li.className = 'inv-empty';
    li.textContent = 'nothing';
    list.appendChild(li);
    return;
  }
  for (const item of items) list.appendChild(renderItem(item, true, 0));
}

const Inventory = {
  attach(api) {
    if (!panel || !list) return;
    loadCollapsed();

    api.on('gmcp:Char.Inventory', (payload) => {
      render((payload && Array.isArray(payload.items)) ? payload.items : []);
      showPanel(roomAllows);
    });

    // Room.Info decides only whether this is shown, never what is in it:
    // walking into the lobby does not empty your hands, and coming back
    // out should not need a command before the panel is right again.
    api.on('gmcp:Room.Info', (room) => {
      roomAllows = !!(room && room.ic && !room.no_map);
      showPanel(roomAllows && current !== null);
    });

    // Same reasoning as the map: once the socket is gone this is a picture
    // of what you *were* carrying. Hidden rather than emptied, so a
    // reconnect restores it the moment the server says anything.
    api.on('disconnect', () => showPanel(false));
  },
};

window.Inventory = Inventory;

})();
