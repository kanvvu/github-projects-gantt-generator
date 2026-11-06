#!/usr/bin/env python3
"""
Generuje interaktywny wykres Gantta (HTML + SVG) ze strzałkami zależności
(blocked_by / blocking oraz opcjonalnie parent -> sub-issue) oraz zwijaniem/rozwijaniem
drzewa WBS (podzadań) na podstawie pliku project_export.json.
"""

import json
import os
import sys


def generate_gantt_html(json_path: str = "project_export.json", output_html: str = "gantt_chart.html") -> str:
    if not os.path.exists(json_path):
        raise FileNotFoundError(f"Nie znaleziono pliku {json_path}. Uruchom najpierw export_github_project.py.")

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    embedded_json = json.dumps(data, ensure_ascii=False)

    html_content = f"""<!DOCTYPE html>
<html lang="pl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Wykres Gantta – {data.get('project', {}).get('title', 'GitHub Project')}</title>
<style>
  :root {{
    --bg: #ffffff;
    --surface: #f8fafc;
    --border: #e2e8f0;
    --border-strong: #cbd5e1;
    --text: #0f172a;
    --text-muted: #64748b;
    --etap-bar: #1e293b;
    --parent-bar: #2563eb;
    --leaf-bar: #3b82f6;
    --inferred-bar: #94a3b8;
    --dep-arrow: #f59e0b;
    --dep-arrow-hover: #d97706;
    --hier-arrow: #64748b;
    --row-hover: #f1f5f9;
  }}

  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Inter, sans-serif;
    background: var(--bg);
    color: var(--text);
    padding: 20px;
  }}

  .header {{
    display: flex;
    flex-wrap: wrap;
    justify-content: space-between;
    align-items: center;
    gap: 16px;
    padding-bottom: 16px;
    border-bottom: 1px solid var(--border);
    margin-bottom: 16px;
  }}
  .header h1 {{
    font-size: 20px;
    font-weight: 700;
  }}
  .header .subtitle {{
    font-size: 13px;
    color: var(--text-muted);
    margin-top: 4px;
  }}

  .controls {{
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    align-items: center;
  }}
  .control-group {{
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 13px;
    background: var(--surface);
    padding: 6px 10px;
    border: 1px solid var(--border);
    border-radius: 6px;
  }}
  select, button, input[type="checkbox"] {{
    font-size: 13px;
    cursor: pointer;
  }}
  select {{
    border: 1px solid var(--border-strong);
    border-radius: 4px;
    padding: 3px 6px;
    background: #fff;
  }}
  .btn {{
    background: #0f172a;
    color: #fff;
    border: none;
    padding: 6px 11px;
    border-radius: 6px;
    font-weight: 500;
    transition: background 0.15s, opacity 0.15s;
  }}
  .btn:hover {{ opacity: 0.9; }}
  .btn-secondary {{
    background: #fff;
    color: #0f172a;
    border: 1px solid var(--border-strong);
  }}
  .btn-secondary:hover {{
    background: #f1f5f9;
  }}
  .btn-sm {{
    padding: 4px 8px;
    font-size: 12px;
  }}

  .notice {{
    background: #fff7ed;
    border: 1px solid #fed7aa;
    color: #9a3412;
    padding: 10px 14px;
    border-radius: 6px;
    font-size: 13px;
    margin-bottom: 14px;
    display: none;
  }}

  .legend {{
    display: flex;
    flex-wrap: wrap;
    gap: 18px;
    font-size: 12px;
    color: var(--text-muted);
    margin-bottom: 14px;
    align-items: center;
  }}
  .legend-item {{
    display: flex;
    align-items: center;
    gap: 6px;
  }}
  .swatch {{
    width: 14px;
    height: 10px;
    border-radius: 3px;
    display: inline-block;
  }}
  .line-swatch {{
    width: 24px;
    height: 0;
    border-top: 2px solid var(--dep-arrow);
    display: inline-block;
    position: relative;
  }}

  .gantt-wrapper {{
    border: 1px solid var(--border-strong);
    border-radius: 8px;
    overflow: auto;
    background: #fff;
    box-shadow: 0 1px 3px rgba(0,0,0,0.04);
  }}

  .tree-toggle {{
    cursor: pointer;
    user-select: none;
  }}
  .tree-toggle:hover rect.toggle-hit {{
    fill: #e2e8f0;
  }}

  .deps-summary {{
    margin-top: 20px;
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 14px;
    background: var(--surface);
  }}
  .deps-summary h3 {{
    font-size: 14px;
    margin-bottom: 8px;
  }}
  .deps-list {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
    gap: 8px;
    font-size: 13px;
  }}
  .dep-card {{
    background: #fff;
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 8px 10px;
    display: flex;
    align-items: center;
    gap: 8px;
  }}
  .dep-arrow-badge {{
    color: var(--dep-arrow);
    font-weight: 700;
  }}

  #tooltip {{
    position: fixed;
    pointer-events: none;
    background: rgba(15, 23, 42, 0.95);
    color: #fff;
    padding: 10px 12px;
    border-radius: 6px;
    font-size: 12px;
    line-height: 1.45;
    z-index: 1000;
    display: none;
    max-width: 340px;
    box-shadow: 0 4px 12px rgba(0,0,0,0.2);
  }}

  @media print {{
    .controls, .notice {{ display: none !important; }}
    body {{ padding: 0; }}
    .gantt-wrapper {{ border: none; overflow: visible; }}
  }}
</style>
</head>
<body>

<div class="header">
  <div>
    <h1 id="project-title">Wykres Gantta</h1>
    <div class="subtitle" id="project-stats"></div>
  </div>
  <div class="controls">
    <div class="control-group">
      <span>Drzewo WBS:</span>
      <button class="btn btn-secondary btn-sm" onclick="expandAll()" title="Pokaż wszystkie poziomy podzadań">Rozwiń wszystko</button>
      <button class="btn btn-secondary btn-sm" onclick="collapseToDepth(1)" title="Pokaż Etapy i główne zadania (schowaj podzadania 3. i 4. poziomu)">Poziom 2 (Sekcje)</button>
      <button class="btn btn-secondary btn-sm" onclick="collapseToDepth(0)" title="Zwiń wszystko do samych Etapów głównych">Tylko Etapy</button>
    </div>
    <div class="control-group">
      <label for="filter-mode">Widok zadań:</label>
      <select id="filter-mode">
        <option value="dated_or_deps" selected>Z datami lub zależnościami</option>
        <option value="deps_only">Tylko powiązane zależnościami (strzałki)</option>
        <option value="all">Wszystkie zadania z projektu (pełny WBS)</option>
      </select>
    </div>
    <div class="control-group">
      <input type="checkbox" id="show-dep-arrows" checked>
      <label for="show-dep-arrows">Strzałki zależności (Blocked by / Blocking)</label>
    </div>
    <div class="control-group">
      <input type="checkbox" id="show-hier-arrows">
      <label for="show-hier-arrows">Strzałki hierarchii (Parent &rarr; Sub-issue)</label>
    </div>
    <div class="control-group">
      <label for="day-width">Skala:</label>
      <select id="day-width">
        <option value="18">Wąska (18px)</option>
        <option value="26" selected>Standardowa (26px)</option>
        <option value="38">Szeroka (38px)</option>
      </select>
    </div>
    <button class="btn btn-secondary" onclick="downloadSVG()">Pobierz SVG</button>
    <button class="btn" onclick="window.print()">Drukuj / PDF</button>
  </div>
</div>

<div id="missing-deps-notice" class="notice"></div>

<div class="legend">
  <div class="legend-item"><span class="swatch" style="background: var(--etap-bar)"></span> Etap (wyliczony z podzadań)</div>
  <div class="legend-item"><span class="swatch" style="background: var(--parent-bar)"></span> Zadanie nadrzędne (kliknij <strong>&#9660;/&#9654;</strong> przy nazwie, aby zwinąć/rozwinąć podzadania)</div>
  <div class="legend-item"><span class="swatch" style="background: var(--leaf-bar)"></span> Zadanie z datą Start / Target</div>
  <div class="legend-item"><span class="swatch" style="background: var(--inferred-bar)"></span> Data odziedziczona z rodzica/etapu</div>
  <div class="legend-item"><span class="line-swatch"></span> <strong>Strzałka zależności (Poprzednik &rarr; Następnik)</strong></div>
  <div class="legend-item"><span class="line-swatch" style="border-top: 2px dashed var(--hier-arrow)"></span> Strzałka WBS (Parent &rarr; Sub-issue)</div>
</div>

<div class="gantt-wrapper" id="gantt-container"></div>

<div class="deps-summary" id="deps-summary">
  <h3 id="deps-title">Wykryte zależności (strzałki)</h3>
  <div class="deps-list" id="deps-list"></div>
</div>

<div id="tooltip"></div>

<script>
const RAW_DATA = {embedded_json};

// Zbiór numerów zadań, które mają aktualnie zwinięte (schowane) podzadania
const collapsedNodes = new Set();

function parseDate(str) {{
  if (!str) return null;
  const [y, m, d] = str.split('-').map(Number);
  return new Date(Date.UTC(y, m - 1, d));
}}

function formatDate(dt) {{
  if (!dt) return '-';
  return dt.toISOString().slice(0, 10);
}}

function addDays(dt, days) {{
  return new Date(dt.getTime() + days * 86400000);
}}

function diffDays(a, b) {{
  return Math.round((b.getTime() - a.getTime()) / 86400000);
}}

function buildModel() {{
  const items = RAW_DATA.items || [];
  const byNum = new Map();
  items.forEach(it => {{
    if (it.number != null) byNum.set(it.number, it);
  }});

  // Zbierz krawędzie zależności (A -> B oznacza: A blokuje B / B jest zablokowane przez A)
  const depEdges = [];
  const depEdgeSet = new Set();
  const involvedInDeps = new Set();

  items.forEach(it => {{
    const rels = it.relationships || {{}};
    const blockedBy = rels.blocked_by || [];
    const blocking = rels.blocking || [];

    blockedBy.forEach(pred => {{
      if (pred && pred.number != null && byNum.has(pred.number)) {{
        const key = `${{pred.number}}->${{it.number}}`;
        if (!depEdgeSet.has(key)) {{
          depEdgeSet.add(key);
          depEdges.push({{ from: pred.number, to: it.number, type: 'dependency' }});
          involvedInDeps.add(pred.number);
          involvedInDeps.add(it.number);
        }}
      }}
    }});

    blocking.forEach(succ => {{
      if (succ && succ.number != null && byNum.has(succ.number)) {{
        const key = `${{it.number}}->${{succ.number}}`;
        if (!depEdgeSet.has(key)) {{
          depEdgeSet.add(key);
          depEdges.push({{ from: it.number, to: succ.number, type: 'dependency' }});
          involvedInDeps.add(it.number);
          involvedInDeps.add(succ.number);
        }}
      }}
    }});
  }});

  // Uporządkuj drzewo WBS (roots -> children)
  const childrenMap = new Map();
  const parentMap = new Map();
  items.forEach(it => {{
    const pNum = it.parent_issue ? it.parent_issue.number : null;
    if (pNum != null && byNum.has(pNum)) {{
      parentMap.set(it.number, pNum);
      if (!childrenMap.has(pNum)) childrenMap.set(pNum, []);
      childrenMap.get(pNum).push(it.number);
    }}
  }});

  // Policz łączną liczbę wszystkich potomków w poddrzewie (do badge'a [+N] po zwinięciu)
  const descendantCountMap = new Map();
  function countDescendants(num) {{
    const ch = childrenMap.get(num) || [];
    let total = 0;
    ch.forEach(c => {{
      total += 1 + countDescendants(c);
    }});
    descendantCountMap.set(num, total);
    return total;
  }}

  const roots = items
    .filter(it => !it.parent_issue || !byNum.has(it.parent_issue.number))
    .sort((a, b) => (a.number || 0) - (b.number || 0));

  roots.forEach(r => countDescendants(r.number));

  const ordered = [];
  const visited = new Set();

  function dfs(num, depth) {{
    if (visited.has(num)) return;
    visited.add(num);
    const it = byNum.get(num);
    if (!it) return;
    ordered.push({{ item: it, depth }});
    const ch = childrenMap.get(num) || [];
    ch.sort((a, b) => a - b);
    ch.forEach(c => dfs(c, depth + 1));
  }}

  roots.forEach(r => dfs(r.number, 0));
  items.forEach(it => {{
    if (!visited.has(it.number)) dfs(it.number, 0);
  }});

  // Wyznacz daty własne z GitHub Projects (Start date / Target date / End date)
  const dateInfo = new Map();
  items.forEach(it => {{
    const pf = it.project_fields || {{}};
    const s = parseDate(pf['Start date'] || pf['Start Date']);
    const e = parseDate(pf['Target date'] || pf['End date'] || pf['Target Date'] || pf['End Date']);
    if (s || e) {{
      const start = s || e;
      const end = (e && e >= start) ? e : start;
      dateInfo.set(it.number, {{ start, end, source: 'explicit' }});
    }}
  }});

  // Rollup: jeśli rodzic (np. Etap 1, Etap 2) nie ma własnych dat, wylicz min(start) i max(end) z potomków
  function computeRollup(num) {{
    const ch = childrenMap.get(num) || [];
    let minS = null;
    let maxE = null;
    ch.forEach(c => {{
      const sub = computeRollup(c);
      if (sub) {{
        if (!minS || sub.start < minS) minS = sub.start;
        if (!maxE || sub.end > maxE) maxE = sub.end;
      }}
    }});
    if (dateInfo.has(num)) {{
      return dateInfo.get(num);
    }}
    if (minS && maxE) {{
      const info = {{ start: minS, end: maxE, source: 'rollup' }};
      dateInfo.set(num, info);
      return info;
    }}
    return null;
  }}
  roots.forEach(r => computeRollup(r.number));

  // Jeśli rodzic jest w relacji zależności (lub jego potomkowie są), oznacz też przodków przy filtrowaniu
  const subtreeHasDeps = new Set(involvedInDeps);
  function propagateDepsUp(num) {{
    let curr = parentMap.get(num);
    while (curr != null) {{
      subtreeHasDeps.add(curr);
      curr = parentMap.get(curr);
    }}
  }}
  involvedInDeps.forEach(n => propagateDepsUp(n));

  // Dziedziczenie w dół dla zadań bez dat (aby strzałki i widok pełnego WBS zawsze miały współrzędne)
  const fallbackDate = parseDate('2026-11-02');
  ordered.forEach(({{ item }}) => {{
    if (!dateInfo.has(item.number)) {{
      let curr = item.parent_issue ? item.parent_issue.number : null;
      while (curr != null) {{
        if (dateInfo.has(curr)) {{
          const pInfo = dateInfo.get(curr);
          dateInfo.set(item.number, {{ start: pInfo.start, end: pInfo.end, source: 'inferred' }});
          break;
        }}
        const pItem = byNum.get(curr);
        curr = (pItem && pItem.parent_issue) ? pItem.parent_issue.number : null;
      }}
      if (!dateInfo.has(item.number)) {{
        dateInfo.set(item.number, {{ start: fallbackDate, end: addDays(fallbackDate, 3), source: 'inferred' }});
      }}
    }}
  }});

  return {{
    byNum,
    ordered,
    childrenMap,
    parentMap,
    descendantCountMap,
    depEdges,
    involvedInDeps,
    subtreeHasDeps,
    dateInfo
  }};
}}

const MODEL = buildModel();

function toggleNode(num, evt) {{
  if (evt) evt.stopPropagation();
  if (collapsedNodes.has(num)) {{
    collapsedNodes.delete(num);
  }} else {{
    collapsedNodes.add(num);
  }}
  render();
}}

function expandAll() {{
  collapsedNodes.clear();
  render();
}}

function collapseToDepth(maxDepth) {{
  collapsedNodes.clear();
  MODEL.ordered.forEach(({{ item, depth }}) => {{
    const hasChildren = (MODEL.childrenMap.get(item.number) || []).length > 0;
    if (hasChildren && depth >= maxDepth) {{
      collapsedNodes.add(item.number);
    }}
  }});
  render();
}}

function isHiddenByCollapsedAncestor(num) {{
  let curr = MODEL.parentMap.get(num);
  while (curr != null) {{
    if (collapsedNodes.has(curr)) return true;
    curr = MODEL.parentMap.get(curr);
  }}
  return false;
}}

function getVisibleRepresentative(num, visibleSet) {{
  let curr = num;
  while (curr != null) {{
    if (visibleSet.has(curr)) return curr;
    curr = MODEL.parentMap.get(curr);
  }}
  return null;
}}

function render() {{
  const filterMode = document.getElementById('filter-mode').value;
  const showDepArrows = document.getElementById('show-dep-arrows').checked;
  const showHierArrows = document.getElementById('show-hier-arrows').checked;
  const dayWidth = parseInt(document.getElementById('day-width').value, 10);

  const {{
    byNum,
    ordered,
    childrenMap,
    descendantCountMap,
    depEdges,
    involvedInDeps,
    subtreeHasDeps,
    dateInfo
  }} = MODEL;

  // Sprawdź czy w JSON są już pobrane pola blocked_by / blocking
  const sampleItem = ordered[0] ? ordered[0].item : null;
  const hasBlockedByField = sampleItem && sampleItem.relationships && ('blocked_by' in sampleItem.relationships);
  const noticeEl = document.getElementById('missing-deps-notice');
  if (!hasBlockedByField) {{
    noticeEl.style.display = 'block';
    noticeEl.innerHTML = '<strong>Uwaga:</strong> Obecny plik <code>project_export.json</code> został wygenerowany przed dodaniem pobierania relacji <code>Blocked by / Blocking</code>. Uruchom ponownie <code>python export_github_project.py --url "https://github.com/users/Matthew-Calish/projects/3"</code>, aby dociągnąć strzałki zależności z GitHuba!';
  }} else if (depEdges.length === 0) {{
    noticeEl.style.display = 'block';
    noticeEl.innerHTML = 'W API GitHuba nie znaleziono jeszcze żadnych relacji <code>Blocked by / Blocking</code> dla zadań w tym projekcie. Możesz włączyć u góry opcję <strong>"Strzałki hierarchii (Parent &rarr; Sub-issue)"</strong> lub dodać relacje <em>Blocked by</em> na GitHubie i odświeżyć eksport.';
  }} else {{
    noticeEl.style.display = 'none';
  }}

  // 1) Najpierw filtrujemy wg trybu widoku, a potem odrzucamy potomków zwiniętych węzłów
  const modeFiltered = ordered.filter(({{ item }}) => {{
    const dInfo = dateInfo.get(item.number);
    const hasExplicitOrRollup = dInfo && (dInfo.source === 'explicit' || dInfo.source === 'rollup');
    const inDeps = involvedInDeps.has(item.number) || subtreeHasDeps.has(item.number);

    if (filterMode === 'deps_only') {{
      return inDeps;
    }}
    if (filterMode === 'dated_or_deps') {{
      return hasExplicitOrRollup || inDeps;
    }}
    return true;
  }});

  const modeFilteredSet = new Set(modeFiltered.map(r => r.item.number));

  const visibleRows = modeFiltered.filter(({{ item }}) => !isHiddenByCollapsedAncestor(item.number));
  const visibleSet = new Set(visibleRows.map(r => r.item.number));

  // Zakres dat osi czasu
  let minDate = null;
  let maxDate = null;
  visibleRows.forEach(({{ item }}) => {{
    const d = dateInfo.get(item.number);
    if (d) {{
      if (!minDate || d.start < minDate) minDate = d.start;
      if (!maxDate || d.end > maxDate) maxDate = d.end;
    }}
  }});
  if (!minDate) {{
    minDate = parseDate('2026-10-28');
    maxDate = parseDate('2026-12-20');
  }} else {{
    minDate = addDays(minDate, -3);
    maxDate = addDays(maxDate, 5);
  }}

  const totalDays = Math.max(14, diffDays(minDate, maxDate) + 1);
  const leftColWidth = 475;
  const headerHeight = 56;
  const rowHeight = 36;
  const chartWidth = leftColWidth + totalDays * dayWidth + 60;
  const chartHeight = headerHeight + visibleRows.length * rowHeight + 30;

  const svgParts = [];
  svgParts.push(`<svg id="gantt-svg" xmlns="http://www.w3.org/2000/svg" width="${{chartWidth}}" height="${{chartHeight}}" style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; display: block;">`);

  // Definicje grotów strzałek
  svgParts.push(`
    <defs>
      <marker id="arrow-dep" viewBox="0 0 10 10" refX="7" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse">
        <path d="M 0 1.5 L 8.5 5 L 0 8.5 z" fill="#7c8da6" />
      </marker>
      <marker id="arrow-hier" viewBox="0 0 10 10" refX="7" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse">
        <path d="M 0 1.5 L 8.5 5 L 0 8.5 z" fill="#64748b" />
      </marker>
    </defs>
  `);

  // Tło nagłówka
  svgParts.push(`<rect x="0" y="0" width="${{chartWidth}}" height="${{headerHeight}}" fill="#f8fafc" />`);
  svgParts.push(`<line x1="0" y1="${{headerHeight}}" x2="${{chartWidth}}" y2="${{headerHeight}}" stroke="#cbd5e1" stroke-width="1" />`);
  svgParts.push(`<text x="16" y="34" font-size="13" font-weight="700" fill="#0f172a">Zadanie (#ID Tytuł – kliknij &#9660;/&#9654; aby zwinąć)</text>`);
  svgParts.push(`<text x="${{leftColWidth - 145}}" y="34" font-size="12" font-weight="600" fill="#64748b">Osoba</text>`);
  svgParts.push(`<text x="${{leftColWidth - 85}}" y="34" font-size="12" font-weight="600" fill="#64748b">Start &rarr; Koniec</text>`);

  // Siatka pionowa dni i nagłówki dat
  for (let i = 0; i < totalDays; i++) {{
    const cur = addDays(minDate, i);
    const x = leftColWidth + i * dayWidth;
    const dayOfWeek = cur.getUTCDay();
    const isWeekend = (dayOfWeek === 0 || dayOfWeek === 6);
    const dayNum = cur.getUTCDate();
    const monthStr = cur.toISOString().slice(0, 7);

    if (isWeekend) {{
      svgParts.push(`<rect x="${{x}}" y="${{headerHeight}}" width="${{dayWidth}}" height="${{chartHeight - headerHeight}}" fill="#f8fafc" />`);
    }}

    svgParts.push(`<line x1="${{x}}" y1="${{headerHeight - 22}}" x2="${{x}}" y2="${{chartHeight}}" stroke="${{dayOfWeek === 1 ? '#cbd5e1' : '#f1f5f9'}}" stroke-width="1" />`);

    if (dayNum === 1 || i === 0) {{
      svgParts.push(`<text x="${{x + 4}}" y="18" font-size="11" font-weight="700" fill="#334155">${{monthStr}}</text>`);
    }}
    if (dayWidth >= 22 || dayOfWeek === 1) {{
      svgParts.push(`<text x="${{x + dayWidth / 2}}" y="${{headerHeight - 7}}" font-size="10" text-anchor="middle" fill="${{isWeekend ? '#94a3b8' : '#475569'}}">${{String(dayNum).padStart(2, '0')}}</text>`);
    }}
  }}

  // Wiersze i paski zadań
  const barCoords = new Map();
  const topAvatarsLayer = [];

  visibleRows.forEach(({{ item, depth }}, idx) => {{
    const y = headerHeight + idx * rowHeight;
    const dInfo = dateInfo.get(item.number);
    const isEtap = (item.project_fields && item.project_fields['Status'] === 'Etap') || depth === 0;
    const allChildren = childrenMap.get(item.number) || [];
    const visibleInModeChildren = allChildren.filter(c => modeFilteredSet.has(c));
    const hasCollapsibleChildren = visibleInModeChildren.length > 0;
    const isCollapsed = collapsedNodes.has(item.number);
    const totalDesc = descendantCountMap.get(item.number) || allChildren.length;

    // Tło wiersza
    svgParts.push(`<rect x="0" y="${{y}}" width="${{chartWidth}}" height="${{rowHeight}}" fill="${{idx % 2 === 0 ? '#ffffff' : '#fcfdff'}}" opacity="0.7" />`);
    svgParts.push(`<line x1="0" y1="${{y + rowHeight}}" x2="${{chartWidth}}" y2="${{y + rowHeight}}" stroke="#f1f5f9" stroke-width="1" />`);

    // Wcięcie i przycisk zwijania/rozwijania drzewa
    const indent = 12 + depth * 18;
    const textStartX = indent + 20;
    const rawTitle = `#${{item.number}} ${{item.title || ''}}`;
    const reserveRight = isCollapsed ? 195 : 160;
    const maxChars = Math.max(16, Math.floor((leftColWidth - reserveRight - textStartX) / 6.5));
    const truncatedTitle = rawTitle.length > maxChars ? rawTitle.slice(0, maxChars - 1) + '…' : rawTitle;
    const fontWeight = (isEtap || allChildren.length > 0) ? '600' : '400';
    const textColor = isEtap ? '#0f172a' : (allChildren.length > 0 ? '#1e3a8a' : '#334155');

    if (hasCollapsibleChildren) {{
      const iconChar = isCollapsed ? '&#9654;' : '&#9660;';
      const badgeText = isCollapsed ? ` [+${{totalDesc}}]` : '';
      svgParts.push(`
        <g class="tree-toggle" onclick="toggleNode(${{item.number}}, event)">
          <rect class="toggle-hit" x="${{indent - 4}}" y="${{y + 4}}" width="${{leftColWidth - indent - 150}}" height="${{rowHeight - 8}}" rx="4" fill="transparent" />
          <rect x="${{indent}}" y="${{y + 9}}" width="16" height="16" rx="3" fill="${{isCollapsed ? '#dbeafe' : '#f1f5f9'}}" stroke="${{isCollapsed ? '#93c5fd' : '#cbd5e1'}}" stroke-width="1" />
          <text x="${{indent + 8}}" y="${{y + 20}}" font-size="9" text-anchor="middle" fill="${{isCollapsed ? '#1d4ed8' : '#475569'}}">${{iconChar}}</text>
          <text x="${{textStartX}}" y="${{y + 22}}" font-size="12" font-weight="${{fontWeight}}" fill="${{textColor}}">
            ${{escapeXml(truncatedTitle)}}<tspan fill="#2563eb" font-size="11" font-weight="700">${{badgeText}}</tspan>
          </text>
        </g>
      `);
    }} else {{
      // Kropka dla liścia (zadania bez widocznych podzadań)
      svgParts.push(`
        <circle cx="${{indent + 8}}" cy="${{y + 17}}" r="2.2" fill="#94a3b8" />
        <text x="${{textStartX}}" y="${{y + 22}}" font-size="12" font-weight="${{fontWeight}}" fill="${{textColor}}">${{escapeXml(truncatedTitle)}}</text>
      `);
    }}

    // Ikony przypisanych osób (GitHub Avatars) w kolumnie "Osoba"
    const assignees = item.assignees || [];
    const avatarBaseX = leftColWidth - 145;
    assignees.slice(0, 3).forEach((login, aIdx) => {{
      const ax = avatarBaseX + aIdx * 18;
      const ay = y + 7;
      const clipId = `avatar-clip-${{item.number}}-${{aIdx}}`;
      const initials = (login || '?').slice(0, 2).toUpperCase();
      svgParts.push(`
        <g onmouseenter="showTooltip(event, ${{item.number}})" onmouseleave="hideTooltip()">
          <clipPath id="${{clipId}}">
            <circle cx="${{ax + 11}}" cy="${{ay + 11}}" r="11" />
          </clipPath>
          <circle cx="${{ax + 11}}" cy="${{ay + 11}}" r="11" fill="#e2e8f0" />
          <text x="${{ax + 11}}" y="${{ay + 14.5}}" font-size="8.5" font-weight="700" text-anchor="middle" fill="#475569">${{escapeXml(initials)}}</text>
          <image href="https://github.com/${{encodeURIComponent(login)}}.png?size=48" x="${{ax}}" y="${{ay}}" width="22" height="22" clip-path="url(#${{clipId}})" />
          <circle cx="${{ax + 11}}" cy="${{ay + 11}}" r="11" fill="none" stroke="#ffffff" stroke-width="1.5" />
          <title>${{escapeXml(login)}}</title>
        </g>
      `);
    }});

    if (dInfo) {{
      const dateLabel = `${{formatDate(dInfo.start).slice(5)}}..${{formatDate(dInfo.end).slice(5)}}`;
      svgParts.push(`<text x="${{leftColWidth - 85}}" y="${{y + 22}}" font-size="10.5" fill="#64748b">${{dateLabel}}</text>`);

      const startOffset = diffDays(minDate, dInfo.start);
      const durationDays = Math.max(1, diffDays(dInfo.start, dInfo.end) + 1);
      const barX = leftColWidth + startOffset * dayWidth + 2;
      const barW = Math.max(12, durationDays * dayWidth - 4);
      const barY = y + (isEtap ? 8 : 7);
      const barH = isEtap ? 20 : 22;

      let fill = '#3b82f6';
      if (isEtap) fill = '#1e293b';
      else if (allChildren.length > 0) fill = '#2563eb';
      else if (dInfo.source === 'inferred') fill = '#94a3b8';

      barCoords.set(item.number, {{
        x: barX,
        y: barY,
        w: barW,
        h: barH,
        midY: barY + barH / 2,
        rightX: barX + barW,
        leftX: barX
      }});

      // Małe awatary z GitHuba bezpośrednio przy pasku na osi czasu
      let barAvatarsSvg = '';
      let barAvatarOffset = 0;
      assignees.slice(0, 3).forEach((login, aIdx) => {{
        const bx = barX + barW + 6 + aIdx * 16;
        const by = y + 9;
        const bClipId = `bar-avatar-clip-${{item.number}}-${{aIdx}}`;
        barAvatarsSvg += `
          <clipPath id="${{bClipId}}">
            <circle cx="${{bx + 9}}" cy="${{by + 9}}" r="9" />
          </clipPath>
          <image href="https://github.com/${{encodeURIComponent(login)}}.png?size=40" x="${{bx}}" y="${{by}}" width="18" height="18" clip-path="url(#${{bClipId}})" />
          <circle cx="${{bx + 9}}" cy="${{by + 9}}" r="9" fill="none" stroke="#cbd5e1" stroke-width="1" />
        `;
        barAvatarOffset += 17;
      }});
      if (barAvatarOffset > 0) barAvatarOffset += 4;

      // Nazwa zadania na pastylce (bez #ID i bez licznika +N)
      const cleanBarTitle = item.title || '';
      let barTextSvg = '';
      if (barW >= 55) {{
        const maxBarChars = Math.max(4, Math.floor((barW - 14) / 6.3));
        const pillTitle = cleanBarTitle.length > maxBarChars
          ? cleanBarTitle.slice(0, maxBarChars - 1) + '…'
          : cleanBarTitle;
        barTextSvg = `<text x="${{barX + 8}}" y="${{barY + barH / 2 + 4}}" font-size="11" fill="#ffffff" font-weight="600">${{escapeXml(pillTitle)}}</text>`;
      }} else {{
        // Dla bardzo krótkich (np. 1-dniowych) pastylek, gdzie tekst nie zmieści się w środku
        barTextSvg = `<text x="${{barX + barW + 6 + barAvatarOffset}}" y="${{barY + barH / 2 + 4}}" font-size="11" fill="#334155" font-weight="500">${{escapeXml(cleanBarTitle)}}</text>`;
      }}

      const clickAttr = hasCollapsibleChildren ? `onclick="toggleNode(${{item.number}}, event)" style="cursor:pointer;"` : '';
      const pillRadius = barH / 2;
      svgParts.push(`
        <g class="task-bar" data-num="${{item.number}}" ${{clickAttr}} onmouseenter="showTooltip(event, ${{item.number}})" onmouseleave="hideTooltip()">
          <rect x="${{barX}}" y="${{barY}}" width="${{barW}}" height="${{barH}}" rx="${{pillRadius}}" ry="${{pillRadius}}" fill="${{fill}}" />
          ${{barTextSvg}}
        </g>
      `);
      if (barAvatarsSvg) {{
        topAvatarsLayer.push(`
          <g class="bar-avatars-top" onmouseenter="showTooltip(event, ${{item.number}})" onmouseleave="hideTooltip()">
            ${{barAvatarsSvg}}
          </g>
        `);
      }}
    }}
  }});

  // Linia oddzielająca tabelę od osi czasu
  svgParts.push(`<line x1="${{leftColWidth}}" y1="0" x2="${{leftColWidth}}" y2="${{chartHeight}}" stroke="#cbd5e1" stroke-width="1.5" />`);

  // Funkcja budująca ścieżkę z zaokrąglonymi narożnikami (zamiast ostrych kątów 90 stopni)
  function buildRoundedOrthogonalPath(pts, radius = 8) {{
    if (!pts || pts.length === 0) return '';
    if (pts.length === 1) return `M ${{pts[0][0]}} ${{pts[0][1]}}`;
    let d = `M ${{pts[0][0]}} ${{pts[0][1]}}`;
    for (let i = 1; i < pts.length - 1; i++) {{
      const prev = pts[i - 1];
      const curr = pts[i];
      const next = pts[i + 1];
      const v1x = curr[0] - prev[0];
      const v1y = curr[1] - prev[1];
      const v2x = next[0] - curr[0];
      const v2y = next[1] - curr[1];
      const len1 = Math.hypot(v1x, v1y);
      const len2 = Math.hypot(v2x, v2y);
      const r = Math.min(radius, len1 / 2, len2 / 2);
      if (r < 0.5) {{
        d += ` L ${{curr[0]}} ${{curr[1]}}`;
      }} else {{
        const startCornerX = curr[0] - (v1x / len1) * r;
        const startCornerY = curr[1] - (v1y / len1) * r;
        const endCornerX = curr[0] + (v2x / len2) * r;
        const endCornerY = curr[1] + (v2y / len2) * r;
        d += ` L ${{startCornerX}} ${{startCornerY}} Q ${{curr[0]}} ${{curr[1]}} ${{endCornerX}} ${{endCornerY}}`;
      }}
    }}
    const last = pts[pts.length - 1];
    d += ` L ${{last[0]}} ${{last[1]}}`;
    return d;
  }}

  // 1) Strzałki hierarchii (Parent -> Sub-issue), jeśli włączone (z zaokrąglonymi narożnikami)
  if (showHierArrows) {{
    visibleRows.forEach(({{ item }}) => {{
      const pNum = item.parent_issue ? item.parent_issue.number : null;
      if (pNum != null && barCoords.has(pNum) && barCoords.has(item.number)) {{
        const from = barCoords.get(pNum);
        const to = barCoords.get(item.number);
        const startX = from.leftX + 6;
        const startY = from.midY;
        const endX = to.leftX - 2;
        const endY = to.midY;
        const path = buildRoundedOrthogonalPath([[startX, startY], [startX, endY], [endX, endY]], 7);
        svgParts.push(`<path d="${{path}}" fill="none" stroke="#64748b" stroke-width="1.3" stroke-dasharray="4 3" marker-end="url(#arrow-hier)" opacity="0.75" />`);
      }}
    }});
  }}

  // 2) Strzałki zależności (Blocked by / Blocking) – identyczna geometria jak na referencyjnym zrzucie:
  // Wyjście z prawego środka pastylki -> mały zaokrąglony nawrót w korytarz bezpośrednio pod/nad pastylką ->
  // wspólna pionowa linia w dół przed docelowymi pastylkami -> zaokrąglone wejście w lewy bok pastylki.
  if (showDepArrows) {{
    const drawnPairs = new Set();
    const depStrokes = [];

    depEdges.forEach(edge => {{
      const visFrom = getVisibleRepresentative(edge.from, visibleSet);
      const visTo = getVisibleRepresentative(edge.to, visibleSet);
      if (visFrom == null || visTo == null || visFrom === visTo) return;
      if (!barCoords.has(visFrom) || !barCoords.has(visTo)) return;

      const pairKey = `${{visFrom}}->${{visTo}}`;
      if (drawnPairs.has(pairKey)) return;
      drawnPairs.add(pairKey);

      const from = barCoords.get(visFrom);
      const to = barCoords.get(visTo);

      const x1 = from.rightX;
      const y1 = from.midY;
      const x2 = to.leftX;
      const y2 = to.midY;
      const goingDown = y2 >= y1;

      const stepOut = x1 + 14;
      const trunkX = x2 - 14;
      // Korytarz poziomy tuż pod (lub nad) pastylką źródłową – wspólny dla wszystkich gałęzi wychodzących z tego samego zadania!
      const corridorY = goingDown
        ? (from.y + from.h + (rowHeight - from.h) / 2)
        : (from.y - (rowHeight - from.h) / 2);

      let pts;
      if (trunkX >= stepOut) {{
        // Następnik jest daleko w prawo – prosty schodek bez nawrotu
        pts = [[x1, y1], [trunkX, y1], [trunkX, y2], [x2 - 2, y2]];
      }} else {{
        // Nawrót jak na zdjęciu: prawo -> w dół do korytarza pod pastylką -> w lewo do osi przed następnikiem -> w dół do następnika -> w prawo
        pts = [
          [x1, y1],
          [stepOut, y1],
          [stepOut, corridorY],
          [trunkX, corridorY],
          [trunkX, y2],
          [x2 - 2, y2]
        ];
      }}
      const dPath = buildRoundedOrthogonalPath(pts, 6);

      depStrokes.push(`
        <path d="${{dPath}}" fill="none" stroke="#7c8da6" stroke-width="1.8" stroke-linejoin="round" stroke-linecap="round" marker-end="url(#arrow-dep)" />
      `);
    }});

    svgParts.push(`<g class="dep-arrow-strokes">${{depStrokes.join('\\n')}}</g>`);
  }}

  // 3) Najwyższa warstwa: awatary z GitHuba na osi czasu (renderowane NAD strzałkami!)
  if (topAvatarsLayer.length > 0) {{
    svgParts.push(`<g id="avatars-top-layer">${{topAvatarsLayer.join('\\n')}}</g>`);
  }}

  svgParts.push(`</svg>`);
  document.getElementById('gantt-container').innerHTML = svgParts.join('\\n');

  // Nagłówek i podsumowanie zależności pod wykresem
  const pTitle = (RAW_DATA.project && RAW_DATA.project.title) ? RAW_DATA.project.title : 'Projekt GitHub';
  document.getElementById('project-title').textContent = `Wykres Gantta – ${{pTitle}}`;
  document.getElementById('project-stats').textContent =
    `Widoczne wiersze: ${{visibleRows.length}} z ${{ordered.length}} (zwinięte węzły: ${{collapsedNodes.size}}) | Relacje zależności (strzałki): ${{depEdges.length}}`;

  const depsListEl = document.getElementById('deps-list');
  document.getElementById('deps-title').textContent = `Wykryte zależności Blocked by / Blocking (${{depEdges.length}})`;
  if (depEdges.length === 0) {{
    depsListEl.innerHTML = `<div style="color: #64748b;">Brak zdefiniowanych relacji Blocked by / Blocking w wyeksportowanym pliku JSON.</div>`;
  }} else {{
    depsListEl.innerHTML = depEdges.map(e => {{
      const a = byNum.get(e.from) || {{}};
      const b = byNum.get(e.to) || {{}};
      return `
        <div class="dep-card">
          <span><strong>#${{e.from}}</strong> ${{escapeXml(a.title || '')}}</span>
          <span class="dep-arrow-badge">&rarr; blokuje &rarr;</span>
          <span><strong>#${{e.to}}</strong> ${{escapeXml(b.title || '')}}</span>
        </div>
      `;
    }}).join('');
  }}
}}

function escapeXml(unsafe) {{
  return String(unsafe)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}}

function showTooltip(evt, num) {{
  const it = MODEL.byNum.get(num);
  if (!it) return;
  const dInfo = MODEL.dateInfo.get(num);
  const rels = it.relationships || {{}};
  const blockedBy = (rels.blocked_by || []).map(x => `#${{x.number}} ${{x.title}}`).join('<br>• ');
  const blocking = (rels.blocking || []).map(x => `#${{x.number}} ${{x.title}}`).join('<br>• ');
  const parentStr = it.parent_issue ? `#${{it.parent_issue.number}} ${{it.parent_issue.title}}` : 'Brak (poziom główny)';
  const descCount = MODEL.descendantCountMap.get(num) || 0;

  let html = `<div><strong>#${{it.number}} ${{escapeXml(it.title)}}</strong></div>`;
  html += `<div style="color:#cbd5e1; margin-top:4px;">Start: <b>${{formatDate(dInfo.start)}}</b> | Koniec: <b>${{formatDate(dInfo.end)}}</b></div>`;
  const assignees = it.assignees || [];
  if (assignees.length > 0) {{
    const avatarsHtml = assignees.map(u => `<span style="display:inline-flex;align-items:center;gap:4px;background:#1e293b;padding:2px 6px;border-radius:12px;margin-right:4px;"><img src="https://github.com/${{encodeURIComponent(u)}}.png?size=32" style="width:14px;height:14px;border-radius:50%;"/>${{escapeXml(u)}}</span>`).join('');
    html += `<div style="margin-top:5px;">Przypisani: ${{avatarsHtml}}</div>`;
  }} else {{
    html += `<div style="color:#64748b; margin-top:2px;">Przypisani: <i>brak</i></div>`;
  }}
  html += `<div style="color:#94a3b8; margin-top:2px;">Rodzic (Parent): ${{escapeXml(parentStr)}}</div>`;
  if (descCount > 0) {{
    html += `<div style="color:#93c5fd; margin-top:2px;">Podzadania w drzewie: <b>${{descCount}}</b> (kliknij aby ${{collapsedNodes.has(num) ? 'rozwinąć' : 'zwinąć'}})</div>`;
  }}
  if (blockedBy) html += `<div style="margin-top:6px; color:#fca5a5;"><b>Zablokowane przez (poprzednik):</b><br>• ${{blockedBy}}</div>`;
  if (blocking) html += `<div style="margin-top:6px; color:#86efac;"><b>Blokuje (następnik):</b><br>• ${{blocking}}</div>`;

  const tt = document.getElementById('tooltip');
  tt.innerHTML = html;
  tt.style.display = 'block';
  tt.style.left = (evt.clientX + 14) + 'px';
  tt.style.top = (evt.clientY + 14) + 'px';
}}

function hideTooltip() {{
  document.getElementById('tooltip').style.display = 'none';
}}

function downloadSVG() {{
  const svgEl = document.getElementById('gantt-svg');
  if (!svgEl) return;
  const serializer = new XMLSerializer();
  let source = serializer.serializeToString(svgEl);
  const blob = new Blob([source], {{ type: "image/svg+xml;charset=utf-8" }});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'gantt_chart.svg';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}}

document.getElementById('filter-mode').addEventListener('change', render);
document.getElementById('show-dep-arrows').addEventListener('change', render);
document.getElementById('show-hier-arrows').addEventListener('change', render);
document.getElementById('day-width').addEventListener('change', render);

// Domyślnie na starcie zwijamy podzadania do widoku: Etap -> Podetapy
collapseToDepth(1);
</script>
</body>
</html>
"""

    with open(output_html, "w", encoding="utf-8") as f:
        f.write(html_content)

    return os.path.abspath(output_html)


if __name__ == "__main__":
    json_file = sys.argv[1] if len(sys.argv) > 1 else "project_export.json"
    out_file = sys.argv[2] if len(sys.argv) > 2 else "gantt_chart.html"
    path = generate_gantt_html(json_file, out_file)
    print(f"Wygenerowano interaktywny wykres Gantta: {path}")
