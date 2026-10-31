// The tap-calendar: month tables of days (templates/_components.html `month_tables`) where a day is
// toggled by a tap, by Enter or Space, or, with a mouse or pen, by dragging across a run of days.
//
//   window.DayGrid(calendar, { cls, onChange })  binds one calendar; `cls` is the class a picked day
//       carries ("open" in the year planner) and onChange() runs after each change. Returns
//       { days, teardown }; teardown() drops the window handlers when the calendar is replaced.
//
// The planner (planner.js) builds its ranges on it. The profile's company days off use it directly:
// a [data-day-picker] holds the calendar ([data-day-grid], picked days are .off), a hidden field with the
// comma list of dates, and the plain text field that a browser without this script uses instead.
(function () {
  "use strict";

  function DayGrid(calendar, options) {
    var cls = options.cls;
    var onChange = options.onChange || function () {};
    var days = Array.prototype.slice.call(calendar.querySelectorAll("td[data-date]"));
    var indexOf = new Map();
    days.forEach(function (d, i) { indexOf.set(d, i); });
    var drag = null; // { anchor, current, mode }, mouse and pen only
    var tap = null; // the day a touch started on

    function dayAt(x, y) {
      var el = document.elementFromPoint(x, y);
      var td = el && el.closest ? el.closest("td[data-date]") : null;
      return td && indexOf.has(td) ? td : null;
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
      drag = { anchor: td, current: td, mode: td.classList.contains(cls) ? "close" : "open" };
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
        for (var i = s[0]; i <= s[1]; i++) days[i].classList.toggle(cls, drag.mode === "open");
      }
      clearPreview();
      drag = null;
      if (commit) onChange();
    }

    function onPointerUp(e) {
      if (e.pointerType === "touch") {
        var started = tap;
        tap = null;
        if (started && dayAt(e.clientX, e.clientY) === started) {
          started.classList.toggle(cls);
          onChange();
        }
        return;
      }
      finish(e, true);
    }
    function onPointerCancel(e) {
      tap = null;
      finish(e, false);
    }
    window.addEventListener("pointerup", onPointerUp);
    window.addEventListener("pointercancel", onPointerCancel);

    calendar.addEventListener("keydown", function (e) {
      if (e.repeat) return;
      if (e.key !== "Enter" && e.key !== " " && e.key !== "Spacebar") return;
      var td = e.target.closest ? e.target.closest("td[data-date]") : null;
      if (!td || !indexOf.has(td)) return;
      e.preventDefault();
      td.classList.toggle(cls);
      onChange();
    });

    return {
      days: days,
      teardown: function () {
        window.removeEventListener("pointerup", onPointerUp);
        window.removeEventListener("pointercancel", onPointerCancel);
      },
    };
  }

  window.DayGrid = DayGrid;

  // --- the day picker (profile: company days off) ------------------------------------------------

  function label(iso) {
    var d = new Date(iso + "T00:00:00");
    if (isNaN(d.getTime())) return iso;
    return d.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" }).replace(",", "") +
      ", " + d.getFullYear();
  }

  function bindPicker(root) {
    if (root.classList.contains("is-live")) return;
    var calendar = root.querySelector("[data-day-grid]");
    var hidden = root.querySelector("[data-days-value]");
    var plain = root.querySelector("[data-days-plain]");
    var list = root.querySelector(".day-picked");
    if (!calendar || !hidden || !plain || !list) return;
    // Dates the calendar doesn't show (past ones, or more than a year out) are kept as they were.
    var shown = new Set();
    calendar.querySelectorAll("td[data-date]").forEach(function (td) { shown.add(td.dataset.date); });
    var unseen = hidden.value.split(",").map(function (s) { return s.trim(); }).filter(function (d) {
      return d && !shown.has(d);
    });

    function picked() {
      var on = Array.prototype.slice.call(calendar.querySelectorAll("td.off[data-date]")).map(function (td) {
        return td.dataset.date;
      });
      return unseen.concat(on).sort();
    }

    // The picked days as chips with remove buttons, so they read as saved things and are easy to undo.
    function render() {
      var dates = picked();
      list.textContent = "";
      dates.forEach(function (iso) {
        var li = document.createElement("li");
        li.className = "chip";
        var text = document.createElement("span");
        text.className = "chip-text";
        text.textContent = label(iso);
        var x = document.createElement("button");
        x.type = "button";
        x.className = "chip-x";
        x.textContent = "×";
        x.setAttribute("aria-label", "Remove " + label(iso));
        x.addEventListener("click", function () {
          unseen = unseen.filter(function (d) { return d !== iso; });
          var td = calendar.querySelector('td[data-date="' + iso + '"]');
          if (td) td.classList.remove("off");
          changed();
        });
        li.appendChild(text);
        li.appendChild(x);
        list.appendChild(li);
      });
    }

    function changed() {
      hidden.value = picked().join(", ");
      render();
      hidden.dispatchEvent(new Event("change", { bubbles: true })); // ui.js data-autosave saves it
    }

    hidden.disabled = false;
    plain.removeAttribute("name");
    root.classList.add("is-live");
    DayGrid(calendar, { cls: "off", onChange: changed });
    render();
  }

  function bindAll(scope) {
    Array.prototype.slice.call(scope.querySelectorAll("[data-day-picker]")).forEach(bindPicker);
  }

  bindAll(document);
  document.addEventListener("ui:swapped", function (e) {
    if (e.detail && e.detail.element) bindAll(e.detail.element);
  });
})();
