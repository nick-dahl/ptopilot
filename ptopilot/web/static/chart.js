// The destination page's price chart: hover, tap or keyboard focus shows a scan day's date and price.
// The server draws the SVG (web/viz.trend_chart) with one hidden .trend-pt marker per scan day, carrying
// data-date (ISO) and data-price. This shows the marker nearest the pointer and a tooltip above it. With
// the chart focused, ← and → step through the days and Home/End jump to the ends; Esc hides the tooltip.
// Without this script the chart is still drawn, with its first and last day and the low price below it.

const DATE = new Intl.DateTimeFormat("en-US", { weekday: "short", month: "short", day: "numeric", timeZone: "UTC" });

function money(value) {
  return "$" + Number(value).toLocaleString("en-US", { maximumFractionDigits: 0 });
}

function init(plot) {
  const svg = plot.querySelector("svg.trend");
  const tip = plot.querySelector(".trend-tip");
  const points = svg ? [...svg.querySelectorAll(".trend-pt")] : [];
  if (!tip || !points.length) return;
  let active = -1;

  function show(i) {
    if (active >= 0) points[active].classList.remove("is-active");
    active = i;
    const pt = points[i];
    pt.classList.add("is-active");
    const day = new Date(pt.dataset.date + "T00:00:00Z");
    tip.innerHTML = "";
    const price = document.createElement("b");
    price.textContent = money(pt.dataset.price);
    tip.append(price, DATE.format(day));
    tip.hidden = false;
    // Place the tip over the marker, kept inside the plot so it never widens the page.
    const box = plot.getBoundingClientRect();
    const mark = pt.getBoundingClientRect();
    const half = tip.offsetWidth / 2;
    const x = Math.min(Math.max(mark.left + mark.width / 2 - box.left, half), box.width - half);
    tip.style.left = `${x}px`;
    tip.style.top = `${mark.top - box.top}px`;
  }

  function hide() {
    if (active >= 0) points[active].classList.remove("is-active");
    active = -1;
    tip.hidden = true;
  }

  function nearest(clientX) {
    let best = 0;
    let gap = Infinity;
    points.forEach((pt, i) => {
      const r = pt.getBoundingClientRect();
      const d = Math.abs(r.left + r.width / 2 - clientX);
      if (d < gap) [best, gap] = [i, d];
    });
    return best;
  }

  svg.setAttribute("tabindex", "0");
  svg.setAttribute("aria-describedby", tip.id || (tip.id = "trend-tip"));
  svg.addEventListener("pointermove", (e) => show(nearest(e.clientX)));
  svg.addEventListener("pointerdown", (e) => show(nearest(e.clientX))); // a tap on a phone
  svg.addEventListener("pointerleave", (e) => {
    if (e.pointerType === "mouse") hide();
  });
  svg.addEventListener("focus", () => show(active >= 0 ? active : points.length - 1));
  svg.addEventListener("blur", hide);
  svg.addEventListener("keydown", (e) => {
    const last = points.length - 1;
    const step = { ArrowLeft: -1, ArrowRight: 1 }[e.key];
    if (step) show(Math.min(Math.max((active < 0 ? last : active) + step, 0), last));
    else if (e.key === "Home") show(0);
    else if (e.key === "End") show(last);
    else if (e.key === "Escape") hide();
    else return;
    e.preventDefault();
  });
  document.addEventListener("pointerdown", (e) => {
    if (!plot.contains(e.target)) hide();
  });
  plot.classList.add("is-live");
}

document.querySelectorAll(".trend-plot").forEach(init);
