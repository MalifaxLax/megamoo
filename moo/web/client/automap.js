/*
 * Automap — a graphical map of the world, drawn in the corner.
 *
 * The server sends `Room.Info` with the room's objnum on every move.  It
 * does *not* say where the exits lead (see moo/builtins.py), so this maps
 * only what the player has actually walked: each arrival links the room
 * they left to the room they entered, in the direction they went.  Exits
 * that have never been used are drawn as short stubs — a visible frontier
 * rather than a guess.
 *
 * Room identity is exact (the objnum), so unlike a dead-reckoning
 * automapper this never confuses two rooms that share a name, and a loop
 * that returns somewhere already mapped closes correctly.
 *
 * Layout is a plane: each direction moves one cell. Real MUD geography is
 * not euclidean, so two rooms can compete for a cell; the later one is
 * nudged to the nearest free cell and its link line simply runs further.
 * Up/down/in/out have no planar offset and are drawn as badges instead.
 */
(function () {
'use strict';

/* =========================================================================
 * Directions
 * ========================================================================= */

/** Planar offsets. Keys are canonical direction names. */
const OFFSETS = {
  north: [0, -1], south: [0, 1], east: [1, 0], west: [-1, 0],
  ne: [1, -1], nw: [-1, -1], se: [1, 1], sw: [-1, 1],
};

/** Directions with no planar offset; shown as badges on the room. */
const VERTICAL = { u: '↑', d: '↓', in: '·', o: '·' };

/**
 * Every spelling the game accepts, mapped to its canonical name.
 * Mirrors moo verbs/16/go.py, which takes both full names and the
 * abbreviations in #15's `dnames`.
 */
const ALIASES = {
  n: 'north', north: 'north',
  s: 'south', south: 'south',
  e: 'east', east: 'east',
  w: 'west', west: 'west',
  ne: 'ne', northeast: 'ne',
  nw: 'nw', northwest: 'nw',
  se: 'se', southeast: 'se',
  sw: 'sw', southwest: 'sw',
  u: 'u', up: 'u',
  d: 'd', down: 'd',
  o: 'o', out: 'o',
  in: 'in',
};

/** Canonical direction for an input line, or null if it isn't movement. */
function directionOf(line) {
  const text = String(line).trim().toLowerCase();
  const word = text.startsWith('go ') ? text.slice(3).trim() : text;
  return ALIASES[word] || null;
}

/**
 * Direction implied by two rooms' canonical positions, if they adjoin.
 *
 * Reading the direction off the player's input only works when the input
 * *is* a direction. It isn't when they repeat with `.`, when a script
 * sends the move, or when they leave through a named exit object. This
 * covers all of those, because the layout is built from the exit graph:
 * two rooms one cell apart are one cell apart *precisely because* an exit
 * joins them in that direction.
 *
 * Only immediate neighbours qualify. Anything further apart was a
 * teleport or a portal rather than a step, and inventing a link for it
 * would draw a corridor that nobody can walk.
 */
function directionBetween(from, to) {
  if (!from || !to) return null;
  const dx = to.x - from.x;
  const dy = to.y - from.y;
  const dz = (to.z || 0) - (from.z || 0);

  if (dz !== 0) {
    // A staircase: only when it is a pure vertical step.
    if (dx === 0 && dy === 0 && Math.abs(dz) === 1) return dz > 0 ? 'u' : 'd';
    return null;
  }
  if (Math.abs(dx) > 1 || Math.abs(dy) > 1 || (dx === 0 && dy === 0)) {
    return null;
  }
  for (const [name, offset] of Object.entries(OFFSETS)) {
    if (offset[0] === dx && offset[1] === dy) return name;
  }
  return null;
}

/* =========================================================================
 * The graph
 * ========================================================================= */

const STORAGE_KEY = 'megamoo.automap';

const map = {
  /** num -> {num, name, exits:[dir], x, y} */
  rooms: new Map(),
  /** "from>to" -> direction */
  links: new Map(),

  load() {
    try {
      const raw = JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null');
      if (!raw) return;
      // Only IC rooms belong on the map. Anything stored before that rule
      // existed lacks the flag and is dropped here, so an old map cleans
      // itself up rather than keeping OOC rooms around forever.
      for (const room of raw.rooms || []) {
        if (room.ic) this.rooms.set(room.num, room);
      }
      for (const [key, dir] of raw.links || []) {
        const [from, to] = key.split('>').map(Number);
        if (this.rooms.has(from) && this.rooms.has(to)) {
          this.links.set(key, dir);
        }
      }
    } catch {
      // A corrupt map is not worth a broken client; start fresh.
    }
  },

  save() {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({
        rooms: Array.from(this.rooms.values()),
        links: Array.from(this.links.entries()),
      }));
    } catch {
      // Quota exceeded on a very large map: keep running, just unsaved.
    }
  },

  occupant(x, y, z = 0) {
    for (const room of this.rooms.values()) {
      if (room.x === x && room.y === y && (room.z || 0) === z) return room;
    }
    return null;
  },

  /**
   * Find a free cell at or near (x, y).
   *
   * MUD geography loops and folds, so the cell a direction points at is
   * often already taken by an unrelated room. Rather than stacking them
   * invisibly, spiral outward for space — the link line stretches, which
   * reads as "the world bends here" instead of hiding a room.
   */
  freeCell(x, y) {
    if (!this.occupant(x, y)) return [x, y];
    for (let radius = 1; radius <= 6; radius++) {
      for (let dx = -radius; dx <= radius; dx++) {
        for (let dy = -radius; dy <= radius; dy++) {
          if (Math.abs(dx) !== radius && Math.abs(dy) !== radius) continue;
          if (!this.occupant(x + dx, y + dy)) return [x + dx, y + dy];
        }
      }
    }
    return [x, y];      // give up and overlap rather than loop forever
  },

  /**
   * Record an arrival; returns the room record.
   *
   * `coords` is the server's canonical position for this room, derived
   * once from the exit graph (moo/roommap.py). When present it always
   * wins: it is the same for every player, it already resolved the
   * collisions a looping map creates, and it carries a real z level.
   * The path-based placement below is the fallback for a server that
   * does not send it.
   */
  visit(num, name, exits, fromNum, direction, coords) {
    let room = this.rooms.get(num);

    if (!room) {
      room = { num, name, exits: exits || [], x: 0, y: 0, z: 0, ic: true };
      this.rooms.set(num, room);
      if (!coords) this.placeByPath(room, fromNum, direction);
    } else {
      // Names and exits can change (a door opens); keep them current.
      room.name = name;
      room.exits = exits || room.exits;
    }

    if (coords) {
      room.x = coords[0];
      room.y = coords[1];
      room.z = coords[2] || 0;
      room.exact = true;
    }

    if (fromNum != null && fromNum !== num && direction) {
      this.links.set(fromNum + '>' + num, direction);
    }
    return room;
  },

  /** Fallback layout: step one cell from where we came from. */
  placeByPath(room, fromNum, direction) {
    const from = fromNum != null ? this.rooms.get(fromNum) : null;
    let x = 0;
    let y = 0;
    if (from && direction && OFFSETS[direction]) {
      const [dx, dy] = OFFSETS[direction];
      [x, y] = this.freeCell(from.x + dx, from.y + dy);
    } else if (from) {
      // Arrived without a planar direction (up, a portal, a teleport):
      // park it next to where we came from rather than on the origin.
      [x, y] = this.freeCell(from.x, from.y + 1);
    } else if (this.rooms.size > 1) {
      [x, y] = this.freeCell(0, 0);
    }
    room.x = x;
    room.y = y;
    room.z = from ? (from.z || 0) : 0;
  },

  clear() {
    this.rooms.clear();
    this.links.clear();
    localStorage.removeItem(STORAGE_KEY);
  },
};

/* =========================================================================
 * Rendering
 * ========================================================================= */

const panel  = document.getElementById('automap');

/* Showing the map reserves a column for it in the scrollback, so game text
 * stops running underneath it. Every place that shows or hides the panel
 * goes through here, so the two cannot get out of step -- a reserved column
 * with no map in it is a stripe of wasted width, and a map with no column
 * is text hidden behind a box. */
function showPanel(visible) {
  panel.hidden = !visible;
  const back = document.getElementById('scrollback');
  // The column belongs to whichever readout is showing, so it stays
  // reserved while either does -- the mirror of the test in inventory.js.
  // Both panels follow the same room rule and so normally appear and go
  // together, but "normally" is how a stripe of dead space, or a line of
  // text under a panel, survives a refactor.
  const inv = document.getElementById('inventory');
  const wanted = visible || (inv && !inv.hidden);
  if (back) back.classList.toggle('has-map', !!wanted);
}
const canvas = document.getElementById('automap-canvas');
const label  = document.getElementById('automap-room');
const ctx    = canvas.getContext('2d');

const CELL = 34;            // backing-store pixels per grid cell
const VIEW_W = 9;           // cells shown across
const VIEW_H = 7;           // cells shown down
const ROOM = 18;            // room box size within a cell

/**
 * Link lengths, in cells, and how each is drawn.
 *
 * A grid cannot embed the world exactly, so connections come in three
 * kinds and conflating them is what makes a map unreadable:
 *
 *   1 cell        real adjacency        solid line
 *   2-3 cells     stretched by layout   dashed, dimmer
 *   beyond        different area        a stub at each end
 *
 * Drawing a stretched link solid claims a corridor that isn't there;
 * drawing it not at all leaves rooms looking severed from a map they are
 * genuinely part of. Dashed says "connected, but the geometry here is
 * approximate", which is the truth.
 */
const ADJACENT = 1;
const STRETCHED_MAX = 3;

/**
 * How far a link stops short of a room's centre, as a fraction of a cell.
 *
 * Lines are drawn between room edges rather than centres. Centre-to-centre
 * lines all converge on the middle of each box, and where a room has
 * exits in eight directions that convergence is a knot — most of it
 * hidden under the box, the rest reading as scribble in the gaps.
 */
const LINK_INSET = 0.30;

canvas.width = CELL * VIEW_W;
canvas.height = CELL * VIEW_H;

const COLORS = {
  bg:       '#08090b',
  room:     '#2f3742',
  roomEdge: '#4a5563',
  visited:  '#3d4a5a',
  current:  '#d9a441',
  link:     '#55606f',
  farLink:  '#4a5262',   // a connection whose other end is off somewhere else
  stub:     '#39424e',
  text:     '#0c0e11',
};

/** Current room number, or null before the first Room.Info. */
let currentNum = null;

function draw() {
  ctx.fillStyle = COLORS.bg;
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  const here = currentNum != null ? map.rooms.get(currentNum) : null;
  if (!here) return;

  // One level at a time: with real z coordinates, stacked floors would
  // otherwise draw on top of each other.
  const level = here.z || 0;
  const onLevel = (room) => (room.z || 0) === level;

  // Centre the view on the current room.
  const originX = here.x - Math.floor(VIEW_W / 2);
  const originY = here.y - Math.floor(VIEW_H / 2);
  const px = (x) => (x - originX) * CELL + CELL / 2;
  const py = (y) => (y - originY) * CELL + CELL / 2;

  // --- links, under the rooms ---
  // Only cells near the viewport are worth drawing. A room far outside it
  // is culled below, but its *links* are not bounded by the canvas: a
  // corridor joining two areas the layout placed twenty cells apart would
  // otherwise drag a full-length line straight across the panel.
  const inView = (room) =>
    room.x >= originX - 1 && room.x <= originX + VIEW_W &&
    room.y >= originY - 1 && room.y <= originY + VIEW_H;

  ctx.lineWidth = 2;
  for (const [key, direction] of map.links.entries()) {
    const [fromNum, toNum] = key.split('>').map(Number);
    const from = map.rooms.get(fromNum);
    const to = map.rooms.get(toNum);
    if (!from || !to) continue;
    // A stair between floors has no line to draw on either floor; the
    // room's up/down badge is what marks it.
    if (!onLevel(from) || !onLevel(to)) continue;
    if (!inView(from) && !inView(to)) continue;

    const span = Math.max(Math.abs(to.x - from.x), Math.abs(to.y - from.y));
    if (span <= STRETCHED_MAX) {
      // Edge to edge, not centre to centre: leaves the box faces clean
      // and keeps eight exits from converging into a scribble.
      const ax = px(from.x);
      const ay = py(from.y);
      const bx = px(to.x);
      const by = py(to.y);
      const length = Math.hypot(bx - ax, by - ay) || 1;
      const ix = ((bx - ax) / length) * CELL * LINK_INSET;
      const iy = ((by - ay) / length) * CELL * LINK_INSET;

      const stretched = span > ADJACENT;
      ctx.strokeStyle = stretched ? COLORS.farLink : COLORS.link;
      ctx.setLineDash(stretched ? [3, 3] : []);
      ctx.beginPath();
      ctx.moveTo(ax + ix, ay + iy);
      ctx.lineTo(bx - ix, by - iy);
      ctx.stroke();
      ctx.setLineDash([]);       // stubs below must not inherit the dash
      continue;
    }

    // Too far to draw honestly as a straight line. Mark it at whichever
    // end is on screen with a stub pointing the way, so the connection
    // still reads without a wire crossing everything between.
    ctx.strokeStyle = COLORS.farLink;
    for (const [near, far] of [[from, to], [to, from]]) {
      if (!inView(near)) continue;
      const offset = OFFSETS[direction];
      // Point along the exit if it has a compass meaning, otherwise
      // straight at wherever the other room ended up.
      let ux;
      let uy;
      if (near === from && offset) {
        [ux, uy] = offset;
      } else {
        const dx = far.x - near.x;
        const dy = far.y - near.y;
        const length = Math.hypot(dx, dy) || 1;
        ux = dx / length;
        uy = dy / length;
      }
      ctx.beginPath();
      ctx.moveTo(px(near.x), py(near.y));
      ctx.lineTo(px(near.x) + ux * CELL * 0.44,
                 py(near.y) + uy * CELL * 0.44);
      ctx.stroke();
    }
  }

  // --- unexplored exits, as stubs ---
  ctx.strokeStyle = COLORS.stub;
  ctx.lineWidth = 2;
  for (const room of map.rooms.values()) {
    if (!onLevel(room)) continue;
    for (const rawDir of room.exits) {
      const dir = ALIASES[String(rawDir).toLowerCase()];
      const offset = dir && OFFSETS[dir];
      if (!offset) continue;
      // Skip exits we have already walked; those are drawn as links.
      const walked = Array.from(map.links.entries()).some(
        ([key, d]) => d === dir && Number(key.split('>')[0]) === room.num);
      if (walked) continue;
      const [dx, dy] = offset;
      ctx.beginPath();
      ctx.moveTo(px(room.x), py(room.y));
      ctx.lineTo(px(room.x) + dx * CELL * 0.38,
                 py(room.y) + dy * CELL * 0.38);
      ctx.stroke();
    }
  }

  // --- rooms ---
  for (const room of map.rooms.values()) {
    if (!onLevel(room)) continue;
    const x = px(room.x) - ROOM / 2;
    const y = py(room.y) - ROOM / 2;
    if (x < -ROOM || y < -ROOM ||
        x > canvas.width || y > canvas.height) continue;

    const isHere = room.num === currentNum;
    ctx.fillStyle = isHere ? COLORS.current : COLORS.room;
    ctx.fillRect(x, y, ROOM, ROOM);
    ctx.strokeStyle = isHere ? COLORS.current : COLORS.roomEdge;
    ctx.lineWidth = 1;
    ctx.strokeRect(x + 0.5, y + 0.5, ROOM - 1, ROOM - 1);

    // Up/down/in/out have nowhere to go on a plane; badge them instead.
    const badges = room.exits
      .map((d) => VERTICAL[ALIASES[String(d).toLowerCase()]])
      .filter(Boolean);
    if (badges.length) {
      ctx.fillStyle = isHere ? COLORS.text : COLORS.roomEdge;
      ctx.font = '9px ui-monospace, Menlo, monospace';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(Array.from(new Set(badges)).join(''),
                   x + ROOM / 2, y + ROOM / 2);
    }
  }
}

/* =========================================================================
 * Wiring
 * ========================================================================= */

/**
 * The direction of the move in progress.
 *
 * Set when the player submits a movement command and consumed by the
 * next Room.Info.  Arriving any other way (a portal, a teleport) leaves
 * it null, and the room is added unlinked rather than wrongly joined to
 * wherever we happened to be.
 */
let pendingDirection = null;
let previousNum = null;

/**
 * The last command that wasn't `.`, mirroring the server's `last_command`.
 *
 * `.` repeats the previous command, and the expansion happens server-side
 * (see the command loop in moo/web/connection.py), so the client only
 * ever sees the dot. Tracking the same thing here keeps a repeated
 * movement recognisable as movement. Like the server, `.` itself never
 * becomes the remembered command.
 */
let lastCommand = '';

const Automap = {
  attach(api) {
    map.load();

    api.on('input', (line) => {
      const text = String(line).trim();
      if (!text) return;
      const effective = text === '.' ? lastCommand : text;
      if (text !== '.') lastCommand = text;
      const dir = directionOf(effective);
      if (dir) pendingDirection = dir;
    });

    // A map is a picture of where you are. Once the socket is gone it is a
    // picture of where you were, and it should not sit there over a dead
    // connection claiming otherwise.
    //
    // Hidden rather than cleared: the rooms already walked are saved, and
    // a dropped connection reconnects on its own. Forgetting the map every
    // time the wifi blinked would throw away real exploration for nothing
    // -- that is what the reset button is for. The next Room.Info brings
    // the panel straight back.
    api.on('disconnect', () => {
      showPanel(false);
      previousNum = null;   // never draw a link across the gap
    });

    api.on('gmcp:Room.Info', (room) => {
      if (!room || room.num == null) return;   // older server: no identity
      let direction = pendingDirection;
      pendingDirection = null;

      // Two kinds of room are not part of the world map, and they are
      // handled the same way.
      //
      // Out-of-character rooms -- the entry hall, chargen -- because they
      // are not in the world. And rooms the builder marked `no_map`: a
      // maze meant to disorient, a vehicle interior, anywhere a tidy
      // coordinate grid would tell the player something the fiction says
      // they should not know. Those are in character; they simply decline
      // to be drawn.
      //
      // Nothing about either is recorded, and the panel goes away while
      // you are in one. previousNum is cleared too, so walking IC -> OOC
      // -> IC (or in and out of a maze) does not fabricate a link between
      // two rooms that are not connected. The next mappable room starts a
      // fresh trail.
      if (!room.ic || room.no_map) {
        previousNum = null;
        currentNum = null;
        showPanel(false);
        return;
      }

      // No usable direction from the input? Derive it from where the two
      // rooms sit, which covers `.`, scripted moves and named exits alike.
      if (!direction && room.coords && previousNum != null) {
        direction = directionBetween(map.rooms.get(previousNum), {
          x: room.coords[0], y: room.coords[1], z: room.coords[2] || 0,
        });
      }

      const record = map.visit(room.num, room.name || '', room.exits,
                               previousNum, direction, room.coords);
      previousNum = room.num;
      currentNum = room.num;

      // Name the level only when there is more than one, so a flat world
      // never carries a pointless "level 0".
      const levels = new Set(
        Array.from(map.rooms.values()).map((r) => r.z || 0));
      label.textContent = levels.size > 1
        ? `${record.name}  ·  level ${record.z || 0}`
        : record.name;
      showPanel(true);
      map.save();
      draw();
    });

  },

  /** Forget the map (exposed for the UI button and for scripts). */
  reset() {
    map.clear();
    previousNum = null;
    currentNum = null;
    showPanel(false);
  },

  get rooms() { return map.rooms.size; },
};

document.getElementById('automap-reset')
  .addEventListener('click', () => Automap.reset());

window.Automap = Automap;

})();
