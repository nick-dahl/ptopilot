// Small actions without a page reload. A <form data-inplace> posts with fetch and asks for JSON; the
// server answers {"ok": true, ...} or a 4xx with {"ok": false, "errors": [...]}. Without this script the
// same form is a plain POST that redirects, so every action still works with JavaScript off.
//
//   data-after="reload-section"  re-fetch this page and swap the element(s) named by data-section
//                                (an id, or several ids separated by spaces)
//   data-after="remove"          remove the element named by data-section (or the form itself)
//   data-after="none"            leave the page as it is (the default)
//   data-toast="..."             optional message for the toast shown when the control is gone
//
// After swapping a section it dispatches "ui:swapped" on document ({ detail: { element } }) so scripts
// bound to the old markup can re-bind.

const SAVED_MS = 2200;
const TOAST_MS = 3200;

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

function showErrors(form, control, errors) {
  clearErrors(form);
  const box = document.createElement("span");
  box.className = "inline-error";
  box.setAttribute("role", "alert");
  box.textContent = (errors && errors.length ? errors : ["That didn't work. Try again."]).join(" ");
  (control || form.lastElementChild || form).after(box);
}

function showSaved(control) {
  if (!control) return;
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
      showErrors(form, submitter, data && data.errors);
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
    if (again) {
      showSaved(again);
      if (hadFocus) again.focus();
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
