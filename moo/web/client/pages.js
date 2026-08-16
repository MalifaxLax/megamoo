/*
 * Client.Page — a full-window page pushed by verb code.
 *
 * The readouts reserve 212px down the left, which is right for a
 * conversation and wrong for a wide table: a training screen laid out
 * against a terminal's character cell has nowhere to go. A <dialog>
 * spans the whole window, so the column stops mattering rather than
 * having to be negotiated with.
 *
 * Pushed, not pulled. Char.Inventory and Char.Vitals are asked for by the
 * engine after every command; this arrives only when a verb decides to
 * show something, which is why there is no "changed since last time"
 * check here -- every frame was sent on purpose.
 *
 * WHAT THE WORLD MAY SEND. Widgets, from the vocabulary in panels.js --
 * never HTML. Rendering goes through ScriptPanels.renderInto so there is
 * exactly one renderer with the property that matters: every string it
 * places lands via textContent, and no branch of it can produce an
 * element the vocabulary does not name. A verb that could send markup
 * could read the player's session, and every builder with @program could
 * write that verb.
 */
(function () {
'use strict';

const dialog = document.getElementById('page-dialog');
const titleEl = document.getElementById('page-title');
const bodyEl = document.getElementById('page-body');
const inputRow = document.getElementById('page-input-row');
const inputEl = document.getElementById('page-cmd');

/*
 * Whether this client can show a page at all.
 *
 * A world may be running against a client older than this file. The
 * server cannot know that -- GMCP negotiation says the connection speaks
 * GMCP, not which packages it understands -- so the page is simply
 * dropped here, and the verb's plain-text fallback is what the player
 * sees. That is the same outcome as telnet, which is the right one.
 */
const usable = !!(dialog && titleEl && bodyEl && window.ScriptPanels &&
                  typeof window.ScriptPanels.renderInto === 'function' &&
                  typeof dialog.showModal === 'function');

function show(page) {
  if (!usable) return;
  const title = String((page && page.title) || '');
  titleEl.textContent = title;
  // Named for a screen reader off the same string, so the dialog
  // announces as "Training" rather than as an unlabelled dialog.
  dialog.setAttribute('aria-label', title || 'Page');
  window.ScriptPanels.renderInto(bodyEl, page && page.widgets);

  // The keyboard buffer, when the page asks for one. A page that only
  // reports something -- a score sheet, a map key -- does not want an
  // input sitting under it inviting commands it will not answer.
  const asked = !!(page && page.input);
  const wantsInput = asked && inputRow && inputEl;
  if (asked && !wantsInput) {
    // The page asked for a keyboard buffer and this document has no
    // element for one -- which in practice means a cached index.html
    // older than the markup. Silently drawing a page you cannot type
    // into looks like the world forgot to ask, so say which it was.
    console.warn('[megamoo] this page asked for a command input, but this ' +
                 'page markup has none — reload (Develop > Empty Caches).');
  }
  if (inputRow) inputRow.hidden = !wantsInput;

  const reopening = !dialog.open;
  if (reopening) dialog.showModal();
  // Scrolled to the top on a fresh page, but *not* on a refresh: `train`
  // re-sends this screen after each skill, and jumping back to the top
  // each time would lose the reader's place in a long column.
  if (reopening) bodyEl.scrollTop = 0;
  if (wantsInput) inputEl.focus();
}

const Pages = {
  attach(api) {
    if (!usable) return;

    /*
     * The keyboard buffer sends exactly what the main input row sends.
     *
     * Through `api.send`, not the socket, so a line typed here is the
     * same event as a line typed below -- and echoed to the scrollback
     * too, so the transcript records what you did while the page was up
     * rather than showing a room's worth of replies to commands that
     * appear nowhere.
     *
     * Deliberately *not* routed through the client-command layer: `\con`
     * and friends belong to the session, not to a page, and a page's
     * input claiming them would put credentials in a box that a world
     * asked to exist.
     */
    if (inputRow) {
      inputRow.addEventListener('submit', (event) => {
        event.preventDefault();
        const text = inputEl.value;
        inputEl.value = '';
        if (!text.trim()) return;
        api.echo(text, 'echo');
        api.send(text);
        inputEl.focus();
      });
    }

    api.on('gmcp:Client.Page', (payload) => {
      if (payload && typeof payload === 'object') show(payload);
    });

    // A page is about the character's situation, and once the socket is
    // gone it is about a situation that no longer obtains. Closed rather
    // than left standing over a dead connection.
    api.on('disconnect', () => {
      if (dialog.open) dialog.close();
    });
  },
};

window.Pages = Pages;

})();
