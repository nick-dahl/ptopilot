// Small actions without a page reload. A <form data-inplace> posts with fetch and asks for JSON; the
// server answers {"ok": true, ...} or a 4xx with {"ok": false, "errors": [...]}. Without this script the
// same form is a plain POST that redirects, so every action still works with JavaScript off.
//
//   data-after="reload-section"  re-fetch this page and swap the element(s) named by data-section
//                                (an id, or several ids separated by spaces)
//   data-after="remove"          remove the element named by data-section (or the form itself)
//   data-after="none"            leave the page as it is (the default)
//   data-toast="..."             optional message for the toast shown when the control is gone
//   data-autosave                save whenever a named field changes (the profile's sections); the
//                                form gets .is-autosaving (app.css hides its Save button), the "Saved"
//                                tick goes after that button, and errors beside their fields: an answer's
//                                field_errors ([{field, message}]) go into [data-error-for~=field] slots,
//                                the rest into the form's [data-error-slot]
//
// After swapping a section it dispatches "ui:swapped" on document ({ detail: { element } }) so scripts
// bound to the old markup can re-bind.

const SAVED_MS = 2200;
const TOAST_MS = 3200;
const AUTOSAVE_MS = 350; // a burst of changes (stepper clicks, a dragged slider) is one save

let region = null;

export function toast(message) {
  if (!region) {
    region = document.createElement("div");
    region.className = "toast-region";
    region.setAttribute("role", "status");
    region.setAttribute("aria-live", "polite");
    document.body.appendChild(region);
  }
  const item = document.createElement("div");
  item.className = "toast";
  item.textContent = message;
  region.appendChild(item);
  requestAnimationFrame(() => item.classList.add("is-shown"));
  setTimeout(() => {
    item.classList.remove("is-shown");
    setTimeout(() => item.remove(), 250);
  }, TOAST_MS);
}

function clearErrors(form) {
  form.querySelectorAll(".inline-error").forEach((el) => el.remove());
}

function errorBox(text) {
  const box = document.createElement("span");
  box.className = "inline-error";
  box.setAttribute("role", "alert");
  box.textContent = text;
  return box;
}

function showErrors(form, control, errors, fieldErrors) {
  clearErrors(form);
  const rest = [];
  for (const e of fieldErrors || []) {
    const slot = e.field && form.querySelector(`[data-error-for~="${CSS.escape(e.field)}"]`);
    if (slot) slot.append(errorBox(e.message));
    else rest.push(e.message);
  }
  if (!fieldErrors) rest.push(...(errors || []));
  if (!rest.length && fieldErrors && fieldErrors.length) return;
  const box = errorBox((rest.length ? rest : ["That didn't work. Try again."]).join(" "));
  const slot = form.querySelector("[data-error-slot]");
  if (slot) slot.append(box);
  else (control || form.lastElementChild || form).after(box);
}

function showSaved(control) {
  if (!control) return;
  control.parentElement.querySelectorAll(".saved-tick").forEach((old) => old.remove());
  const tick = document.createElement("span");
  tick.className = "saved-tick";
  tick.setAttribute("role", "status");
  tick.textContent = "Saved";
  control.after(tick);
  setTimeout(() => tick.remove(), SAVED_MS);
}

function sectionIds(form) {
  return (form.dataset.section || "").split(/\s+/).filter(Boolean);
}

// The same control in freshly swapped markup: same form action, same button name and value.
function findControl(action, name, value) {
  for (const f of document.querySelectorAll("form[data-inplace]")) {
    if (f.getAttribute("action") !== action) continue;
    for (const b of f.querySelectorAll("button[type=submit], button:not([type])")) {
      if ((b.name || "") === name && (b.value || "") === value) return b;
    }
  }
  return null;
}

// Laid out and not clipped to a pixel (app.css's .sr-only and the planner's hidden "Set" button).
function visible(node) {
  if (!node || !node.isConnected || node.closest("[hidden], .sr-only")) return false;
  const box = node.getBoundingClientRect();
  return box.width > 1 && box.height > 1;
}

// Focus somewhere sensible once the focused control is gone: the first visible candidate, else the
// section itself (tabindex -1 makes it focusable; .focus-landing keeps the outline from flashing).
function landFocus(candidates, section) {
  const target = candidates.find(visible);
  if (target) return target.focus();
  if (!section || !section.isConnected) return;
  section.setAttribute("tabindex", "-1");
  section.classList.add("focus-landing");
  section.focus({ preventScroll: true });
}

// The focused element's twin in fresh markup: by id, else name + value, else aria-label.
function twin(scope, node) {
  if (!scope || !node || node === document.body) return null;
  if (node.id) return scope.querySelector(`#${CSS.escape(node.id)}`);
  const attr = (a) => `[${a}="${CSS.escape(node.getAttribute(a))}"]`;
  if (node.name) {
    const value = node.getAttribute("value") != null ? attr("value") : "";
    return scope.querySelector(`${node.tagName}[name="${CSS.escape(node.name)}"]${value}`);
  }
  if (node.getAttribute("aria-label")) return scope.querySelector(`${node.tagName}${attr("aria-label")}`);
  return null;
}

async function reloadSections(ids) {
  const response = await fetch(location.href, { headers: { Accept: "text/html" }, credentials: "same-origin" });
  if (!response.ok) throw new Error("reload failed");
  const fresh = new DOMParser().parseFromString(await response.text(), "text/html");
  for (const id of ids) {
    const now = document.getElementById(id);
    const next = fresh.getElementById(id);
    if (now && next) {
      const swapped = document.importNode(next, true);
      now.replaceWith(swapped);
      // Scripts that bound to the old markup (planner.js) re-bind to the new element.
      document.dispatchEvent(new CustomEvent("ui:swapped", { detail: { element: swapped } }));
    } else if (now) now.remove();
  }
}

function removeTarget(form) {
  const ids = sectionIds(form);
  const target = (ids.length && document.getElementById(ids[0])) || form;
  target.classList.add("is-leaving");
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  setTimeout(() => target.remove(), reduced ? 0 : 180);
}

async function submitInPlace(form, submitter) {
  const body = new FormData(form);
  if (submitter && submitter.name) body.append(submitter.name, submitter.value);
  const action = form.getAttribute("action");
  const name = (submitter && submitter.name) || "";
  const value = (submitter && submitter.value) || "";
  const hadFocus = form.contains(document.activeElement);
  const focused = hadFocus ? document.activeElement : null;
  if (submitter) submitter.disabled = true;
  form.setAttribute("aria-busy", "true");
  let data = null;
  try {
    // getAttribute, never form.action: a control named "action" (the related forms' buttons) shadows it.
    const response = await fetch(action, {
      method: "POST",
      body,
      headers: { Accept: "application/json" },
      credentials: "same-origin",
    });
    data = await response.json().catch(() => null);
    if (!response.ok || !data || !data.ok) {
      showErrors(form, submitter, data && data.errors, data && data.field_errors);
      return;
    }
  } catch (err) {
    showErrors(form, submitter, ["Couldn't reach ptopilot. Check your connection and try again."]);
    return;
  } finally {
    if (submitter) submitter.disabled = false;
    form.removeAttribute("aria-busy");
  }
  clearErrors(form);
  const after = form.dataset.after || "none";
  if (after === "remove") {
    const ids = sectionIds(form);
    const gone = (ids.length && document.getElementById(ids[0])) || form;
    if (hadFocus) landFocus([], gone.parentElement && gone.parentElement.closest("section, .panel, main"));
    removeTarget(form);
    toast(form.dataset.toast || "Done");
  } else if (after === "reload-section") {
    try {
      await reloadSections(sectionIds(form));
    } catch (err) {
      location.reload();
      return;
    }
    const again = findControl(action, name, value);
    if (hadFocus) {
      const section = document.getElementById(sectionIds(form)[0]);
      landFocus([twin(section, focused), again].filter(Boolean), section);
    }
    if (again) {
      showSaved(again);
    } else {
      toast(form.dataset.toast || "Saved");
    }
  } else {
    showSaved(submitter);
  }
}

// Delegated, so forms inside swapped sections keep working.
document.addEventListener("submit", (event) => {
  const form = event.target;
  if (!(form instanceof HTMLFormElement) || !form.hasAttribute("data-inplace")) return;
  if (!window.fetch) return;
  event.preventDefault();
  if (form.getAttribute("aria-busy") === "true") return; // one request at a time
  submitInPlace(form, event.submitter || form.querySelector("button[type=submit], button:not([type])"));
});

// Save-on-change. Only fields with a name count: the chip and slider scripts write named fields and fire
// "change" on them, while their own typing boxes and range handles have no name. A change made while a
// save is running waits for it, so nothing is lost.
const autosaveTimers = new WeakMap();

function autosave(form) {
  clearTimeout(autosaveTimers.get(form));
  autosaveTimers.set(
    form,
    setTimeout(() => {
      if (form.getAttribute("aria-busy") === "true") return autosave(form);
      form.requestSubmit(form.querySelector("button[type=submit], button:not([type])") || undefined);
    }, AUTOSAVE_MS),
  );
}

function markAutosaving(scope) {
  scope.querySelectorAll("form[data-autosave]").forEach((form) => form.classList.add("is-autosaving"));
}

if (window.fetch) markAutosaving(document);
document.addEventListener("ui:swapped", (e) => window.fetch && markAutosaving(e.detail.element));

document.addEventListener("change", (event) => {
  const field = event.target;
  const form = field && field.form;
  if (!form || !form.hasAttribute("data-autosave") || !field.name || !window.fetch) return;
  autosave(form);
});
