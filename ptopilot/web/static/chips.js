// Chip inputs (templates/_inputs.html `chips`): type, pick from the suggestions, Enter, and each item
// becomes a chip with a remove button. Only suggested rows become chips, so an unknown code can't be added.
//
//   data-source="airports"  /api/airports?q=&near=   (data-near: the home airport, nearest first)
//   data-source="places"    /api/places?q=
//   data-source="holidays"  /api/holidays?calendar=  (the form's holiday_calendar), filtered here; the
//                           calendar's holidays are also listed as toggle chips, which replace the
//                           typing box once they load and follow the calendar picker
//   data-source="dates"     a date picker; each picked date is a chip
//   data-max="1"            one chip at most: picking another replaces it
//   data-near-first         airports measured from the list's own first chip (the home airport)
//
// Without this script (or before it runs) the visible text field (a comma list) is submitted. Here the hidden field carries
// the list instead, and a "change" event on it lets the form save itself (ui.js, data-autosave).
// Keys: ↑ ↓ move, Enter adds, Esc closes, Backspace in an empty field removes the last chip.
// Text still in the box when the form is sent (Next, Save) is treated like Enter: the top suggestion is
// picked, or the form waits and says nothing matches.

const MAX_ROWS = 6;
const DEBOUNCE_MS = 150;
const NOUN = { airports: "airport", places: "place", holidays: "holiday" };
const OFFLINE = "Couldn't load suggestions. Check your connection.";

const holidayCache = new Map(); // calendar code -> Promise<string[]>

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

function dateLabel(iso) {
  const d = new Date(iso + "T00:00:00");
  if (Number.isNaN(d.getTime())) return iso;
  const parts = d.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });
  return parts.replace(",", "") + ", " + d.getFullYear();
}

// A suggestion as the menu shows it and as a chip keeps it: { value, code, label, title, meta }.
function airportRow(r) {
  const km = r.km == null ? "" : ` · ${r.km.toLocaleString("en-US")} km`;
  return { value: r.code, code: r.code, label: r.city, title: `${r.code} · ${r.name}`, meta: `${r.city}, ${r.country}${km}` };
}

function placeRow(r) {
  return {
    value: r.code,
    code: r.code,
    label: r.name,
    title: r.name,
    meta: `${r.country} · ${r.airports.map((a) => a.code).join(", ")}`,
    photo: r.photo || null, // the place's cover thumbnail, once it has one
  };
}

async function getJSON(url, signal) {
  const response = await fetch(url, { headers: { Accept: "application/json" }, credentials: "same-origin", signal });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

function setup(root) {
  if (root.hasAttribute("data-chips-live")) return;
  root.setAttribute("data-chips-live", "");
  const source = root.dataset.source;
  const max = Number(root.dataset.max || 0);
  const list = root.querySelector(".chip-list");
  const hidden = root.querySelector("[data-chips-value]");
  const input = root.querySelector("[data-chips-input]");
  const menu = root.querySelector(".chip-menu");
  const note = root.querySelector(".chip-note");
  const form = root.closest("form");

  hidden.disabled = false;
  input.removeAttribute("name");
  root.classList.add("is-live"); // app.css switches to the chip box only now
  input.value = "";
  if (source === "dates") {
    input.type = "date";
  } else {
    input.setAttribute("role", "combobox");
    input.setAttribute("aria-autocomplete", "list");
    input.setAttribute("aria-expanded", "false");
    input.setAttribute("aria-controls", menu.id);
  }

  let rows = [];
  let active = -1;
  let pending = null; // the running lookup, so Enter can wait for it
  let controller = null;
  let timer = null;

  const values = () => [...list.children].map((li) => li.dataset.value);

  function say(text) {
    note.textContent = text || "";
  }

  function sync() {
    hidden.value = values().join(", ");
    hidden.dispatchEvent(new Event("change", { bubbles: true }));
  }

  function chip(item) {
    const li = el("li", "chip");
    li.dataset.value = item.value;
    const text = el("span", "chip-text");
    if (item.code) {
      text.append(el("b", null, item.code));
      if (item.label && item.label !== item.code) text.append(` · ${item.label}`); // "PHL · Philadelphia"
    } else {
      text.textContent = item.label || item.value;
    }
    const x = el("button", "chip-x", "×");
    x.type = "button";
    x.setAttribute("aria-label", `Remove ${item.code || item.label || item.value}`);
    li.append(text, x);
    return li;
  }

  function shake(li) {
    li.classList.remove("is-shaking");
    void li.offsetWidth; // restart the animation
    li.classList.add("is-shaking");
    li.addEventListener("animationend", () => li.classList.remove("is-shaking"), { once: true });
  }

  function add(item) {
    const same = [...list.children].find((li) => li.dataset.value === item.value);
    if (same) {
      shake(same);
      say(`${item.code || item.label || item.value} is already added.`);
      return false;
    }
    while (max && list.children.length >= max) list.firstElementChild.remove();
    list.append(chip(item));
    say("");
    sync();
    return true;
  }

  function remove(li) {
    const name = li.querySelector(".chip-x").getAttribute("aria-label").replace(/^Remove /, "");
    li.remove();
    say(`Removed ${name}.`);
    sync();
    input.focus();
  }

  function close() {
    menu.hidden = true;
    menu.replaceChildren();
    rows = [];
    active = -1;
    input.setAttribute("aria-expanded", "false");
    input.removeAttribute("aria-activedescendant");
  }

  function highlight(i) {
    active = i;
    [...menu.children].forEach((li, n) => li.setAttribute("aria-selected", String(n === i)));
    if (i >= 0) input.setAttribute("aria-activedescendant", menu.children[i].id);
    else input.removeAttribute("aria-activedescendant");
  }

  function render(found) {
    rows = found.slice(0, MAX_ROWS);
    if (!rows.length) return close();
    const added = new Set(values());
    menu.replaceChildren(
      ...rows.map((row, i) => {
        const li = el("li", "chip-option");
        li.id = `${menu.id}-${i}`;
        li.setAttribute("role", "option");
        const text = row.photo ? el("span", "chip-option-text") : li;
        text.append(el("b", null, row.title || row.label));
        const meta = [row.meta, added.has(row.value) ? "added" : ""].filter(Boolean).join(" · ");
        if (meta) text.append(el("span", "muted", meta));
        if (row.photo) {
          const img = el("img", "chip-thumb");
          img.src = row.photo;
          img.alt = "";
          img.loading = "lazy";
          img.width = 36;
          img.height = 36;
          img.addEventListener("error", () => img.remove()); // a failed load just leaves the text
          li.classList.add("has-thumb");
          li.append(img, text);
        }
        li.addEventListener("mousedown", (e) => e.preventDefault()); // keep focus in the field
        li.addEventListener("click", () => choose(i));
        return li;
      }),
    );
    menu.hidden = false;
    input.setAttribute("aria-expanded", "true");
    highlight(0);
  }

  async function holidays(q, signal) {
    const select = form && form.querySelector("[name=holiday_calendar]");
    const calendar = select ? select.value : "";
    if (!holidayCache.has(calendar)) {
      holidayCache.set(calendar, getJSON(`/api/holidays?calendar=${encodeURIComponent(calendar)}`, signal));
    }
    let names;
    try {
      names = await holidayCache.get(calendar);
    } catch (err) {
      holidayCache.delete(calendar);
      throw err;
    }
    const needle = q.toLowerCase();
    const later = (n) => (n.toLowerCase().startsWith(needle) ? 0 : 1); // "Ve" puts Veterans Day first
    return names
      .filter((n) => n.toLowerCase().includes(needle))
      .sort((a, b) => later(a) - later(b))
      .map((n) => ({ value: n, label: n, title: n }));
  }

  function lookup(q, signal) {
    if (source === "airports") {
      const near = root.dataset.near ? `&near=${encodeURIComponent(root.dataset.near)}` : "";
      return getJSON(`/api/airports?q=${encodeURIComponent(q)}${near}`, signal).then((r) => r.map(airportRow));
    }
    if (source === "places") {
      return getJSON(`/api/places?q=${encodeURIComponent(q)}`, signal).then((r) => r.map(placeRow));
    }
    return holidays(q, signal);
  }

  function search() {
    const q = input.value.trim();
    if (controller) controller.abort();
    if (q.length < (source === "holidays" ? 1 : 2)) {
      pending = null;
      close();
      return;
    }
    controller = new AbortController();
    const mine = controller;
    pending = lookup(q, mine.signal)
      .then((found) => {
        if (mine === controller) render(found);
        return found;
      })
      .catch((err) => {
        if (err.name === "AbortError") return [];
        if (mine === controller) close(); // no stale rows from an earlier query for Enter to add
        say(OFFLINE);
        return null;
      });
  }

  function choose(i) {
    const row = rows[i];
    if (!row) return;
    if (add(row)) {
      input.value = "";
      close();
    }
    input.focus();
  }

  // Adds the highlighted (or top) suggestion for the typed text; false when there is none.
  async function enter() {
    const q = input.value.trim();
    if (!q) return true;
    if (timer) {
      clearTimeout(timer);
      timer = null;
      search();
    }
    if (pending && (await pending) === null) return false; // the lookup failed: OFFLINE is showing
    if (rows.length) {
      choose(Math.max(active, 0));
      return true;
    }
    say(`No ${NOUN[source] || "match"} matches '${q}' — pick one from the list.`);
    const box = root.querySelector(".chip-box");
    box.classList.remove("is-shaking");
    void box.offsetWidth;
    box.classList.add("is-shaking");
    box.addEventListener("animationend", () => box.classList.remove("is-shaking"), { once: true });
    input.focus();
    return false;
  }

  // Sending the form with text still typed: pick for it first (as Enter would), then send; or stay put.
  // A capture listener on the form runs before ui.js's (on document), so an in-place save waits too.
  if (form && source !== "dates") {
    form.addEventListener(
      "submit",
      async (e) => {
        if (!input.value.trim() || !root.isConnected) return;
        e.preventDefault();
        e.stopPropagation();
        const submitter = e.submitter;
        if (!(await enter()) || input.value.trim()) return; // nothing picked, or it was already added
        // An autosaving form already saves on the hidden field's change.
        if (!form.hasAttribute("data-autosave")) form.requestSubmit(submitter || undefined);
      },
      true,
    );
  }

  // The holidays as toggle chips: pressed = your office works it. Switching the calendar relists them
  // and drops the ones the new calendar doesn't have (the server would refuse them).
  const picker = source === "holidays" && form ? form.querySelector("[name=holiday_calendar]") : null;
  let shelf = null;
  async function toggles() {
    let names;
    try {
      names = (await holidays("")).map((row) => row.value);
    } catch (err) {
      root.classList.remove("has-toggles"); // the typing box stays as the way in
      if (shelf) shelf.remove();
      shelf = null;
      return;
    }
    const known = new Set(names);
    const dropped = values().filter((v) => !known.has(v));
    if (dropped.length) {
      [...list.children].filter((li) => dropped.includes(li.dataset.value)).forEach((li) => li.remove());
      say(`Removed ${dropped.join(", ")}: not in this calendar.`);
      sync();
    }
    if (!shelf) {
      shelf = el("ul", "holiday-toggles");
      shelf.setAttribute("aria-label", "Holidays in this calendar");
      root.querySelector(".chip-box").after(shelf);
    }
    const on = new Set(values());
    shelf.replaceChildren(
      ...names.map((name) => {
        const li = el("li");
        const b = el("button", "holiday-toggle", name);
        b.type = "button";
        b.setAttribute("aria-pressed", String(on.has(name)));
        b.addEventListener("click", () => {
          const pressed = b.getAttribute("aria-pressed") === "true";
          if (pressed) {
            [...list.children].filter((c) => c.dataset.value === name).forEach((c) => c.remove());
            sync();
          } else {
            add({ value: name, label: name, title: name });
          }
          b.setAttribute("aria-pressed", String(!pressed));
        });
        li.append(b);
        return li;
      }),
    );
    root.classList.add("has-toggles");
  }
  if (picker) {
    picker.addEventListener("change", toggles);
    toggles();
  }

  list.addEventListener("click", (e) => {
    const x = e.target.closest(".chip-x");
    if (x) remove(x.closest(".chip"));
  });
  // Clicking the empty part of the box puts the caret in the field, as if the box were one input.
  root.querySelector(".chip-box").addEventListener("click", (e) => {
    if (!e.target.closest(".chip")) input.focus();
  });

  if (source === "dates") {
    const pick = () => {
      if (!input.value) return;
      if (add({ value: input.value, label: dateLabel(input.value) })) input.value = "";
    };
    input.addEventListener("change", pick);
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        pick();
      } else if (e.key === "Backspace" && !input.value && list.lastElementChild) {
        e.preventDefault();
        remove(list.lastElementChild);
      }
    });
    return;
  }

  input.addEventListener("input", () => {
    say("");
    clearTimeout(timer);
    timer = setTimeout(() => {
      timer = null;
      search();
    }, DEBOUNCE_MS);
  });
  input.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      if (menu.hidden) return search();
      const step = e.key === "ArrowDown" ? 1 : -1;
      highlight((active + step + rows.length) % rows.length);
    } else if (e.key === "Enter") {
      e.preventDefault(); // never submits the form; the hidden field's change saves it
      enter();
    } else if (e.key === "Escape") {
      if (!menu.hidden) {
        e.preventDefault();
        close();
      } else if (input.value) {
        e.preventDefault();
        input.value = "";
        say("");
      }
    } else if (e.key === "Backspace" && !input.value && list.lastElementChild) {
      e.preventDefault();
      remove(list.lastElementChild);
    }
  });
  input.addEventListener("blur", () => setTimeout(close, 120));
}

function setupAll(scope) {
  scope.querySelectorAll("[data-chips]").forEach(setup);
}

setupAll(document);
// A new home airport is where the other airport fields measure "nearest" from.
document.addEventListener("change", (e) => {
  if (!e.target.matches || !e.target.matches("[data-chips-value][name=home_airport]") || !e.target.form) return;
  e.target.form.querySelectorAll("[data-chips][data-source=airports]").forEach((root) => {
    root.dataset.near = e.target.value;
  });
});
// One airport list with the home airport first (/welcome step 1, data-near-first): its first chip is home.
document.addEventListener("change", (e) => {
  const root = e.target.closest && e.target.closest("[data-chips][data-near-first]");
  if (!root || !e.target.matches("[data-chips-value]")) return;
  root.dataset.near = e.target.value.split(",")[0].trim();
});
// Sections swapped in place (ui.js) bring fresh markup to enhance.
document.addEventListener("ui:swapped", (e) => setupAll(e.detail.element));
