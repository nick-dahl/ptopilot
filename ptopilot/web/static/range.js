// Number inputs (templates/_inputs.html): the trip-length slider and the − / + steppers.
//
// Trip length: two handles for the shortest and longest trip and a ★ for the ideal one, which is kept
// between them; "No preference" clears the ideal. The three number fields stay the form's real fields
// (they are what a browser without JS shows), so the sliders only write into them, and a "change" on
// them lets the form save itself (ui.js, data-autosave).

function fire(input) {
  input.dispatchEvent(new Event("input", { bubbles: true }));
  input.dispatchEvent(new Event("change", { bubbles: true }));
}

function plural(n) {
  return `${n} day${n === 1 ? "" : "s"}`;
}

function setupRange(root) {
  if (root.hasAttribute("data-range-live")) return;
  root.setAttribute("data-range-live", "");
  const lo = Number(root.dataset.lo);
  const hi = Number(root.dataset.hi);
  const minSlider = root.querySelector(".range-min");
  const maxSlider = root.querySelector(".range-max");
  const star = root.querySelector(".range-ideal");
  const starLabel = root.querySelector(".star-label");
  const line = root.querySelector(".range-line");
  const none = root.querySelector("[data-no-preference]");
  const fields = {
    min: root.querySelector("[name=min_trip_days]"),
    max: root.querySelector("[name=max_trip_days]"),
    ideal: root.querySelector("[name=ideal_trip_days]"),
  };

  const clamp = (v, a, b) => Math.min(Math.max(v, a), b);
  const share = (v) => (hi > lo ? (v - lo) / (hi - lo) : 0);
  const noPreference = () => none.getAttribute("aria-pressed") === "true";

  function paint() {
    const a = Number(minSlider.value);
    const b = Number(maxSlider.value);
    // Positions as custom properties; app.css turns them into lengths that line up with the thumbs.
    root.style.setProperty("--from", share(a));
    root.style.setProperty("--to", share(b));
    root.style.setProperty("--star", share(Number(star.value)));
    root.classList.toggle("no-ideal", noPreference());
    starLabel.textContent = noPreference() ? "" : `★ ${plural(Number(star.value))}`;
    const span = a === b ? `${plural(a)} away` : `${a} to ${plural(b)} away`;
    line.textContent = noPreference() ? `${span} · no preferred length` : `${span} · ideally ${star.value}`;
    star.setAttribute("aria-valuetext", noPreference() ? "No preference" : plural(Number(star.value)));
    minSlider.setAttribute("aria-valuetext", plural(a));
    maxSlider.setAttribute("aria-valuetext", plural(b));
  }

  // Slider moved: keep the handles in order and the ★ between them, then write the number fields.
  function moved(which) {
    let a = Number(minSlider.value);
    let b = Number(maxSlider.value);
    if (a > b) {
      if (which === minSlider) a = b;
      else b = a;
      minSlider.value = a;
      maxSlider.value = b;
    }
    if (which === star) none.setAttribute("aria-pressed", "false");
    star.value = clamp(Number(star.value), a, b);
    fields.min.value = a;
    fields.max.value = b;
    fields.ideal.value = noPreference() ? "" : star.value;
    paint();
  }

  function committed() {
    [fields.min, fields.max, fields.ideal].forEach(fire);
  }

  // Start from the number fields, which hold the saved values (or what was typed before the page loaded).
  const start = (field, fallback) => {
    const n = parseInt(field.value, 10);
    return Number.isNaN(n) ? fallback : clamp(n, lo, hi);
  };
  minSlider.value = start(fields.min, lo);
  maxSlider.value = Math.max(start(fields.max, hi), Number(minSlider.value));
  if (fields.ideal.value.trim() === "") {
    none.setAttribute("aria-pressed", "true");
    star.value = Math.round((Number(minSlider.value) + Number(maxSlider.value)) / 2);
  } else {
    none.setAttribute("aria-pressed", "false");
    star.value = start(fields.ideal, Number(minSlider.value));
  }
  star.value = clamp(Number(star.value), Number(minSlider.value), Number(maxSlider.value));

  for (const slider of [minSlider, maxSlider, star]) {
    slider.addEventListener("input", () => moved(slider));
    slider.addEventListener("change", committed);
  }
  none.addEventListener("click", () => {
    none.setAttribute("aria-pressed", String(!noPreference()));
    moved(none);
    committed();
  });
  paint();
}

function setupStepper(root) {
  if (root.hasAttribute("data-stepper-live")) return;
  root.setAttribute("data-stepper-live", "");
  const input = root.querySelector("input");
  root.querySelectorAll("[data-step]").forEach((button) => {
    button.addEventListener("click", () => {
      const step = Number(button.dataset.step);
      const min = input.min === "" ? -Infinity : Number(input.min);
      const max = input.max === "" ? Infinity : Number(input.max);
      const now = parseInt(input.value, 10);
      const next = Math.min(Math.max((Number.isNaN(now) ? 0 : now) + step, min), max);
      if (String(next) === input.value) return;
      input.value = next;
      fire(input);
    });
  });
}

function setupAll(scope) {
  scope.querySelectorAll("[data-trip-range]").forEach(setupRange);
  scope.querySelectorAll("[data-stepper]").forEach(setupStepper);
}

setupAll(document);
document.addEventListener("ui:swapped", (e) => setupAll(e.detail.element));
