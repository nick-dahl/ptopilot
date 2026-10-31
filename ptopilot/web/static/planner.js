// The year calendar (the tap-calendar of daygrid.js, loaded first): open or close days, then save posts
// the same rows the form does.
// When ui.js swaps the calendar panel in place (after a booking), the new calendar is bound afresh and
// any unsaved open days carry over.
(function () {
  "use strict";
  var current = null; // the bound calendar: { calendar, isDirty, openDates, restore, teardown }

  function bind() {
    var calendar = document.getElementById("year-calendar");
    var form = document.getElementById("ranges-form");
    if (!calendar || !form || !window.DayGrid || calendar.hasAttribute("data-planner-bound")) return null;
    calendar.setAttribute("data-planner-bound", "");

    var note = document.getElementById("unsaved");
    var hint = document.getElementById("dirty-hint");
    var spill = [];
    try { spill = JSON.parse(calendar.dataset.spill || "[]"); } catch (err) { spill = []; }
    var dirty = false;

    function markDirty() {
      dirty = true;
      if (note) note.hidden = false;
      if (hint) hint.hidden = false;
    }

    // Tapping, dragging and the keyboard live in daygrid.js, shared with the profile's days-off calendar.
    var grid = window.DayGrid(calendar, { cls: "open", onChange: markDirty });
    var days = grid.days;

    // A saved range may run past Dec 31 into the next year; the calendar can't show that part, so a run
    // that reaches Dec 31 and holds the start of such a range keeps that range's original end.
    function runEnd(first, last) {
      var end = days[last].dataset.date;
      if (last !== days.length - 1) return end;
      spill.forEach(function (r) {
        if (r[0] >= days[first].dataset.date && r[0] <= end && r[1] > end) end = r[1];
      });
      return end;
    }

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
      if (start !== null) out.push([days[start].dataset.date, runEnd(start, days.length - 1)]);
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

    return {
      calendar: calendar,
      isDirty: function () { return dirty; },
      openDates: function () {
        return days.filter(function (d) { return d.classList.contains("open"); }).map(function (d) { return d.dataset.date; });
      },
      restore: function (dates) {
        var wanted = new Set(dates);
        days.forEach(function (d) { d.classList.toggle("open", wanted.has(d.dataset.date)); });
        markDirty();
      },
      teardown: grid.teardown,
    };
  }

  current = bind();

  document.addEventListener("ui:swapped", function (e) {
    var el = e.detail && e.detail.element;
    if (!el || !(el.id === "year-calendar" || el.querySelector("#year-calendar"))) return;
    if (current && document.contains(current.calendar)) return; // still the same calendar
    var carried = current && current.isDirty() ? current.openDates() : null;
    if (current) current.teardown();
    current = bind();
    if (current && carried) current.restore(carried);
  });
})();
