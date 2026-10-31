// The arrival dialog for a rare deal (dashboard). The hero carries data-candidate-id only when its deal is
// a standout; this opens the hero's <dialog> once per deal per browser, remembered in localStorage under
// ptopilot:seen:{candidate_id}. At 768px and up it is a centred dialog; below that a sheet that slides up
// after the page has painted, so it never covers the content on first paint. Esc, ×, "Not now" or a click
// outside closes it. Without this script (or without <dialog> support) nothing appears: the hero is enough.

const PHONE_DELAY_MS = 700;

function seenKey(id) {
  return `ptopilot:seen:${id}`;
}

function wasSeen(id) {
  try {
    return localStorage.getItem(seenKey(id)) !== null;
  } catch (err) {
    return false; // storage blocked: show it, and simply can't remember
  }
}

function markSeen(id) {
  try {
    localStorage.setItem(seenKey(id), new Date().toISOString());
  } catch (err) {
    /* storage blocked or full: nothing to remember it in */
  }
}

function init() {
  const root = document.querySelector("#hero[data-candidate-id]");
  const dialog = root && root.querySelector("dialog.arrival");
  if (!dialog || typeof dialog.showModal !== "function") return;
  const id = root.dataset.candidateId;
  root.classList.add("is-live");
  if (wasSeen(id)) return;

  const close = () => dialog.open && dialog.close();
  dialog.querySelectorAll("[data-close]").forEach((b) => b.addEventListener("click", close));
  // A click on the backdrop lands on the <dialog> itself, outside its content box.
  dialog.addEventListener("click", (event) => {
    if (event.target !== dialog) return;
    const box = dialog.getBoundingClientRect();
    const inside =
      event.clientX >= box.left && event.clientX <= box.right && event.clientY >= box.top && event.clientY <= box.bottom;
    if (!inside) close();
  });
  // Esc fires "cancel" and closes the modal natively.

  const phone = !window.matchMedia("(min-width: 768px)").matches;
  dialog.classList.toggle("is-sheet", phone);
  const open = () => {
    markSeen(id);
    dialog.showModal();
  };
  if (phone) setTimeout(() => requestAnimationFrame(open), PHONE_DELAY_MS);
  else open();
}

init();
