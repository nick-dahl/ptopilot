// The destinations page: picking a place in the search box opens an "add" card for it, with the place's
// airports as chips, the nearby ones offered as "+" buttons, and a days-away stepper. The card is a plain
// <form data-inplace> posting to /destinations (ui.js saves it and refreshes the list). Without this
// script the search box is an ordinary GET search and each match has its own form.

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

async function findPlace(code) {
  const response = await fetch(`/api/places?q=${encodeURIComponent(code)}`, {
    headers: { Accept: "application/json" },
    credentials: "same-origin",
  });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const rows = await response.json();
  return rows.find((r) => r.code === code) || rows[0] || null;
}

function buildCard(place) {
  const card = document.getElementById("add-card").content.firstElementChild.cloneNode(true);
  card.querySelector("[name=code]").value = place.code;
  card.querySelector("[data-place-name]").textContent = place.name;
  card.querySelector("[data-place-country]").textContent = place.country;
  const chipList = card.querySelector("[data-airport-chips]");
  const offers = card.querySelector("[data-airport-offers]");
  const offerList = card.querySelector("[data-airport-offer-list]");
  const chosen = new Set(place.default && place.default.length ? place.default : [place.code]);
  chosen.add(place.code); // the picked airport always stays: the server needs it

  function paint() {
    chipList.replaceChildren(
      ...place.airports
        .filter((a) => chosen.has(a.code))
        .map((a) => {
          const li = el("li", "chip");
          const text = el("span", "chip-text");
          text.append(el("b", null, a.code), ` · ${a.name}`);
          const field = el("input");
          field.type = "hidden";
          field.name = "airports";
          field.value = a.code;
          li.append(text, field);
          if (a.code !== place.code) {
            const x = el("button", "chip-x", "×");
            x.type = "button";
            x.setAttribute("aria-label", `Remove ${a.code}`);
            x.addEventListener("click", () => {
              chosen.delete(a.code);
              paint();
            });
            li.append(x);
          }
          return li;
        }),
    );
    const rest = place.airports.filter((a) => !chosen.has(a.code));
    offers.hidden = rest.length === 0;
    offerList.replaceChildren(
      ...rest.map((a) => {
        const li = el("li");
        const add = el("button", "chip-toggle", `+ ${a.code} · ${a.name}`);
        add.type = "button";
        add.setAttribute("aria-label", `Add ${a.code}, ${a.name}`);
        add.addEventListener("click", () => {
          chosen.add(a.code);
          paint();
        });
        li.append(add);
        return li;
      }),
    );
  }
  paint();
  return card;
}

function setup(search) {
  if (search.hasAttribute("data-place-live")) return;
  search.setAttribute("data-place-live", "");
  const slot = document.getElementById("add-card-slot");
  const list = search.querySelector(".chip-list");
  const hidden = search.querySelector("[data-chips-value]");
  const input = search.querySelector("[data-chips-input]");
  if (!slot || !hidden || !document.getElementById("add-card")) return;

  hidden.addEventListener("change", async () => {
    const code = hidden.value.trim();
    if (!code) return;
    list.replaceChildren(); // the box is only a picker: the card takes over from here
    hidden.value = "";
    let place = null;
    try {
      place = await findPlace(code);
    } catch (err) {
      place = null;
    }
    if (!place) {
      slot.replaceChildren(el("p", "inline-error", "Couldn't load that place. Try again."));
      return;
    }
    const card = buildCard(place);
    card.querySelector("[data-close-card]").addEventListener("click", () => {
      slot.replaceChildren();
      input.focus();
    });
    slot.replaceChildren(card);
    // The card's stepper wakes up like any swapped-in markup (range.js).
    document.dispatchEvent(new CustomEvent("ui:swapped", { detail: { element: card } }));
    card.querySelector("input[name=target_days]").focus();
  });
}

function setupAll(scope) {
  scope.querySelectorAll("[data-place-search]").forEach(setup);
}

setupAll(document);
document.addEventListener("ui:swapped", (e) => setupAll(e.detail.element));
