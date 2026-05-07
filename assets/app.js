/* Indicadores INEGI · Runtime JS v3
   Reutiliza la lógica de app.js (renderDetailChart, renderBarHorizontal, drilldowns)
   y agrega: sparklines en tabla home v3, filtro por buscador.
   Carga app.js como dependencia mediante import dinámico inline. */

const COLORS_V3 = {
  navy: "#18181B", teal: "#0891B2", tealAlpha: "rgba(8,145,178,0.10)",
  magenta: "#7C3AED", magentaAlpha: "rgba(124,58,237,0.06)",
  orange: "#D97706", wine: "#DC2626", green: "#16A34A", gold: "#D97706", gray: "#71717A"
};

function v3SparkColor(dir) {
  if (dir === "up") return COLORS_V3.green;
  if (dir === "down") return COLORS_V3.wine;
  return COLORS_V3.navy;
}

function v3RenderTblSpark(canvasId, serie, color) {
  const canvas = document.getElementById(canvasId);
  if (!canvas || !window.Chart || !serie) return;
  const cleaned = serie.filter(x => x !== null && x !== undefined);
  if (cleaned.length < 2) return;
  new Chart(canvas.getContext("2d"), {
    type: "line",
    data: {
      labels: serie.map((_, i) => i),
      datasets: [{
        data: serie, borderColor: color, borderWidth: 1.6,
        tension: 0.25, pointRadius: 0, fill: false, spanGaps: true
      }]
    },
    options: {
      responsive: false, maintainAspectRatio: false, animation: false,
      plugins: { legend: { display: false }, tooltip: { enabled: false } },
      scales: { x: { display: false }, y: { display: false } }
    }
  });
}

function v3WireTblFilter() {
  const search = document.getElementById("tbl-search-v3");
  const catSelect = document.getElementById("tbl-cat-filter");
  const tbl = document.getElementById("indic-tbl-v3");
  if (!tbl) return;
  const rows = tbl.querySelectorAll("tbody tr");

  function applyFilters() {
    const q = search ? search.value.trim().toLowerCase() : "";
    const cat = catSelect ? catSelect.value.toLowerCase() : "";
    rows.forEach(tr => {
      const nombre = tr.dataset.nombre || "";
      const trCat = tr.dataset.categoria || "";
      const matchQ = !q || nombre.includes(q);
      const matchCat = !cat || trCat === cat;
      tr.style.display = (matchQ && matchCat) ? "" : "none";
    });
  }

  if (search) search.addEventListener("input", applyFilters);
  if (catSelect) catSelect.addEventListener("change", applyFilters);
}

/* Accesibilidad de teclado: tabindex + Enter/Space en filas de tabla clickeables */
function v3WireTblKeyboard() {
  const tbl = document.getElementById("indic-tbl-v3");
  if (!tbl) return;
  const rows = tbl.querySelectorAll("tbody tr[onclick]");
  rows.forEach(tr => {
    tr.setAttribute("tabindex", "0");
    tr.setAttribute("role", "row");
    tr.addEventListener("keydown", e => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        // Extraer href del onclick attr: location.href='...'
        const match = (tr.getAttribute("onclick") || "").match(/location\.href=['"]([^'"]+)['"]/);
        if (match) window.location.href = match[1];
      }
    });
  });
}

/* Render charts de detalle (reutilizado de app.js) */
function v3RenderDetailChart(canvas, d) {
  if (!canvas || !window.Chart) return;
  const firstSeries = Object.values(d.series || {})[0] || [];
  const validPoints = firstSeries.filter(x => x !== null && x !== undefined);
  if (validPoints.length < 2) {
    const container = canvas.parentElement;
    if (container) {
      container.innerHTML =
        '<div style="height:300px;display:flex;align-items:center;justify-content:center;flex-direction:column;color:#7A7A7A;font-size:13px">' +
        '<strong style="color:#1A1A1A;font-size:15px;margin-bottom:8px">Serie insuficiente</strong>' +
        'Solo ' + validPoints.length + ' punto disponible. Ver tabla debajo.' +
        '</div>';
    }
    return;
  }
  const ctx = canvas.getContext("2d");
  const seriesEntries = Object.entries(d.series || {});
  const nPuntos = firstSeries.length;
  const pointR = nPuntos > 20 ? 0 : (nPuntos > 10 ? 2 : 3);
  const paletteLines = [COLORS_V3.teal, COLORS_V3.magenta, COLORS_V3.orange];
  const paletteFills = [COLORS_V3.tealAlpha, COLORS_V3.magentaAlpha, "transparent"];
  const datasets = seriesEntries.map(([name, vals], i) => ({
    label: name, data: vals,
    borderColor: paletteLines[i % paletteLines.length],
    backgroundColor: paletteFills[i % paletteFills.length],
    tension: 0.25, borderWidth: 2.8, pointRadius: pointR, pointHoverRadius: pointR + 2,
    fill: i === 0, spanGaps: true
  }));
  if (d.ma12) {
    datasets.push({
      label: "MA12", data: d.ma12,
      borderColor: COLORS_V3.navy, borderDash: [6, 4],
      borderWidth: 1.5, pointRadius: 0, fill: false, spanGaps: true
    });
  }
  // Construir anotaciones (banda benchmark + eventos macro)
  const annotations = {};
  if (d.benchmark) {
    const b = d.benchmark;
    if (b.tipo === "banda" && b.y_min !== undefined && b.y_max !== undefined) {
      annotations["benchmark_band"] = {
        type: "box", yMin: b.y_min, yMax: b.y_max,
        backgroundColor: b.color || "rgba(30,91,79,0.10)",
        borderColor: b.border || "#1E5B4F",
        borderWidth: 1, borderDash: [4, 4],
        label: { display: !!b.label, content: b.label, position: "start", color: b.border || "#1E5B4F", font: { size: 10, weight: "600" }, backgroundColor: "rgba(255,255,255,0.85)", padding: 4 }
      };
    } else if (b.tipo === "linea" && b.y !== undefined) {
      annotations["benchmark_line"] = {
        type: "line", yMin: b.y, yMax: b.y,
        borderColor: b.color || "#7A7A7A",
        borderWidth: 1, borderDash: [3, 3],
        label: { display: !!b.label, content: b.label, position: "end", color: b.color || "#7A7A7A", font: { size: 10, weight: "600" }, backgroundColor: "rgba(255,255,255,0.85)", padding: 4 }
      };
    }
  }
  if (d.eventos_macro && d.eventos_macro.length) {
    d.eventos_macro.forEach((ev, i) => {
      annotations["evento_" + i] = {
        type: "line",
        xMin: ev.periodo, xMax: ev.periodo,
        borderColor: ev.color || "#9B2247",
        borderWidth: 1, borderDash: [2, 4],
        label: { display: false, content: ev.label, font: { size: 10 } }
      };
    });
  }

  return new Chart(ctx, {
    type: "line",
    data: { labels: d.periodos, datasets },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { position: "bottom", labels: { boxWidth: 12, boxHeight: 3, font: { size: 11 }, color: COLORS_V3.navy }},
        tooltip: {
          backgroundColor: COLORS_V3.navy, padding: 10,
          titleFont: { size: 12 }, bodyFont: { size: 12 },
          filter: item => item.parsed.y !== null && item.parsed.y !== undefined,
          callbacks: { label: c => c.parsed.y === null ? null : `${c.dataset.label}: ${c.parsed.y.toFixed(2)}${d.unidad || ""}` }
        },
        annotation: { annotations }
      },
      scales: {
        x: { grid: { display: false }, ticks: { font: { size: 11 }, color: COLORS_V3.navy }},
        y: { grid: { color: "rgba(0,48,87,0.08)" }, ticks: { font: { size: 11 }, color: COLORS_V3.navy, callback: v => v + (d.unidad || "") }}
      }
    }
  });
}

function v3RenderBarHorizontal(canvas, d) {
  if (!canvas || !window.Chart) return;
  const labels = d.bar_labels || [];
  const values = d.bar_values || [];
  if (labels.length === 0) return;
  const ctx = canvas.getContext("2d");
  const unit = d.bar_unit || "";
  const fmt = unit === " MDD" ? (v => v !== null ? v.toLocaleString("es-MX") + unit : "—") : (v => v !== null ? v + unit : "—");
  // Diverging: teal para positivo, magenta para negativo
  const bgColors = d.bar_diverging
    ? values.map(v => (v !== null && v >= 0) ? COLORS_V3.teal : COLORS_V3.magenta)
    : COLORS_V3.teal;
  const extras = d.bar_diverging
    ? { annotation: { annotations: { zero: { type: "line", xMin: 0, xMax: 0, borderColor: COLORS_V3.navy, borderWidth: 1 } } } }
    : {};
  return new Chart(ctx, {
    type: "bar",
    data: {
      labels,
      datasets: [{ data: values, backgroundColor: bgColors, borderColor: "transparent", borderWidth: 0, borderRadius: 2 }]
    },
    options: {
      indexAxis: "y", responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: { backgroundColor: COLORS_V3.navy, callbacks: { label: c => fmt(c.parsed.x) }},
        ...extras
      },
      scales: {
        x: { grid: { color: "rgba(0,48,87,0.08)" }, ticks: { font: { size: 11 }, color: COLORS_V3.navy, callback: fmt }},
        y: { grid: { display: false }, ticks: { font: { size: 11 }, color: COLORS_V3.navy, autoSkip: false }}
      }
    }
  });
}

function v3RenderMultiSeries(canvas, periodos, seriesObj, opts) {
  if (!canvas || !window.Chart) return null;
  const cfg = opts || {};
  const palette = [
    COLORS_V3.teal, COLORS_V3.magenta, COLORS_V3.orange, COLORS_V3.navy,
    COLORS_V3.gold, COLORS_V3.green, COLORS_V3.wine
  ];
  const datasets = [];
  let i = 0;
  for (const [name, vals] of Object.entries(seriesObj)) {
    if (!vals || vals.every(x => x === null || x === undefined)) continue;
    datasets.push({
      label: name, data: vals,
      borderColor: palette[i % palette.length],
      backgroundColor: cfg.fill ? (palette[i % palette.length] + "22") : "transparent",
      borderWidth: 2.0, tension: 0.25,
      pointRadius: periodos.length > 30 ? 0 : 2,
      fill: cfg.fill || false, spanGaps: true
    });
    i++;
  }
  return new Chart(canvas.getContext("2d"), {
    type: "line",
    data: { labels: periodos, datasets },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { position: "bottom", labels: { boxWidth: 10, boxHeight: 3, font: { size: 11 }, color: COLORS_V3.navy }},
        tooltip: { backgroundColor: COLORS_V3.navy, padding: 10 }
      },
      scales: {
        x: { grid: { display: false }, ticks: { font: { size: 10 }, color: COLORS_V3.navy, maxRotation: 0, autoSkipPadding: 8 }},
        y: { grid: { color: "rgba(0,48,87,0.08)" }, ticks: { font: { size: 10 }, color: COLORS_V3.navy, callback: v => v + (cfg.unidad || "") }}
      }
    }
  });
}

/* ─── Grupo A: Bar vertical con color pos/neg ─── */
function v3RenderBarVertical(canvas, d) {
  if (!canvas || !window.Chart) return;
  const labels = d.periodos || [];
  const values = (d.series && Object.values(d.series)[0]) || [];
  if (!labels.length) return;
  const colors = values.map(v => (v !== null && v >= 0) ? COLORS_V3.teal : COLORS_V3.magenta);
  const unit = d.unidad || "";
  return new Chart(canvas.getContext("2d"), {
    type: "bar",
    data: {
      labels,
      datasets: [{ data: values, backgroundColor: colors, borderRadius: 3, borderSkipped: false }]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: COLORS_V3.navy, padding: 10, titleFont: { size: 12 }, bodyFont: { size: 12 },
          callbacks: { label: c => (c.parsed.y !== null ? (c.parsed.y > 0 ? "+" : "") + c.parsed.y + unit : "—") }
        },
        annotation: { annotations: {
          zero: { type: "line", yMin: 0, yMax: 0, borderColor: COLORS_V3.navy, borderWidth: 1 }
        }}
      },
      scales: {
        x: { grid: { display: false }, ticks: { font: { size: 11 }, color: COLORS_V3.navy } },
        y: { grid: { color: "rgba(0,48,87,0.08)" }, ticks: { font: { size: 11 }, color: COLORS_V3.navy, callback: v => v + unit } }
      }
    }
  });
}

/* ─── Grupo A/B: Grouped bar ─── */
function v3RenderBarGrouped(canvas, d) {
  if (!canvas || !window.Chart) return;
  const labels = d.periodos || [];
  const grouped = d.grouped_series || {};
  if (!labels.length || !Object.keys(grouped).length) return;
  const palette = [COLORS_V3.teal, COLORS_V3.magenta, COLORS_V3.navy, COLORS_V3.orange, COLORS_V3.gold];
  const unit = d.unidad || "";
  const datasets = Object.entries(grouped).map(([name, vals], i) => ({
    label: name, data: vals,
    backgroundColor: palette[i % palette.length],
    borderRadius: 2, borderSkipped: false
  }));
  return new Chart(canvas.getContext("2d"), {
    type: "bar",
    data: { labels, datasets },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { position: "bottom", labels: { boxWidth: 12, boxHeight: 3, font: { size: 11 }, color: COLORS_V3.navy } },
        tooltip: {
          backgroundColor: COLORS_V3.navy, padding: 10,
          callbacks: { label: c => c.dataset.label + ": " + (c.parsed.y !== null ? (c.parsed.y > 0 ? "+" : "") + c.parsed.y + unit : "—") }
        },
        annotation: { annotations: {
          zero: { type: "line", yMin: 0, yMax: 0, borderColor: COLORS_V3.navy, borderWidth: 1 }
        }}
      },
      scales: {
        x: { grid: { display: false }, ticks: { font: { size: 11 }, color: COLORS_V3.navy } },
        y: { grid: { color: "rgba(0,48,87,0.08)" }, ticks: { font: { size: 11 }, color: COLORS_V3.navy, callback: v => v + unit } }
      }
    }
  });
}

/* ─── Grupo E: Grouped horizontal bar (imai_estatal) ─── */
function v3RenderBarGroupedHorizontal(canvas, d) {
  if (!canvas || !window.Chart) return;
  const labels = d.bar_labels || [];
  const datasets_raw = d.bar_datasets || [];
  if (!labels.length || !datasets_raw.length) return;
  const palette = [COLORS_V3.teal, COLORS_V3.magenta];
  const datasets = datasets_raw.map((ds, i) => ({
    label: ds.label, data: ds.values,
    backgroundColor: palette[i % palette.length], borderRadius: 2
  }));
  return new Chart(canvas.getContext("2d"), {
    type: "bar",
    data: { labels, datasets },
    options: {
      indexAxis: "y", responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { position: "bottom", labels: { boxWidth: 10, boxHeight: 3, font: { size: 11 }, color: COLORS_V3.navy } },
        tooltip: { backgroundColor: COLORS_V3.navy }
      },
      scales: {
        x: { grid: { color: "rgba(0,48,87,0.08)" }, ticks: { font: { size: 10 }, color: COLORS_V3.navy } },
        y: { grid: { display: false }, ticks: { font: { size: 10 }, color: COLORS_V3.navy, autoSkip: false } }
      }
    }
  });
}

/* ─── Grupo C: Radar de componentes (actual vs 12m atrás) ─── */
function v3RenderRadar(canvas, radar) {
  if (!canvas || !window.Chart || !radar) return;
  const { labels, current, prev, periodo_actual, periodo_prev } = radar;
  if (!labels || !labels.length) return;
  return new Chart(canvas.getContext("2d"), {
    type: "radar",
    data: {
      labels,
      datasets: [
        {
          label: periodo_actual || "Actual",
          data: current,
          borderColor: COLORS_V3.teal, backgroundColor: COLORS_V3.tealAlpha,
          borderWidth: 2.5, pointRadius: 4, pointBackgroundColor: COLORS_V3.teal
        },
        {
          label: periodo_prev || "Hace 12m",
          data: prev,
          borderColor: COLORS_V3.magenta, backgroundColor: COLORS_V3.magentaAlpha,
          borderWidth: 2, pointRadius: 3, borderDash: [4, 3], pointBackgroundColor: COLORS_V3.magenta
        }
      ]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { position: "bottom", labels: { boxWidth: 10, boxHeight: 3, font: { size: 11 }, color: COLORS_V3.navy } },
        tooltip: { backgroundColor: COLORS_V3.navy, padding: 10 }
      },
      scales: {
        r: {
          ticks: { font: { size: 10 }, color: COLORS_V3.navy, backdropColor: "transparent" },
          grid: { color: "rgba(0,48,87,0.12)" },
          pointLabels: { font: { size: 11 }, color: COLORS_V3.navy },
          angleLines: { color: "rgba(0,48,87,0.15)" }
        }
      }
    }
  });
}

/* ─── Grupo D: Heatmap año×mes via canvas nativo ─── */
function v3RenderHeatmap(container, heatmap) {
  if (!container || !heatmap) return;
  const { years, months, grid } = heatmap;
  if (!years || !months || !grid) return;

  // Recoger todos los valores válidos para escala de color
  const allVals = [];
  years.forEach(yr => months.forEach(m => {
    const v = (grid[yr] || {})[m];
    if (v !== null && v !== undefined) allVals.push(v);
  }));
  if (!allVals.length) return;
  const vMin = Math.min(...allVals);
  const vMax = Math.max(...allVals);

  // Paleta: azul claro → amarillo → naranja → rojo (buena para inflación)
  function colorFor(v) {
    if (v === null || v === undefined) return "#e8e8e8";
    const t = Math.max(0, Math.min(1, (v - vMin) / (vMax - vMin || 1)));
    // 0→#D9EFF5 (azul suave), 0.33→#FFF3B0 (amarillo), 0.66→#E26C3B (naranja), 1→#9B2247 (vino)
    const stops = [[217,239,245],[255,243,176],[226,108,59],[155,34,71]];
    const seg = t * (stops.length - 1);
    const lo = Math.floor(seg), hi = Math.min(stops.length - 1, lo + 1);
    const f = seg - lo;
    const r = Math.round(stops[lo][0] + f * (stops[hi][0] - stops[lo][0]));
    const g = Math.round(stops[lo][1] + f * (stops[hi][1] - stops[lo][1]));
    const b = Math.round(stops[lo][2] + f * (stops[hi][2] - stops[lo][2]));
    return `rgb(${r},${g},${b})`;
  }

  // Construir tabla HTML
  const nCols = months.length;
  const cellW = Math.max(28, Math.floor((container.offsetWidth - 80) / nCols));
  let html = '<div style="overflow-x:auto"><table class="heatmap-tbl" style="border-collapse:collapse;font-size:10px">';
  html += '<thead><tr><th style="width:48px;text-align:right;padding-right:6px;color:' + COLORS_V3.navy + '"></th>';
  months.forEach(m => {
    html += `<th style="width:${cellW}px;text-align:center;color:${COLORS_V3.navy};font-weight:500;padding:2px 1px">${m}</th>`;
  });
  html += '</tr></thead><tbody>';
  years.forEach(yr => {
    html += `<tr><td style="text-align:right;padding-right:6px;color:${COLORS_V3.navy};font-weight:500;white-space:nowrap">${yr}</td>`;
    months.forEach(m => {
      const v = (grid[yr] || {})[m];
      const bg = colorFor(v);
      const txt = (v !== null && v !== undefined) ? v.toFixed(1) : "";
      const textColor = (v !== null && v !== undefined && (v - vMin) / (vMax - vMin || 1) > 0.6) ? "#fff" : COLORS_V3.navy;
      html += `<td title="${yr} ${m}: ${txt}%" style="background:${bg};text-align:center;padding:3px 1px;color:${textColor}">${txt}</td>`;
    });
    html += '</tr>';
  });
  html += '</tbody></table></div>';

  // Leyenda
  html += `<div style="display:flex;align-items:center;gap:8px;margin-top:8px;font-size:10px;color:${COLORS_V3.navy}">`;
  html += `<span>Mín ${vMin.toFixed(1)}%</span>`;
  html += '<div style="flex:1;height:8px;border-radius:4px;background:linear-gradient(to right,#D9EFF5,#FFF3B0,#E26C3B,#9B2247)"></div>';
  html += `<span>Máx ${vMax.toFixed(1)}%</span></div>`;

  container.innerHTML = html;
}

/* Búsqueda global del topbar */
async function v3InitSearch() {
  const input = document.getElementById("global-search");
  const results = document.getElementById("global-search-results");
  const wrap = document.getElementById("topbar-search");
  if (!input || !results || !wrap) return;

  // Detectar prefix de assets para fetch index (relativo según ubicación)
  const isDetail = location.pathname.includes("/indicador/");
  const idxPath = (isDetail ? "../" : "") + "data/search-index.json";
  let index = [];
  try {
    const r = await fetch(idxPath);
    if (r.ok) index = await r.json();
  } catch (e) { return; }

  function score(item, q) {
    const ql = q.toLowerCase();
    const nl = item.nombre.toLowerCase();
    const il = item.id.toLowerCase();
    const kw = (item.keywords || []).join(" ").toLowerCase();
    if (nl.startsWith(ql) || il.startsWith(ql)) return 3;
    if (nl.includes(ql) || il.includes(ql)) return 2;
    if (kw.includes(ql)) return 1;
    return 0;
  }

  let activeIdx = -1;
  function render(matches) {
    if (!matches.length) {
      results.innerHTML = '<div class="search-empty">Sin resultados</div>';
      results.classList.add("open");
      return;
    }
    results.innerHTML = matches.slice(0, 12).map((m, i) => {
      const initial = m.nombre.charAt(0).toUpperCase();
      const url = (isDetail ? "../" : "") + m.url;
      return `<a class="search-result${i === activeIdx ? " active" : ""}" href="${url}" data-idx="${i}">
        <div class="search-result-icon">${initial}</div>
        <div class="search-result-body">
          <div class="search-result-title">${m.nombre}</div>
          <div class="search-result-cat">${m.categoria || ""}${m.unidad ? " · " + m.unidad : ""}</div>
        </div>
      </a>`;
    }).join("");
    results.classList.add("open");
  }

  function search(q) {
    if (!q || q.length < 1) {
      results.classList.remove("open");
      return;
    }
    const scored = index.map(it => ({ ...it, _s: score(it, q) })).filter(it => it._s > 0);
    scored.sort((a, b) => b._s - a._s);
    activeIdx = -1;
    render(scored);
  }

  input.addEventListener("input", e => search(e.target.value.trim()));
  input.addEventListener("focus", () => {
    if (input.value.trim()) search(input.value.trim());
  });
  document.addEventListener("click", e => {
    if (!wrap.contains(e.target)) results.classList.remove("open");
  });
  input.addEventListener("keydown", e => {
    const items = results.querySelectorAll(".search-result");
    if (e.key === "ArrowDown") {
      e.preventDefault();
      activeIdx = Math.min(activeIdx + 1, items.length - 1);
      items.forEach((el, i) => el.classList.toggle("active", i === activeIdx));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      activeIdx = Math.max(activeIdx - 1, 0);
      items.forEach((el, i) => el.classList.toggle("active", i === activeIdx));
    } else if (e.key === "Enter" && activeIdx >= 0 && items[activeIdx]) {
      e.preventDefault();
      window.location.href = items[activeIdx].href;
    } else if (e.key === "Escape") {
      results.classList.remove("open");
      input.blur();
    }
  });
  // Atajo "/" para enfocar
  document.addEventListener("keydown", e => {
    if (e.key === "/" && !["INPUT", "TEXTAREA"].includes(document.activeElement.tagName)) {
      e.preventDefault();
      input.focus();
    }
  });
}

/* Glossary tooltips: detecta acrónimos en el DOM y agrega tooltip al hover */
async function v3InitGlossary() {
  const isDetail = location.pathname.includes("/indicador/");
  const path = (isDetail ? "../" : "") + "data/glossary.json";
  let gloss = {};
  try {
    const r = await fetch(path);
    if (r.ok) {
      const j = await r.json();
      gloss = j.terminos || {};
    }
  } catch (e) { return; }
  if (!Object.keys(gloss).length) return;

  // Selectores donde buscar términos (texto plano que tiene acrónimos visibles)
  const selectors = [
    ".kpi-label", ".kpi-unidad-label", ".pub-nombre", ".indic-tbl td",
    ".detail-meta", ".analytics-card h4", ".drilldown-head h3",
    ".stat-card .nota", ".stat-card .label", ".kpi-delta-text"
  ];
  // Patrón: palabra completa que coincide exactamente con clave del glossary (case-insensitive)
  const terms = Object.keys(gloss);
  const pattern = new RegExp("\\b(" + terms.map(t => t.replace(/[.*+?^${}()|[\\]\\\\]/g, "\\$&")).join("|") + ")\\b", "gi");

  selectors.forEach(sel => {
    document.querySelectorAll(sel).forEach(el => {
      if (el.dataset.glossDone) return;
      el.dataset.glossDone = "1";
      // Solo procesar nodos texto, no afectar HTML estructural
      const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT, null);
      const toReplace = [];
      let node;
      while ((node = walker.nextNode())) {
        if (node.nodeValue && pattern.test(node.nodeValue)) {
          pattern.lastIndex = 0;
          toReplace.push(node);
        }
      }
      toReplace.forEach(node => {
        const frag = document.createDocumentFragment();
        let last = 0;
        node.nodeValue.replace(pattern, (match, p1, offset) => {
          if (offset > last) frag.appendChild(document.createTextNode(node.nodeValue.slice(last, offset)));
          const span = document.createElement("span");
          span.className = "gloss-term";
          span.textContent = match;
          // Match case-insensitive: buscar definición
          const key = terms.find(t => t.toLowerCase() === match.toLowerCase());
          if (key) span.title = gloss[key];
          frag.appendChild(span);
          last = offset + match.length;
        });
        if (last < node.nodeValue.length) frag.appendChild(document.createTextNode(node.nodeValue.slice(last)));
        node.parentNode.replaceChild(frag, node);
      });
    });
  });
}

/* Selector de rango temporal en chart principal de detalle */
let _detailChartInstance = null;

function v3SliceRangePayload(ind, n) {
  // n = 0 significa "todo". n > 0 toma últimos n.
  if (n === 0 || !ind.periodos || ind.periodos.length <= n) return ind;
  const periodos = ind.periodos.slice(-n);
  const series = {};
  for (const [k, v] of Object.entries(ind.series || {})) {
    series[k] = (v || []).slice(-n);
  }
  const ma12 = (ind.ma12 || []).slice(-n);
  // Re-filtrar eventos macro a la ventana
  const eventos = (ind.eventos_macro || []).filter(ev => periodos.includes(ev.periodo));
  // Re-mapear índices
  const eventos_mapped = eventos.map(ev => ({ ...ev, indice: periodos.indexOf(ev.periodo) }));
  return { ...ind, periodos, series, ma12, eventos_macro: eventos_mapped };
}

function v3RenderDetailChartRanged(canvas, ind, rangeN) {
  if (_detailChartInstance) { _detailChartInstance.destroy(); _detailChartInstance = null; }
  const sliced = v3SliceRangePayload(ind, rangeN);
  _detailChartInstance = v3RenderDetailChart(canvas, sliced);
}

function v3WireRangePills() {
  const pills = document.querySelectorAll("#range-pills .range-pill");
  if (!pills.length) return;
  pills.forEach(p => {
    p.addEventListener("click", () => {
      pills.forEach(x => { x.classList.remove("active"); x.setAttribute("aria-pressed", "false"); });
      p.classList.add("active");
      p.setAttribute("aria-pressed", "true");
      const n = parseInt(p.dataset.range, 10);
      if (window._detailPayload && window._detailCanvas) {
        v3RenderDetailChartRanged(window._detailCanvas, window._detailPayload, n);
      }
    });
  });
  // Estado inicial: marcar el pill activo al cargar
  const active = document.querySelector("#range-pills .range-pill.active");
  pills.forEach(x => x.setAttribute("aria-pressed", x === active ? "true" : "false"));
}

/* Vista comparativa: comparativas curadas pre-armadas */
function v3InitComparar() {
  const dataRaw = document.getElementById("cmp-data");
  if (!dataRaw) return;
  let data;
  try { data = JSON.parse(dataRaw.textContent); } catch (e) { return; }
  const palette = [COLORS_V3.teal, COLORS_V3.wine, COLORS_V3.navy, COLORS_V3.orange, COLORS_V3.green, COLORS_V3.gold];

  function sortPeriodos(periodos) {
    function key(p) {
      const parts = p.split("-");
      if (parts.length !== 2) return [0, 0];
      const yy = parseInt(parts[1]);
      const yyy = yy <= 30 ? 2000 + yy : 1900 + yy;
      const head = parts[0];
      const meses = ["ene","feb","mar","abr","may","jun","jul","ago","sep","oct","nov","dic"];
      if (meses.includes(head.toLowerCase())) return [yyy, meses.indexOf(head.toLowerCase()) + 1];
      if (head.startsWith("T")) return [yyy, parseInt(head[1]) * 3];
      return [yyy, 0];
    }
    return periodos.sort((a, b) => {
      const [ay, am] = key(a), [by, bm] = key(b);
      return ay - by || am - bm;
    });
  }

  Object.entries(data).forEach(([cid, cmp]) => {
    const canvas = document.getElementById("cmp-chart-" + cid);
    if (!canvas || !window.Chart) return;
    if (!cmp.series || cmp.series.length === 0) return;

    // Alinear periodos: unión ordenada
    const setPer = new Set();
    cmp.series.forEach(s => (s.periodos || []).forEach(p => setPer.add(p)));
    const periodos = sortPeriodos(Array.from(setPer));

    const datasets = cmp.series.map((s, i) => {
      const map = new Map(s.periodos.map((p, idx) => [p, s.serie[idx]]));
      const aligned = periodos.map(p => map.has(p) ? map.get(p) : null);
      return {
        label: s.label,
        data: aligned,
        borderColor: palette[i % palette.length],
        backgroundColor: "transparent",
        borderWidth: 2,
        tension: 0.25,
        pointRadius: 0,
        pointHoverRadius: 3,
        spanGaps: true,
      };
    });

    // Anotaciones (banda Banxico, líneas de equilibrio)
    const annotations = {};
    if (cmp.benchmark) {
      const b = cmp.benchmark;
      if (b.tipo === "banda" && b.y_min !== undefined && b.y_max !== undefined) {
        annotations["bench"] = {
          type: "box", yMin: b.y_min, yMax: b.y_max,
          backgroundColor: "rgba(30,91,79,0.08)",
          borderColor: "#1E5B4F", borderWidth: 1, borderDash: [4, 4],
          label: { display: !!b.label, content: b.label, position: "start", color: "#1E5B4F", font: { size: 10, weight: "600" }, backgroundColor: "rgba(255,255,255,0.85)", padding: 4 }
        };
      } else if (b.tipo === "linea" && b.y !== undefined) {
        annotations["bench"] = {
          type: "line", yMin: b.y, yMax: b.y,
          borderColor: "#7A7A7A", borderWidth: 1, borderDash: [3, 3],
          label: { display: !!b.label, content: b.label, position: "end", color: "#7A7A7A", font: { size: 10, weight: "600" }, backgroundColor: "rgba(255,255,255,0.85)", padding: 4 }
        };
      }
    }

    new Chart(canvas.getContext("2d"), {
      type: "line",
      data: { labels: periodos, datasets },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: {
          legend: { position: "bottom", labels: { boxWidth: 10, boxHeight: 3, font: { size: 11 }, color: COLORS_V3.navy }},
          tooltip: { backgroundColor: COLORS_V3.navy, padding: 10, titleFont: { size: 12 }, bodyFont: { size: 12 }, callbacks: { label: c => `${c.dataset.label}: ${c.parsed.y === null ? "—" : c.parsed.y.toFixed(2)}${cmp.unidad || ""}` }},
          annotation: { annotations },
        },
        scales: {
          x: { grid: { display: false }, ticks: { font: { size: 10 }, color: COLORS_V3.navy, maxRotation: 0, autoSkipPadding: 12 }},
          y: { grid: { color: "rgba(0,48,87,0.08)" }, ticks: { font: { size: 10 }, color: COLORS_V3.navy, callback: v => v + (cmp.unidad || "") }}
        }
      }
    });
  });
}

// ── IMSS YoY charts ──────────────────────────────────────────────────────────

function imssRenderYoyArea(canvas, periodos, valores, opts) {
  if (!canvas || !window.Chart) return;
  const cfg = opts || {};
  const ctx = canvas.getContext("2d");
  const BLUE = "#4B7FD4", RED = "#B5262C";
  const BLUE_FILL = "rgba(75,127,212,0.18)", RED_FILL = "rgba(181,38,44,0.18)";
  const mini = cfg.mini || false;
  return new Chart(ctx, {
    type: "line",
    data: {
      labels: periodos,
      datasets: [{
        data: valores,
        borderColor: ctx2 => {
          const v = ctx2.parsed ? ctx2.parsed.y : 0;
          return v >= 0 ? BLUE : RED;
        },
        segment: {
          borderColor: ctx2 => ctx2.p1.parsed.y < 0 ? RED : BLUE,
        },
        backgroundColor: BLUE_FILL,
        fill: { target: { value: 0 }, above: BLUE_FILL, below: RED_FILL },
        tension: 0.35,
        pointRadius: 0,
        borderWidth: mini ? 1.5 : 2,
      }]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: mini ? { enabled: false } : {
          backgroundColor: "#003057",
          callbacks: { label: c => (c.parsed.y >= 0 ? "+" : "") + c.parsed.y.toFixed(1) + "%" }
        },
        annotation: { annotations: {
          zero: { type: "line", yMin: 0, yMax: 0, borderColor: "rgba(0,48,87,0.25)", borderWidth: 1, borderDash: [3, 3] }
        }}
      },
      scales: {
        x: {
          display: !mini,
          grid: { display: false },
          ticks: { font: { size: 10 }, color: "#555", maxTicksLimit: 8, maxRotation: 0 }
        },
        y: {
          display: !mini,
          grid: { color: "rgba(0,48,87,0.06)" },
          ticks: { font: { size: 10 }, color: "#555", callback: v => v + "%" }
        }
      }
    }
  });
}

function imssInitCharts(ind) {
  // Main YoY chart
  const mainCanvas = document.getElementById("imss-main-chart");
  if (mainCanvas && ind.imss_nac_yoy_periodos && ind.imss_nac_yoy_valores) {
    imssRenderYoyArea(mainCanvas, ind.imss_nac_yoy_periodos, ind.imss_nac_yoy_valores, { mini: false });
  }
  // Sector mini-charts
  document.querySelectorAll(".imss-sector-chart").forEach(canvas => {
    try {
      const periodos = JSON.parse(canvas.dataset.periodos || "[]");
      const valores  = JSON.parse(canvas.dataset.valores  || "[]");
      if (periodos.length && valores.length) {
        imssRenderYoyArea(canvas, periodos, valores, { mini: true });
      }
    } catch (e) { console.warn("IMSS sector chart parse error", e); }
  });
}

/* Cierra el dropdown de Indicadores al hacer click fuera (tablet/mobile nav) */
function v3WireNavDropdown() {
  const details = document.getElementById("nav-indicadores-details");
  if (!details) return;
  document.addEventListener("click", e => {
    if (details.open && !details.contains(e.target)) {
      details.open = false;
    }
  });
  // Cierra también con Escape
  document.addEventListener("keydown", e => {
    if (e.key === "Escape" && details.open) details.open = false;
  });
}

document.addEventListener("DOMContentLoaded", () => {
  v3InitSearch();
  v3InitGlossary();
  v3InitComparar();
  v3WireNavDropdown();
  // Sparks tabla home v3
  const raw = document.getElementById("page-data-v3");
  if (raw) {
    try {
      const sparks = JSON.parse(raw.textContent);
      Object.entries(sparks).forEach(([iid, p]) => {
        v3RenderTblSpark("spark-tbl-" + iid, p.serie36, v3SparkColor(p.dir));
      });
    } catch (e) { console.error("page-data-v3 inválido", e); }
  }
  v3WireTblFilter();
  v3WireTblKeyboard();

  // Pages detalle (reutilizan page-data inline)
  const detailRaw = document.getElementById("page-data");
  if (detailRaw) {
    let payload;
    try { payload = JSON.parse(detailRaw.textContent); } catch (e) { return; }
    if (payload.view === "detail") {
      // IMSS tiene su propio sistema de charts
      if (payload.indicador && payload.indicador.id === "empleo_imss") {
        imssInitCharts(payload.indicador);
      }
      const canvas = document.getElementById("detail-chart");
      if (canvas && payload.indicador) {
        const ind = payload.indicador;
        if (ind.chart_tipo === "bar_horizontal" && ind.bar_labels) {
          v3RenderBarHorizontal(canvas, ind);
        } else if (ind.chart_tipo === "bar_grouped_horizontal" && ind.bar_labels) {
          v3RenderBarGroupedHorizontal(canvas, ind);
        } else if (ind.chart_tipo === "bar_vertical" && ind.periodos) {
          v3RenderBarVertical(canvas, ind);
        } else if (ind.chart_tipo === "bar_grouped" && ind.grouped_series) {
          v3RenderBarGrouped(canvas, ind);
        } else if (!ind.tabular) {
          // Guardar payload para re-render al cambiar rango
          window._detailPayload = ind;
          window._detailCanvas = canvas;
          v3RenderDetailChartRanged(canvas, ind, 60);
          v3WireRangePills();
        }
        if (ind.drilldown) {
          const dd = ind.drilldown;
          const renderers = {
            "balanza_comercial": () => {
              v3RenderMultiSeries(document.getElementById("chart-balanza-saldos"), dd.periodos, dd.saldos, { unidad: " MDD" });
              v3RenderMultiSeries(document.getElementById("chart-balanza-exports"), dd.periodos, dd.export_composicion, { unidad: "%" });
              v3RenderMultiSeries(document.getElementById("chart-balanza-imports"), dd.periodos, dd.import_tipo, { unidad: "%", fill: true });
            },
            "inpc_mensual": () => {
              v3RenderMultiSeries(document.getElementById("chart-inpc-general"), dd.periodos, dd.general_vs_subyacente_anual, { unidad: "%" });
              v3RenderMultiSeries(document.getElementById("chart-inpc-subyacente"), dd.periodos, dd.subyacente_partido_anual, { unidad: "%" });
              v3RenderMultiSeries(document.getElementById("chart-inpc-no-subyacente"), dd.periodos, dd.no_subyacente_partido_anual, { unidad: "%" });
              if (dd.heatmap) v3RenderHeatmap(document.getElementById("chart-inpc-heatmap"), dd.heatmap);
            },
            "inpc_quincenal": () => {
              if (dd.heatmap) v3RenderHeatmap(document.getElementById("chart-inpc-quincenal-heatmap"), dd.heatmap);
            },
            "pib_trimestral": () => {
              v3RenderMultiSeries(document.getElementById("chart-pib-actividades"), dd.periodos, dd.actividades_anual, { unidad: "%" });
              v3RenderMultiSeries(document.getElementById("chart-pib-secundarias"), dd.periodos, dd.secundarias_anual, { unidad: "%" });
              v3RenderMultiSeries(document.getElementById("chart-pib-terciarias"), dd.periodos, dd.terciarias_anual, { unidad: "%" });
              v3RenderMultiSeries(document.getElementById("chart-pib-demanda"), dd.periodos, dd.demanda_anual, { unidad: "%" });
            },
            "igae": () => {
              v3RenderMultiSeries(document.getElementById("chart-igae-actividades"), dd.periodos, dd.actividades, { unidad: "%" });
              v3RenderMultiSeries(document.getElementById("chart-igae-secundarias"), dd.periodos, dd.secundarias, { unidad: "%" });
              v3RenderMultiSeries(document.getElementById("chart-igae-terciarias"), dd.periodos, dd.terciarias, { unidad: "%" });
            },
            "actividad_industrial": () => {
              v3RenderMultiSeries(document.getElementById("chart-actind-sectores"), dd.periodos, dd.sectores, { unidad: "%" });
              v3RenderMultiSeries(document.getElementById("chart-actind-manuf"), dd.periodos, dd.subsectores_manuf, { unidad: "%" });
            },
            "consumo_privado": () => {
              v3RenderMultiSeries(document.getElementById("chart-consumo-origen"), dd.periodos, dd.origen, { unidad: "%" });
              v3RenderMultiSeries(document.getElementById("chart-consumo-tipo-nacional"), dd.periodos, dd.tipo_bien_nacional, { unidad: "%" });
              v3RenderMultiSeries(document.getElementById("chart-consumo-tipo-importado"), dd.periodos, dd.tipo_bien_importado, { unidad: "%" });
            },
            "confianza_consumidor": () => {
              v3RenderMultiSeries(document.getElementById("chart-icc-componentes"), dd.periodos, dd.componentes, { unidad: "pp" });
              if (dd.radar) v3RenderRadar(document.getElementById("chart-icc-radar"), dd.radar);
            },
            "emoe_ipm": () => {
              v3RenderMultiSeries(document.getElementById("chart-ipm-componentes"), dd.periodos, dd.componentes, { unidad: "pp" });
              if (dd.radar) v3RenderRadar(document.getElementById("chart-ipm-radar"), dd.radar);
            },
            "emoe_ice": () => {
              v3RenderMultiSeries(document.getElementById("chart-ice-sectores"), dd.periodos, dd.sectores, { unidad: "pp" });
              if (dd.radar) v3RenderRadar(document.getElementById("chart-ice-radar"), dd.radar);
            },
            "emoe_iat": () => v3RenderMultiSeries(document.getElementById("chart-iat-sectores"), dd.periodos, dd.sectores, { unidad: "pp" }),
            "fbcf": () => {
              v3RenderMultiSeries(document.getElementById("chart-fbcf-totales"), dd.periodos, dd.totales, { unidad: "%" });
              v3RenderMultiSeries(document.getElementById("chart-fbcf-construccion"), dd.periodos, dd.construccion_partida, { unidad: "%" });
              v3RenderMultiSeries(document.getElementById("chart-fbcf-maquinaria"), dd.periodos, dd.maquinaria_partida, { unidad: "%" });
            },
            "enoe_mensual": () => {
              v3RenderMultiSeries(document.getElementById("chart-enoe-desocupacion"), dd.periodos, dd.desocupacion, { unidad: "%" });
              v3RenderMultiSeries(document.getElementById("chart-enoe-participacion"), dd.periodos, dd.participacion, { unidad: "%" });
              v3RenderMultiSeries(document.getElementById("chart-enoe-informalidad"), dd.periodos, dd.informalidad_subocupacion, { unidad: "%" });
            },
            "enec": () => v3RenderMultiSeries(document.getElementById("chart-enec-obras"), dd.periodos, dd.obras, { unidad: "%" }),
            "comercio_mayoreo": () => v3RenderMultiSeries(document.getElementById("chart-mayoreo-ramas"), dd.periodos, dd.ramas, { unidad: "%" }),
            "comercio_menudeo": () => v3RenderMultiSeries(document.getElementById("chart-menudeo-sectores"), dd.periodos, dd.sectores, { unidad: "%" }),
            "servicios": () => v3RenderMultiSeries(document.getElementById("chart-servicios-subsectores"), dd.periodos, dd.sectores, { unidad: "%" }),
            "autos_ligeros": () => v3RenderMultiSeries(document.getElementById("chart-autos-series"), dd.periodos, dd.series, { unidad: "%" }),
            "autos_pesados": () => v3RenderMultiSeries(document.getElementById("chart-autos-series"), dd.periodos, dd.series, { unidad: "%" }),
          };
          const r = renderers[dd.tipo];
          if (r) r();
        }
      }
    }
  }

  // Toggle estadísticos avanzados
  const advBtn = document.getElementById("adv-toggle-btn");
  const analyticsGrid = document.getElementById("analytics-grid");
  if (advBtn && analyticsGrid) {
    advBtn.addEventListener("click", () => {
      const visible = analyticsGrid.classList.toggle("adv-visible");
      advBtn.textContent = visible ? "Ocultar avanzados" : "Ver avanzados";
      advBtn.setAttribute("aria-expanded", visible ? "true" : "false");
    });
  }

  // Validador de fecha de próxima publicación
  const pubCard = document.getElementById("proxima-pub-card");
  if (pubCard) {
    const isoDate = pubCard.dataset.nextDate;
    if (isoDate) {
      const expected = new Date(isoDate);
      const today = new Date();
      today.setHours(0, 0, 0, 0);
      if (today > expected) {
        const valEl = document.getElementById("proxima-pub-valor");
        const notaEl = document.getElementById("proxima-pub-nota");
        if (valEl) { valEl.textContent = "Pendiente"; valEl.style.color = "#DC2626"; }
        if (notaEl) { notaEl.innerHTML = '<a href="https://www.inegi.org.mx/calendario/" target="_blank" rel="noopener" style="color:inherit">Ver calendario INEGI</a>'; }
        pubCard.title = "La fecha estimada de publicación ya pasó. Consulta el calendario oficial de INEGI.";
      }
    }
  }
});
