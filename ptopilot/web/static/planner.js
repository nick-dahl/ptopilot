// Drag across the year calendar to open or close days; save posts the same rows the form does.
(function () {
  "use strict";
  var calendar = document.getElementById("year-calendar");
  var form = document.getElementById("ranges-form");
  if (!calendar || !form) return;

  var days = Array.prototype.slice.call(calendar.querySelectorAll("td[data-date]"));
  var indexOf = new Map();
  days.forEach(function (d, i) { indexOf.set(d, i); });
  var note = document.getElementById("unsaved");
  var dirty = false;
  var drag = null; // { anchor, current, mode }, mouse and pen only
  var tap = null; // the day a touch started on

  function dayAt(x, y) {
    var el = document.elementFromPoint(x, y);
    var td = el && el.closest ? el.closest("td[data-date]") : null;
    return td && indexOf.has(td) ? td : null;
  }

  function markDirty() {
    dirty = true;
    if (note) note.hidden = false;
  }

  function clearPreview() {
    days.forEach(function (d) { d.classList.remove("drag-open", "drag-close"); });
  }

  function span() {
    var a = indexOf.get(drag.anchor);
    var b = indexOf.get(drag.current);
    return [Math.min(a, b), Math.max(a, b)];
  }

  function preview() {
    clearPreview();
    var s = span();
    for (var i = s[0]; i <= s[1]; i++) days[i].classList.add("drag-" + drag.mode);
  }

  function apply(from, to, mode) {
    for (var i = from; i <= to; i++) days[i].classList.toggle("open", mode === "open");
    markDirty();
  }

  calendar.addEventListener("pointerdown", function (e) {
    if (e.button !== undefined && e.button > 0) return;
    var td = dayAt(e.clientX, e.clientY);
    if (!td) return;
    if (e.pointerType === "touch") {
      // Touch scrolls the page; only a tap (down and up on the same day) toggles.
      tap = td;
      return;
    }
    e.preventDefault();
    drag = { anchor: td, current: td, mode: td.classList.contains("open") ? "close" : "open" };
    preview();
  });

  calendar.addEventListener("pointermove", function (e) {
    if (!drag) return;
    var td = dayAt(e.clientX, e.clientY);
    if (td && td !== drag.current) {
      drag.current = td;
      preview();
    }
  });

  function finish(e, commit) {
    if (!drag) return;
    if (commit) {
      var td = dayAt(e.clientX, e.clientY);
      if (td) drag.current = td;
      var s = span();
      apply(s[0], s[1], drag.mode);
    }
    clearPreview();
    drag = null;
  }

  window.addEventListener("pointerup", function (e) {
    if (e.pointerType === "touch") {
      var started = tap;
      tap = null;
      if (started && dayAt(e.clientX, e.clientY) === started) {
        started.classList.toggle("open");
        markDirty();
      }
      return;
    }
    finish(e, true);
  });
  window.addEventListener("pointercancel", function (e) {
    tap = null;
    finish(e, false);
  });

  calendar.addEventListener("keydown", function (e) {
    if (e.repeat) return;
    if (e.key !== "Enter" && e.key !== " " && e.key !== "Spacebar") return;
    var td = e.target.closest ? e.target.closest("td[data-date]") : null;
    if (!td || !indexOf.has(td)) return;
    e.preventDefault();
    td.classList.toggle("open");
    markDirty();
  });

  // Consecutive open days become one range.
  function openRanges() {
    var out = [];
    var start = null;
    days.forEach(function (d, i) {
      var isOpen = d.classList.contains("open");
      if (isOpen && start === null) start = i;
      if (!isOpen && start !== null) {
        out.push([days[start].dataset.date, days[i - 1].dataset.date]);
        start = null;
      }
    });
    if (start !== null) out.push([days[start].dataset.date, days[days.length - 1].dataset.date]);
    return out;
  }

  function hidden(name, value) {
    var input = document.createElement("input");
    input.type = "hidden";
    input.name = name;
    input.value = value;
    input.setAttribute("data-planner", "");
    return input;
  }

  form.addEventListener("submit", function () {
    if (!dirty) return; // untouched calendar: the typed date fields are what the person meant
    Array.prototype.slice.call(form.querySelectorAll("input[data-planner]")).forEach(function (i) {
      i.parentNode.removeChild(i);
    });
    Array.prototype.slice.call(form.querySelectorAll(".range-row")).forEach(function (row) {
      row.parentNode.removeChild(row);
    });
    openRanges().forEach(function (r, i) {
      form.appendChild(hidden("range_start_" + i, r[0]));
      form.appendChild(hidden("range_end_" + i, r[1]));
    });
  });
})();
