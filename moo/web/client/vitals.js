/*
 * Vitals — the bars at the foot of the left column.
 *
 * Fed by GMCP `Char.Vitals`, which the server sends after a command only
 * when the numbers have actually changed. The engine has no opinion about
 * what a vital is: it asks the character's `vitals_data` verb, so a world
 * that counts hits, or hits and mana, or blood and sanity, gets what it
 * describes. A world that defines no such verb sends nothing and this
 * panel never appears — the shipped starter is one of those.
 *
 * It sits at the *bottom* of the column rather than the top, under the map
 * and the inventory, which is where the 2003 client put it and is the
 * right place for a different reason too: the map and the inventory change
 * height as you walk and as you pick things up, and anything below them
 * would slide around. Anchored to the foot, the bars are always in the
 * same place, which is what you want from something you check mid-fight.
 */
(function () {
'use strict';

const panel = document.getElementById('vitals');
const list  = document.getElementById('vitals-list');

/**
 * Tones this client knows how to colour, as an allowlist.
 *
 * An allowlist rather than trusting the wire: `tone` arrives from a
 * world's own verb and is about to become a CSS class name. A world that
 * sends a tone this client has never heard of gets the default bar, which
 * is the same bargain the highlight vocabulary makes in commands.js.
 */
const TONES = { hits: 'vit-hits', stamina: 'vit-stamina',
                focus: 'vit-focus', mana: 'vit-mana' };

/* The last payload rendered, so a room change can redraw without waiting
 * on the server. `null` until the first Char.Vitals, which is not the same
 * as an empty list: empty means the world says this body has no pools and
 * is worth showing as nothing, null means it has not said yet. */
let current = null;

/* Whether the room the player is in is one the readouts belong in.
 *
 * The same rule the map and the inventory follow, from the same
 * Room.Info, so the three cannot disagree about whether you are in the
 * world. False until told otherwise. */
let roomAllows = false;

function showPanel(visible) {
  if (!panel) return;
  panel.hidden = !visible;
}

function render(vitals) {
  current = vitals;
  list.textContent = '';
  for (const stat of vitals) {
    const max = Number(stat.max);
    const value = Number(stat.value);
    // A bar with no scale cannot be drawn honestly at any length, so it
    // is skipped rather than guessed at. The server drops these too; this
    // is the client refusing to trust that it did.
    if (!isFinite(max) || max <= 0 || !isFinite(value)) continue;

    const row = document.createElement('li');
    row.className = 'vit-row';

    const label = document.createElement('span');
    label.className = 'vit-label';
    // textContent: a label is a world's string and this is not the place
    // to start trusting it as markup.
    label.textContent = String(stat.label == null ? '' : stat.label);
    row.appendChild(label);

    const track = document.createElement('div');
    track.className = 'vit-track';
    const fill = document.createElement('div');
    const tone = TONES[String(stat.tone)] || '';
    fill.className = 'vit-fill' + (tone ? ' ' + tone : '');
    const pct = Math.max(0, Math.min(100, (value / max) * 100));
    fill.style.width = pct.toFixed(1) + '%';
    track.appendChild(fill);
    row.appendChild(track);

    // The numbers go in the title rather than on screen: the column is
    // 184px wide and the bar is the reading. Trailing '.0' is dropped so
    // a whole number reads as one.
    const trim = (n) => (Math.round(n * 10) / 10).toString();
    row.title = `${label.textContent} ${trim(value)} / ${trim(max)}`;
    // Announced for a screen reader, which cannot see a coloured bar.
    track.setAttribute('role', 'progressbar');
    track.setAttribute('aria-valuenow', trim(value));
    track.setAttribute('aria-valuemin', '0');
    track.setAttribute('aria-valuemax', trim(max));
    track.setAttribute('aria-label', label.textContent);

    list.appendChild(row);
  }
}

const Vitals = {
  attach(api) {
    if (!panel || !list) return;

    api.on('gmcp:Char.Vitals', (payload) => {
      render((payload && Array.isArray(payload.vitals)) ? payload.vitals : []);
      showPanel(roomAllows);
    });

    // Room.Info decides only whether this is shown, never what is in it:
    // walking into the lobby does not change your hit points, and coming
    // back out should not need a command before the bars are right again.
    api.on('gmcp:Room.Info', (room) => {
      roomAllows = !!(room && room.ic && !room.no_map);
      showPanel(roomAllows && current !== null);
    });

    // Once the socket is gone these are a picture of how you *were*.
    // Hidden rather than emptied, so a reconnect restores them the moment
    // the server says anything.
    api.on('disconnect', () => showPanel(false));
  },
};

window.Vitals = Vitals;

})();
