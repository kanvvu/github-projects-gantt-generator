#!/usr/bin/env python3
"""
Generuje interaktywny wykres Gantta (HTML + SVG) ze strzałkami zależności
(blocked_by / blocking oraz opcjonalnie parent -> sub-issue) oraz zwijaniem/rozwijaniem
drzewa WBS (podzadań) na podstawie pliku project_export.json.
"""

import base64
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path


def fetch_avatars_base64(items: list) -> dict:
    """Pobiera awatary przypisanych użytkowników z GitHuba i koduje je jako data:image/png;base64."""
    logins = set()
    for it in items:
        for u in it.get("assignees") or []:
            if u:
                logins.add(u)

    avatar_map = {}
    for login in sorted(logins):
        url = f"https://avatars.githubusercontent.com/{ urllib.parse.quote(login) }?size=64"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "PBL-Gantt-Generator"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                raw = resp.read()
                ctype = resp.headers.get("Content-Type", "image/png").split(";")[0]
                b64 = base64.b64encode(raw).decode("ascii")
                avatar_map[login] = f"data:{ctype};base64,{b64}"
        except Exception:
            pass
    return avatar_map


def find_system_browser() -> str | None:
    """Znajduje zainstalowaną w systemie przeglądarkę Chromium/Chrome/Edge (działa na Ubuntu GHA oraz Windows)."""
    candidates = [
        "google-chrome",
        "google-chrome-stable",
        "chromium",
        "chromium-browser",
        "msedge",
        "chrome",
    ]
    for cmd in candidates:
        found = shutil.which(cmd)
        if found:
            return found

    win_paths = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]
    for p in win_paths:
        if os.path.exists(p):
            return p
    return None


def render_png_from_html(html_path: str, png_path: str) -> str | None:
    """Renderuje wygenerowany plik HTML (w trybie ?export=1) bezpośrednio do pliku PNG za pomocą systemowej przeglądarki."""
    browser = find_system_browser()
    if not browser:
        return None

    abs_html = os.path.abspath(html_path)
    abs_png = os.path.abspath(png_path)
    file_url = Path(abs_html).as_uri() + "?export=1"

    base_flags = [
        browser,
        "--headless",
        "--disable-gpu",
        "--no-sandbox",
        "--hide-scrollbars",
    ]

    # 1) Pobierz wyrenderowany DOM, aby odczytać dokładne wymiary width i height elementu <svg id="gantt-svg">
    width, height = 2200, 720
    try:
        proc = subprocess.run(
            base_flags + ["--dump-dom", file_url],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=20,
        )
        m = re.search(r'<svg[^>]*id="gantt-svg"[^>]*width="(\d+)"[^>]*height="(\d+)"', proc.stdout)
        if m:
            width = int(m.group(1))
            height = int(m.group(2))
    except Exception:
        pass

    # 2) Zapisz zrzut PNG w jakości 2x Retina o dokładnych wymiarach wykresu SVG
    try:
        subprocess.run(
            base_flags
            + [
                "--force-device-scale-factor=2",
                f"--window-size={width},{height}",
                f"--screenshot={abs_png}",
                file_url,
            ],
            capture_output=True,
            timeout=25,
            check=False,
        )
        if os.path.exists(abs_png):
            return abs_png
    except Exception:
        pass
    return None


def generate_gantt_html(
    json_path: str = "project_export.json",
    output_html: str = "gantt_chart.html",
    output_png: str | None = None,
) -> str:
    if not os.path.exists(json_path):
        raise FileNotFoundError(f"Nie znaleziono pliku {json_path}. Uruchom najpierw export_github_project.py.")

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    embedded_json = json.dumps(data, ensure_ascii=False)
    avatars_b64 = data.get("avatars_base64") or fetch_avatars_base64(data.get("items", []))
    avatar_map_json = json.dumps(avatars_b64, ensure_ascii=False)

    html_content = f"""<!DOCTYPE html>
<html lang="pl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>PBL Gantta – {data.get('project', {}).get('title', 'GitHub Project')}</title>
<style>
  :root {{
    --bg: #0d1117;
    --surface: #161b22;
    --border: #21262d;
    --border-strong: #30363d;
    --text: #e6edf3;
    --text-muted: #8b949e;
    --etap-bar: #2563eb;
    --parent-bar: #3b82f6;
    --leaf-bar: #6366f1;
    --inferred-bar: #475569;
    --dep-arrow: #94a3b8;
    --dep-arrow-hover: #cbd5e1;
    --hier-arrow: #64748b;
    --row-hover: #1f242c;
    --btn-bg: #238636;
    --btn-text: #ffffff;
  }}

  body.light-mode {{
    --bg: #ffffff;
    --surface: #f8fafc;
    --border: #e2e8f0;
    --border-strong: #cbd5e1;
    --text: #0f172a;
    --text-muted: #64748b;
    --etap-bar: #1d4ed8;
    --parent-bar: #2563eb;
    --leaf-bar: #3b82f6;
    --inferred-bar: #94a3b8;
    --dep-arrow: #7c8da6;
    --dep-arrow-hover: #475569;
    --hier-arrow: #64748b;
    --row-hover: #f1f5f9;
    --btn-bg: #0f172a;
    --btn-text: #ffffff;
  }}

  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Inter, sans-serif;
    background: var(--bg);
    color: var(--text);
    padding: 20px;
    transition: background 0.15s, color 0.15s;
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
    background: var(--bg);
    color: var(--text);
  }}
  .btn {{
    background: var(--btn-bg);
    color: var(--btn-text);
    border: none;
    padding: 6px 11px;
    border-radius: 6px;
    font-weight: 500;
    transition: background 0.15s, opacity 0.15s;
  }}
  .btn:hover {{ opacity: 0.9; }}
  .btn-secondary {{
    background: var(--surface);
    color: var(--text);
    border: 1px solid var(--border-strong);
  }}
  .btn-secondary:hover {{
    background: var(--row-hover);
  }}
  .btn-sm {{
    padding: 4px 8px;
    font-size: 12px;
  }}

  .notice {{
    background: rgba(210, 153, 34, 0.15);
    border: 1px solid rgba(210, 153, 34, 0.4);
    color: #e3b341;
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
    background: var(--bg);
    box-shadow: 0 4px 16px rgba(0,0,0,0.25);
  }}

  .tree-toggle {{
    cursor: pointer;
    user-select: none;
  }}
  .tree-toggle:hover rect.toggle-hit {{
    fill: rgba(148, 163, 184, 0.12);
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
    background: var(--bg);
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
    <h1 id="project-title">PBL Gantta</h1>
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
      <input type="checkbox" id="show-milestones" checked>
      <label for="show-milestones">Kamienie milowe (◆)</label>
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
    <button class="btn btn-secondary" id="theme-btn" onclick="toggleTheme()">☀️ Jasny motyw</button>
    <button class="btn btn-secondary" id="png-btn" onclick="downloadPNG()">🖼 Pobierz PNG</button>
    <button class="btn btn-secondary" onclick="downloadSVG()">Pobierz SVG</button>
    <button class="btn" onclick="window.print()">Drukuj / PDF</button>
  </div>
</div>

<div id="missing-deps-notice" class="notice"></div>

<div class="legend">
  <div class="legend-item"><span class="swatch" style="background: #238636; border: 1.5px solid #3fb950;"></span> <strong>Backlog</strong></div>
  <div class="legend-item"><span class="swatch" style="background: #9e6a03; border: 1.5px solid #d29922;"></span> <strong>In progress</strong></div>
  <div class="legend-item"><span class="swatch" style="background: #1f6feb; border: 1.5px solid #388bfd;"></span> <strong>In review</strong></div>
  <div class="legend-item"><span class="swatch" style="background: #8957e5; border: 1.5px solid #a371f7;"></span> <strong>Done / Closed</strong></div>
  <div class="legend-item"><span style="color: #22c55e; font-size: 14px; line-height: 1;">&#9670;</span> <strong>Kamień milowy (Milestone)</strong></div>
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
const AVATAR_MAP = {avatar_map_json};

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
    .filter(it => !it.parent_issue || !byNum.has(it.parent_issue.number));

  roots.forEach(r => countDescendants(r.number));

  // Wyznacz daty własne z GitHub Projects (Start date / Target date / End date) PRZED sortowaniem drzewa
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

  // Funkcja porównująca zadania po Target date (end), następnie po Start date (start), a na końcu po #ID
  function compareByTargetDate(numA, numB) {{
    const dA = dateInfo.get(numA);
    const dB = dateInfo.get(numB);
    if (dA && dB) {{
      if (dA.end.getTime() !== dB.end.getTime()) {{
        return dA.end.getTime() - dB.end.getTime();
      }}
      if (dA.start.getTime() !== dB.start.getTime()) {{
        return dA.start.getTime() - dB.start.getTime();
      }}
    }} else if (dA && !dB) {{
      return -1;
    }} else if (!dA && dB) {{
      return 1;
    }}
    return (numA || 0) - (numB || 0);
  }}

  roots.sort((a, b) => compareByTargetDate(a.number, b.number));

  const ordered = [];
  const visited = new Set();
  const stageIndexMap = new Map();

  function dfs(num, depth, stageIdx) {{
    if (visited.has(num)) return;
    visited.add(num);
    const it = byNum.get(num);
    if (!it) return;
    stageIndexMap.set(num, stageIdx);
    ordered.push({{ item: it, depth, stageIdx }});
    const ch = childrenMap.get(num) || [];
    ch.sort(compareByTargetDate);
    ch.forEach(c => dfs(c, depth + 1, stageIdx));
  }}

  roots.forEach((r, idx) => dfs(r.number, 0, idx));
  items.forEach(it => {{
    if (!visited.has(it.number)) dfs(it.number, 0, 0);
  }});

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

  // Zbierz unikalne kamienie milowe (Milestones) z zadań projektu
  const milestonesMap = new Map();
  items.forEach(it => {{
    const m = it.milestone;
    if (m && m.due_on) {{
      const dueStr = m.due_on.slice(0, 10);
      const dueDate = parseDate(dueStr);
      const key = m.number != null ? m.number : m.title;
      if (dueDate && !milestonesMap.has(key)) {{
        milestonesMap.set(key, {{
          number: m.number,
          title: m.title || 'Milestone',
          state: m.state || 'OPEN',
          dueStr,
          dueDate,
          url: m.url
        }});
      }}
    }}
  }});
  const milestones = Array.from(milestonesMap.values()).sort(
    (a, b) => a.dueDate.getTime() - b.dueDate.getTime()
  );

  return {{
    byNum,
    roots,
    ordered,
    childrenMap,
    parentMap,
    descendantCountMap,
    stageIndexMap,
    depEdges,
    involvedInDeps,
    subtreeHasDeps,
    dateInfo,
    milestones
  }};
}}

const STAGE_PALETTE = [
  {{
    stageFill: '#2563eb',
    parentFill: '#3b82f6',
    leafFill: '#60a5fa',
    zoneBgLight: 'rgba(37, 99, 235, 0.05)',
    zoneBgDark: 'rgba(59, 130, 246, 0.08)',
    border: '#3b82f6',
    chipBgLight: '#dbeafe',
    chipTextLight: '#1e40af',
    chipBgDark: 'rgba(37, 99, 235, 0.22)',
    chipTextDark: '#93c5fd'
  }},
  {{
    stageFill: '#4f46e5',
    parentFill: '#6366f1',
    leafFill: '#818cf8',
    zoneBgLight: 'rgba(79, 70, 229, 0.05)',
    zoneBgDark: 'rgba(99, 102, 241, 0.08)',
    border: '#6366f1',
    chipBgLight: '#e0e7ff',
    chipTextLight: '#3730a3',
    chipBgDark: 'rgba(79, 70, 229, 0.22)',
    chipTextDark: '#a5b4fc'
  }},
  {{
    stageFill: '#0284c7',
    parentFill: '#0ea5e9',
    leafFill: '#38bdf8',
    zoneBgLight: 'rgba(2, 132, 199, 0.05)',
    zoneBgDark: 'rgba(14, 165, 233, 0.08)',
    border: '#0ea5e9',
    chipBgLight: '#e0f2fe',
    chipTextLight: '#075985',
    chipBgDark: 'rgba(2, 132, 199, 0.22)',
    chipTextDark: '#7dd3fc'
  }}
];

let isDarkMode = true;

function getStatusStyle(item, isDark) {{
  const pf = (item && item.project_fields) || {{}};
  const rawStatus = pf['Status'] || (item && item.state === 'CLOSED' ? 'Done' : 'Backlog');
  const norm = String(rawStatus).trim().toLowerCase();

  if (norm === 'in progress') {{
    return {{
      label: rawStatus,
      ring: '#d29922',
      fill: isDark ? '#2b2111' : '#fef3c7',
      badgeBg: isDark ? 'rgba(210, 153, 34, 0.14)' : '#fef3c7',
      badgeBorder: isDark ? 'rgba(210, 153, 34, 0.4)' : '#f59e0b',
      textColor: isDark ? '#e3b341' : '#92400e',
      barFill: isDark ? '#9e6a03' : '#d97706',
      barStroke: '#e3b341'
    }};
  }}
  if (norm === 'in review') {{
    return {{
      label: rawStatus,
      ring: '#388bfd',
      fill: isDark ? '#12233d' : '#dbeafe',
      badgeBg: isDark ? 'rgba(56, 139, 253, 0.14)' : '#dbeafe',
      badgeBorder: isDark ? 'rgba(56, 139, 253, 0.4)' : '#3b82f6',
      textColor: isDark ? '#79c0ff' : '#1e40af',
      barFill: isDark ? '#1f6feb' : '#2563eb',
      barStroke: '#58a6ff'
    }};
  }}
  if (norm === 'done' || norm === 'closed') {{
    return {{
      label: rawStatus,
      ring: '#a371f7',
      fill: isDark ? '#271c3f' : '#f3e8ff',
      badgeBg: isDark ? 'rgba(163, 113, 247, 0.14)' : '#f3e8ff',
      badgeBorder: isDark ? 'rgba(163, 113, 247, 0.4)' : '#a855f7',
      textColor: isDark ? '#d2a8ff' : '#6b21a8',
      barFill: isDark ? '#8957e5' : '#7c3aed',
      barStroke: '#bc8cff'
    }};
  }}
  // Domyślnie: Backlog (zielony jak w GitHub Projects)
  return {{
    label: rawStatus,
    ring: '#3fb950',
    fill: isDark ? '#122d1f' : '#dcfce7',
    badgeBg: isDark ? 'rgba(63, 185, 80, 0.14)' : '#dcfce7',
    badgeBorder: isDark ? 'rgba(63, 185, 80, 0.4)' : '#22c55e',
    textColor: isDark ? '#7ee787' : '#166534',
    barFill: isDark ? '#238636' : '#16a34a',
    barStroke: '#3fb950'
  }};
}}

function toggleTheme() {{
  isDarkMode = !isDarkMode;
  document.body.classList.toggle('light-mode', !isDarkMode);
  const btn = document.getElementById('theme-btn');
  if (btn) {{
    btn.textContent = isDarkMode ? '☀️ Jasny motyw' : '🌙 Ciemny motyw';
  }}
  render();
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
  const showMilestones = document.getElementById('show-milestones') ? document.getElementById('show-milestones').checked : true;
  const showDepArrows = document.getElementById('show-dep-arrows').checked;
  const showHierArrows = document.getElementById('show-hier-arrows').checked;
  const dayWidth = parseInt(document.getElementById('day-width').value, 10);

  const {{
    byNum,
    roots,
    ordered,
    childrenMap,
    descendantCountMap,
    stageIndexMap,
    depEdges,
    involvedInDeps,
    subtreeHasDeps,
    dateInfo,
    milestones
  }} = MODEL;

  // Sprawdź czy w JSON są już pobrane pola blocked_by / blocking
  const sampleItem = ordered[0] ? ordered[0].item : null;
  const hasBlockedByField = sampleItem && sampleItem.relationships && ('blocked_by' in sampleItem.relationships);
  const noticeEl = document.getElementById('missing-deps-notice');
  if (!hasBlockedByField) {{
    noticeEl.style.display = 'block';
    const projUrl = (RAW_DATA.project && RAW_DATA.project.url) ? RAW_DATA.project.url : '<URL_PROJEKTU>';
    noticeEl.innerHTML = `<strong>Uwaga:</strong> Obecny plik <code>project_export.json</code> został wygenerowany przed dodaniem pobierania relacji <code>Blocked by / Blocking</code>. Uruchom ponownie <code>python export_github_project.py --url "${{escapeXml(projUrl)}}"</code>, aby dociągnąć strzałki zależności z GitHuba!`;
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

  // Etapy główne (depth === 0) są wyświetlane obok siebie w dedykowanym górnym pasie "Pas Etapów",
  // a pod nimi w wierszach tabeli wyświetlamy podetapy i podzadania (depth > 0).
  const stageItems = roots.filter(r => modeFilteredSet.has(r.number));
  const visibleRows = modeFiltered.filter(({{ item, depth }}) => depth > 0 && !isHiddenByCollapsedAncestor(item.number));
  const visibleSet = new Set([
    ...stageItems.map(s => s.number),
    ...visibleRows.map(r => r.item.number)
  ]);

  // Zakres dat osi czasu (uwzględniając zarówno etapy, widoczne zadania, jak i kamienie milowe)
  let minDate = null;
  let maxDate = null;
  [...stageItems, ...visibleRows.map(r => r.item)].forEach(item => {{
    const d = dateInfo.get(item.number);
    if (d) {{
      if (!minDate || d.start < minDate) minDate = d.start;
      if (!maxDate || d.end > maxDate) maxDate = d.end;
    }}
  }});
  if (showMilestones) {{
    milestones.forEach(m => {{
      if (!minDate || m.dueDate < minDate) minDate = m.dueDate;
      if (!maxDate || m.dueDate > maxDate) maxDate = m.dueDate;
    }});
  }}
  if (!minDate) {{
    minDate = parseDate('2026-10-28');
    maxDate = parseDate('2026-12-20');
  }} else {{
    minDate = addDays(minDate, -3);
    maxDate = addDays(maxDate, 5);
  }}

  const totalDays = Math.max(14, diffDays(minDate, maxDate) + 1);
  const leftColWidth = 440;
  const monthRowHeight = 26;
  const milestoneBandHeight = (showMilestones && milestones.length > 0) ? 28 : 0;
  const dayRowHeight = 24;
  const headerHeight = monthRowHeight + milestoneBandHeight + dayRowHeight;
  const stageBandHeight = 40;
  const rowsStartY = headerHeight + stageBandHeight;
  const rowHeight = 36;
  const chartWidth = leftColWidth + totalDays * dayWidth + 60;
  const chartHeight = rowsStartY + visibleRows.length * rowHeight + 30;

  const T = isDarkMode
    ? {{
        bg: '#0d1117',
        headerBg: '#161b22',
        stageBandBg: '#161b22',
        rowEven: '#0d1117',
        rowOdd: '#121820',
        weekendBg: 'rgba(255, 255, 255, 0.02)',
        borderStrong: '#30363d',
        gridMonday: '#30363d',
        gridDay: '#1c2128',
        rowLine: '#21262d',
        textMain: '#e6edf3',
        textParent: '#93c5fd',
        textSub: '#c9d1d9',
        textMuted: '#8b949e',
        textWeekend: '#6e7681',
        toggleBg: '#21262d',
        toggleBorder: '#30363d',
        toggleIcon: '#8b949e',
        toggleCollapsedBg: 'rgba(37, 99, 235, 0.25)',
        toggleCollapsedBorder: '#3b82f6',
        toggleCollapsedIcon: '#93c5fd',
        arrowColor: '#94a3b8',
        avatarRing: '#30363d'
      }}
    : {{
        bg: '#ffffff',
        headerBg: '#f8fafc',
        stageBandBg: '#f1f5f9',
        rowEven: '#ffffff',
        rowOdd: '#fcfdff',
        weekendBg: '#f8fafc',
        borderStrong: '#cbd5e1',
        gridMonday: '#cbd5e1',
        gridDay: '#f1f5f9',
        rowLine: '#f1f5f9',
        textMain: '#0f172a',
        textParent: '#1e3a8a',
        textSub: '#334155',
        textMuted: '#64748b',
        textWeekend: '#94a3b8',
        toggleBg: '#f1f5f9',
        toggleBorder: '#cbd5e1',
        toggleIcon: '#475569',
        toggleCollapsedBg: '#dbeafe',
        toggleCollapsedBorder: '#93c5fd',
        toggleCollapsedIcon: '#1d4ed8',
        arrowColor: '#7c8da6',
        avatarRing: '#cbd5e1'
      }};

  const svgParts = [];
  svgParts.push(`<svg id="gantt-svg" xmlns="http://www.w3.org/2000/svg" width="${{chartWidth}}" height="${{chartHeight}}" style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; display: block; background: ${{T.bg}};">`);

  // Definicje grotów strzałek
  svgParts.push(`
    <defs>
      <marker id="arrow-dep" viewBox="0 0 10 10" refX="7" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse">
        <path d="M 0 1.5 L 8.5 5 L 0 8.5 z" fill="${{T.arrowColor}}" />
      </marker>
      <marker id="arrow-hier" viewBox="0 0 10 10" refX="7" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse">
        <path d="M 0 1.5 L 8.5 5 L 0 8.5 z" fill="#64748b" />
      </marker>
    </defs>
  `);

  // Tło całego wykresu i nagłówka
  svgParts.push(`<rect x="0" y="0" width="${{chartWidth}}" height="${{chartHeight}}" fill="${{T.bg}}" />`);
  svgParts.push(`<rect x="0" y="0" width="${{chartWidth}}" height="${{headerHeight}}" fill="${{T.headerBg}}" />`);
  svgParts.push(`<line x1="0" y1="${{headerHeight}}" x2="${{chartWidth}}" y2="${{headerHeight}}" stroke="${{T.borderStrong}}" stroke-width="1" />`);

  const colHeaderY = milestoneBandHeight > 0 ? (headerHeight - 7) : 34;
  svgParts.push(`<text x="16" y="${{colHeaderY}}" font-size="13" font-weight="700" fill="${{T.textMain}}">PBL Gantta</text>`);
  svgParts.push(`<text x="${{leftColWidth - 85}}" y="${{colHeaderY}}" font-size="12" font-weight="600" fill="${{T.textMuted}}">Start &rarr; Koniec</text>`);

  // Siatka pionowa dni i nagłówki dat (Rok-Miesiąc u samej góry, a Dni pod pasem kamieni milowych)
  for (let i = 0; i < totalDays; i++) {{
    const cur = addDays(minDate, i);
    const x = leftColWidth + i * dayWidth;
    const dayOfWeek = cur.getUTCDay();
    const isWeekend = (dayOfWeek === 0 || dayOfWeek === 6);
    const dayNum = cur.getUTCDate();
    const monthStr = cur.toISOString().slice(0, 7);

    if (isWeekend) {{
      svgParts.push(`<rect x="${{x}}" y="${{headerHeight}}" width="${{dayWidth}}" height="${{chartHeight - headerHeight}}" fill="${{T.weekendBg}}" />`);
    }}

    svgParts.push(`<line x1="${{x}}" y1="${{headerHeight - dayRowHeight}}" x2="${{x}}" y2="${{chartHeight}}" stroke="${{dayOfWeek === 1 ? T.gridMonday : T.gridDay}}" stroke-width="1" />`);

    if (dayNum === 1 || i === 0) {{
      svgParts.push(`<text x="${{x + 4}}" y="18" font-size="11" font-weight="700" fill="${{T.textMain}}">${{monthStr}}</text>`);
    }}
    if (dayWidth >= 22 || dayOfWeek === 1) {{
      svgParts.push(`<text x="${{x + dayWidth / 2}}" y="${{headerHeight - 7}}" font-size="10" text-anchor="middle" fill="${{isWeekend ? T.textWeekend : T.textMuted}}">${{String(dayNum).padStart(2, '0')}}</text>`);
    }}
  }}

  // Strefy tła oraz pionowe przerywane linie początku i końca każdego Etapu
  stageItems.forEach((stage, sIdx) => {{
    const dInfo = dateInfo.get(stage.number);
    if (!dInfo) return;
    const pal = STAGE_PALETTE[sIdx % STAGE_PALETTE.length];
    const zoneBg = isDarkMode ? pal.zoneBgDark : pal.zoneBgLight;
    const startOffset = diffDays(minDate, dInfo.start);
    const durationDays = Math.max(1, diffDays(dInfo.start, dInfo.end) + 1);
    const zoneX = leftColWidth + startOffset * dayWidth;
    const zoneW = durationDays * dayWidth;
    svgParts.push(`<rect x="${{zoneX}}" y="${{headerHeight}}" width="${{zoneW}}" height="${{chartHeight - headerHeight}}" fill="${{zoneBg}}" />`);
    svgParts.push(`<line x1="${{zoneX}}" y1="${{headerHeight}}" x2="${{zoneX}}" y2="${{chartHeight}}" stroke="${{pal.border}}" stroke-width="1.3" stroke-dasharray="6 4" opacity="0.55" />`);
    svgParts.push(`<line x1="${{zoneX + zoneW}}" y1="${{headerHeight}}" x2="${{zoneX + zoneW}}" y2="${{chartHeight}}" stroke="${{pal.border}}" stroke-width="1.3" stroke-dasharray="6 4" opacity="0.55" />`);
  }});

  // PAS KAMIENI MILOWYCH (Milestones) – POD ROKIEM/MIESIĄCEM, A NAD DNIAMI (kolor zielony)
  if (showMilestones && milestones.length > 0) {{
    const mBandY = monthRowHeight;
    const mMidY = mBandY + milestoneBandHeight / 2;
    const mBadgeBg = isDarkMode ? 'rgba(34, 197, 94, 0.20)' : '#dcfce7';
    const mBadgeText = isDarkMode ? '#86efac' : '#166534';
    const mBadgeBorder = '#22c55e';

    svgParts.push(`<line x1="0" y1="${{mBandY}}" x2="${{chartWidth}}" y2="${{mBandY}}" stroke="${{T.rowLine}}" stroke-width="1" />`);
    svgParts.push(`<line x1="0" y1="${{mBandY + milestoneBandHeight}}" x2="${{chartWidth}}" y2="${{mBandY + milestoneBandHeight}}" stroke="${{T.rowLine}}" stroke-width="1" />`);
    svgParts.push(`<text x="16" y="${{mBandY + 18}}" font-size="11.5" font-weight="700" fill="${{mBadgeText}}">&#9670; Kamienie milowe (${{milestones.length}}):</text>`);

    milestones.forEach((m, mIdx) => {{
      const dueOffset = diffDays(minDate, m.dueDate) + 1;
      const mX = leftColWidth + dueOffset * dayWidth;
      const labelStr = `#${{m.number}} ${{m.title}} (${{m.dueStr}})`;
      const badgeW = Math.min(360, Math.max(120, labelStr.length * 6.0 + 18));
      const badgeX = Math.max(leftColWidth + 4, mX - badgeW - 9);

      // Pionowa zielona linia przerywana kamienia milowego od pasa kamieni milowych przez cały wykres
      svgParts.push(`<line x1="${{mX}}" y1="${{mMidY}}" x2="${{mX}}" y2="${{chartHeight}}" stroke="#22c55e" stroke-width="1.5" stroke-dasharray="4 3" opacity="0.8" />`);

      // Zielona pastylka opisu kamienia milowego oraz zielony romb ◆ na linii docelowej daty
      svgParts.push(`
        <g class="milestone-marker" style="cursor:pointer;" onmouseenter="showMilestoneTooltip(event, ${{mIdx}})" onmouseleave="hideTooltip()">
          <rect x="${{badgeX}}" y="${{mBandY + 3}}" width="${{badgeW}}" height="22" rx="11" fill="${{mBadgeBg}}" stroke="${{mBadgeBorder}}" stroke-width="1.2" />
          <text x="${{badgeX + badgeW / 2}}" y="${{mBandY + 17.5}}" font-size="10.5" font-weight="600" text-anchor="middle" fill="${{mBadgeText}}">${{escapeXml(labelStr)}}</text>
          <polygon points="${{mX}},${{mMidY - 6.5}} ${{mX + 6.5}},${{mMidY}} ${{mX}},${{mMidY + 6.5}} ${{mX - 6.5}},${{mMidY}}" fill="#22c55e" stroke="${{isDarkMode ? '#0d1117' : '#ffffff'}}" stroke-width="1.5" />
        </g>
      `);
    }});
  }}

  // Wiersze i paski zadań
  const barCoords = new Map();
  const topAvatarsLayer = [];

  // GÓRNY PAS ETAPÓW (pastylki etapów obok siebie u samej góry + daty rozpoczęcia i zakończenia na pastylce)
  svgParts.push(`<rect x="0" y="${{headerHeight}}" width="${{chartWidth}}" height="${{stageBandHeight}}" fill="${{T.stageBandBg}}" opacity="0.85" />`);
  svgParts.push(`<line x1="0" y1="${{rowsStartY}}" x2="${{chartWidth}}" y2="${{rowsStartY}}" stroke="${{T.borderStrong}}" stroke-width="1.5" />`);

  // W lewym panelu górnego pasa: klikalne przyciski Etapów do zwijania/rozwijania
  svgParts.push(`<text x="16" y="${{headerHeight + 24}}" font-size="12" font-weight="700" fill="${{T.textMain}}">Etapy:</text>`);
  let stageChipX = 64;
  stageItems.forEach((stage, sIdx) => {{
    const pal = STAGE_PALETTE[sIdx % STAGE_PALETTE.length];
    const chipBg = isDarkMode ? pal.chipBgDark : pal.chipBgLight;
    const chipText = isDarkMode ? pal.chipTextDark : pal.chipTextLight;
    const isCollapsed = collapsedNodes.has(stage.number);
    const totalDesc = descendantCountMap.get(stage.number) || 0;
    const iconChar = isCollapsed ? '&#9654;' : '&#9660;';
    const chipLabel = `#${{stage.number}} ${{stage.title}}${{isCollapsed ? ' [+' + totalDesc + ']' : ''}}`;
    const chipW = Math.max(76, chipLabel.length * 6.5 + 24);
    svgParts.push(`
      <g class="tree-toggle" onclick="toggleNode(${{stage.number}}, event)">
        <rect x="${{stageChipX}}" y="${{headerHeight + 9}}" width="${{chipW}}" height="22" rx="6" fill="${{chipBg}}" stroke="${{pal.border}}" stroke-width="1" />
        <text x="${{stageChipX + 10}}" y="${{headerHeight + 24}}" font-size="11" font-weight="600" fill="${{chipText}}">${{iconChar}} ${{escapeXml(chipLabel)}}</text>
      </g>
    `);
    stageChipX += chipW + 8;

    // Pastylka Etapu na osi czasu (u samej góry, obok siebie!)
    const dInfo = dateInfo.get(stage.number);
    if (dInfo) {{
      const startOffset = diffDays(minDate, dInfo.start);
      const durationDays = Math.max(1, diffDays(dInfo.start, dInfo.end) + 1);
      const barX = leftColWidth + startOffset * dayWidth + 2;
      const barW = Math.max(24, durationDays * dayWidth - 4);
      const barY = headerHeight + 7;
      const barH = 26;
      const pillRadius = barH / 2;

      barCoords.set(stage.number, {{
        x: barX,
        y: barY,
        w: barW,
        h: barH,
        midY: barY + barH / 2,
        rightX: barX + barW,
        leftX: barX
      }});

      const startStr = formatDate(dInfo.start);
      const endStr = formatDate(dInfo.end);
      const fullStageLabel = `${{stage.title}}  •  ${{startStr}} – ${{endStr}}`;
      const maxStageChars = Math.max(8, Math.floor((barW - 18) / 6.5));
      const stagePillText = fullStageLabel.length > maxStageChars
        ? `${{stage.title}} (${{startStr.slice(5)}}..${{endStr.slice(5)}})`
        : fullStageLabel;

      svgParts.push(`
        <g class="task-bar" data-num="${{stage.number}}" onclick="toggleNode(${{stage.number}}, event)" style="cursor:pointer;" onmouseenter="showTooltip(event, ${{stage.number}})" onmouseleave="hideTooltip()">
          <rect x="${{barX}}" y="${{barY}}" width="${{barW}}" height="${{barH}}" rx="${{pillRadius}}" ry="${{pillRadius}}" fill="${{pal.stageFill}}" />
          <text x="${{barX + barW / 2}}" y="${{barY + barH / 2 + 4}}" font-size="11.5" text-anchor="middle" fill="#ffffff" font-weight="700">${{escapeXml(stagePillText)}}</text>
        </g>
      `);
    }}
  }});

  visibleRows.forEach(({{ item, depth, stageIdx }}, idx) => {{
    const y = rowsStartY + idx * rowHeight;
    const dInfo = dateInfo.get(item.number);
    const pal = STAGE_PALETTE[(stageIdx || 0) % STAGE_PALETTE.length];
    const allChildren = childrenMap.get(item.number) || [];
    const visibleInModeChildren = allChildren.filter(c => modeFilteredSet.has(c));
    const hasCollapsibleChildren = visibleInModeChildren.length > 0;
    const isCollapsed = collapsedNodes.has(item.number);
    const totalDesc = descendantCountMap.get(item.number) || allChildren.length;

    // Tło wiersza
    svgParts.push(`<rect x="0" y="${{y}}" width="${{leftColWidth}}" height="${{rowHeight}}" fill="${{idx % 2 === 0 ? T.rowEven : T.rowOdd}}" opacity="0.92" />`);
    svgParts.push(`<line x1="0" y1="${{y + rowHeight}}" x2="${{chartWidth}}" y2="${{y + rowHeight}}" stroke="${{T.rowLine}}" stroke-width="1" />`);

    // Wcięcie i przycisk zwijania/rozwijania drzewa (depth - 1 bo Etapy są u góry)
    const indent = 12 + Math.max(0, depth - 1) * 18;
    const textStartX = indent + 20;
    const rawTitle = `#${{item.number}} ${{item.title || ''}}`;
    const reserveRight = isCollapsed ? 130 : 95;
    const maxChars = Math.max(16, Math.floor((leftColWidth - reserveRight - textStartX) / 6.5));
    const truncatedTitle = rawTitle.length > maxChars ? rawTitle.slice(0, maxChars - 1) + '…' : rawTitle;
    const fontWeight = allChildren.length > 0 ? '600' : '400';
    const textColor = allChildren.length > 0 ? T.textParent : T.textSub;

    if (hasCollapsibleChildren) {{
      const iconChar = isCollapsed ? '&#9654;' : '&#9660;';
      const badgeText = isCollapsed ? ` [+${{totalDesc}}]` : '';
      svgParts.push(`
        <g class="tree-toggle" onclick="toggleNode(${{item.number}}, event)">
          <rect class="toggle-hit" x="${{indent - 4}}" y="${{y + 4}}" width="${{leftColWidth - indent - 90}}" height="${{rowHeight - 8}}" rx="4" fill="transparent" />
          <rect x="${{indent}}" y="${{y + 9}}" width="16" height="16" rx="3" fill="${{isCollapsed ? T.toggleCollapsedBg : T.toggleBg}}" stroke="${{isCollapsed ? T.toggleCollapsedBorder : T.toggleBorder}}" stroke-width="1" />
          <text x="${{indent + 8}}" y="${{y + 20}}" font-size="9" text-anchor="middle" fill="${{isCollapsed ? T.toggleCollapsedIcon : T.toggleIcon}}">${{iconChar}}</text>
          <text x="${{textStartX}}" y="${{y + 22}}" font-size="12" font-weight="${{fontWeight}}" fill="${{textColor}}">
            ${{escapeXml(truncatedTitle)}}<tspan fill="#3b82f6" font-size="11" font-weight="700">${{badgeText}}</tspan>
          </text>
        </g>
      `);
    }} else {{
      // Kropka dla liścia (zadania bez widocznych podzadań)
      svgParts.push(`
        <circle cx="${{indent + 8}}" cy="${{y + 17}}" r="2.2" fill="${{T.textMuted}}" />
        <text x="${{textStartX}}" y="${{y + 22}}" font-size="12" font-weight="${{fontWeight}}" fill="${{textColor}}">${{escapeXml(truncatedTitle)}}</text>
      `);
    }}

    const assignees = item.assignees || [];
    const st = getStatusStyle(item, isDarkMode);

    if (dInfo) {{
      const dateLabel = `${{formatDate(dInfo.start).slice(5)}}..${{formatDate(dInfo.end).slice(5)}}`;
      svgParts.push(`<text x="${{leftColWidth - 85}}" y="${{y + 22}}" font-size="10.5" fill="${{T.textMuted}}">${{dateLabel}}</text>`);

      const startOffset = diffDays(minDate, dInfo.start);
      const durationDays = Math.max(1, diffDays(dInfo.start, dInfo.end) + 1);
      const barX = leftColWidth + startOffset * dayWidth + 2;
      const barW = Math.max(12, durationDays * dayWidth - 4);
      const barY = y + 7;
      const barH = 22;

      // Kolor pastylki na wykresie bezpośrednio nawiązuje do jej stanu (Statusu) z GitHuba
      const fill = st.barFill;
      const barStroke = st.barStroke;

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
        const initials = (login || '?').slice(0, 2).toUpperCase();
        const avatarHref = AVATAR_MAP[login] || `https://avatars.githubusercontent.com/${{encodeURIComponent(login)}}?size=48`;
        barAvatarsSvg += `
          <clipPath id="${{bClipId}}">
            <circle cx="${{bx + 9}}" cy="${{by + 9}}" r="9" />
          </clipPath>
          <circle cx="${{bx + 9}}" cy="${{by + 9}}" r="9" fill="${{T.toggleBg}}" />
          <text x="${{bx + 9}}" y="${{by + 12}}" font-size="7.5" font-weight="700" text-anchor="middle" fill="${{T.textMuted}}">${{escapeXml(initials)}}</text>
          <image data-login="${{escapeXml(login)}}" href="${{avatarHref}}" onerror="this.remove()" x="${{bx}}" y="${{by}}" width="18" height="18" clip-path="url(#${{bClipId}})" />
          <circle cx="${{bx + 9}}" cy="${{by + 9}}" r="9" fill="none" stroke="${{T.avatarRing}}" stroke-width="1" />
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
        barTextSvg = `<text x="${{barX + barW + 6 + barAvatarOffset}}" y="${{barY + barH / 2 + 4}}" font-size="11" fill="${{T.textSub}}" font-weight="500">${{escapeXml(cleanBarTitle)}}</text>`;
      }}

      const clickAttr = hasCollapsibleChildren ? `onclick="toggleNode(${{item.number}}, event)" style="cursor:pointer;"` : '';
      const pillRadius = barH / 2;
      svgParts.push(`
        <g class="task-bar" data-num="${{item.number}}" ${{clickAttr}} onmouseenter="showTooltip(event, ${{item.number}})" onmouseleave="hideTooltip()">
          <rect x="${{barX}}" y="${{barY}}" width="${{barW}}" height="${{barH}}" rx="${{pillRadius}}" ry="${{pillRadius}}" fill="${{fill}}" stroke="${{barStroke}}" stroke-width="1.2" />
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
  svgParts.push(`<line x1="${{leftColWidth}}" y1="0" x2="${{leftColWidth}}" y2="${{chartHeight}}" stroke="${{T.borderStrong}}" stroke-width="1.5" />`);

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

  // 2) Strzałki zależności (Blocked by / Blocking)
  // Obsługa zarówno rozgałęzienia (1 -> wiele, np. #71 -> #72, #73, #75),
  // jak i złączenia (wiele -> 1, np. #65 i #83 -> #66 oraz #76 i #78 -> #77), dokładnie jak na rysunku!
  if (showDepArrows) {{
    const drawnPairs = new Set();
    const validEdges = [];
    const predsByTarget = new Map();
    const succsBySource = new Map();

    depEdges.forEach(edge => {{
      const visFrom = getVisibleRepresentative(edge.from, visibleSet);
      const visTo = getVisibleRepresentative(edge.to, visibleSet);
      if (visFrom == null || visTo == null || visFrom === visTo) return;
      if (!barCoords.has(visFrom) || !barCoords.has(visTo)) return;

      const pairKey = `${{visFrom}}->${{visTo}}`;
      if (drawnPairs.has(pairKey)) return;
      drawnPairs.add(pairKey);

      validEdges.push({{ visFrom, visTo }});
      if (!predsByTarget.has(visTo)) predsByTarget.set(visTo, []);
      predsByTarget.get(visTo).push(visFrom);
      if (!succsBySource.has(visFrom)) succsBySource.set(visFrom, []);
      succsBySource.get(visFrom).push(visTo);
    }});

    const depStrokes = [];

    validEdges.forEach(({{ visFrom, visTo }}) => {{
      const from = barCoords.get(visFrom);
      const to = barCoords.get(visTo);

      const x1 = from.rightX;
      const y1 = from.midY;
      const x2 = to.leftX;
      const y2 = to.midY;
      const goingDown = y2 >= y1;

      // Sprawdź wszystkich poprzedników tego samego celu (np. #65 i #83 dla #66)
      const allPreds = (predsByTarget.get(visTo) || []).map(p => barCoords.get(p)).filter(Boolean);
      const maxPredRightX = allPreds.length > 0
        ? Math.max(...allPreds.map(p => p.rightX))
        : x1;

      const stepOut = Math.max(x1, maxPredRightX) + 14;
      const trunkX = x2 - 14;

      // Wyznacz korytarz poziomy (corridorY):
      // - Jeśli wiele zadań wchodzi do jednego celu (np. #65 i #83 -> #66), schodzimy wspólną linią z prawej strony
      //   aż pod ostatniego poprzednika (tuż nad docelową pastylkę #66) i tam zawracamy w lewo!
      // - Jeśli jedno zadanie rozgałęzia się na wiele (np. #71 -> #72, #73, #75), zawracamy w lewo tuż pod #71 (nad pierwszym następnikiem #72)
      //   i schodzimy wspólną linią z lewej strony!
      let corridorY;
      if (goingDown) {{
        const predsAboveTo = allPreds.filter(p => p.midY <= y2);
        if (predsAboveTo.length > 1) {{
          const lowestPred = predsAboveTo.reduce((acc, p) => (p.y + p.h > acc.y + acc.h ? p : acc), from);
          corridorY = lowestPred.y + lowestPred.h + (rowHeight - lowestPred.h) / 2;
        }} else {{
          corridorY = from.y + from.h + (rowHeight - from.h) / 2;
        }}
      }} else {{
        const predsBelowTo = allPreds.filter(p => p.midY > y2);
        if (predsBelowTo.length > 1) {{
          const highestPred = predsBelowTo.reduce((acc, p) => (p.y < acc.y ? p : acc), from);
          corridorY = highestPred.y - (rowHeight - highestPred.h) / 2;
        }} else {{
          corridorY = from.y - (rowHeight - from.h) / 2;
        }}
      }}

      let pts;
      if (trunkX >= stepOut) {{
        pts = [[x1, y1], [trunkX, y1], [trunkX, y2], [x2 - 2, y2]];
      }} else {{
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
        <path d="${{dPath}}" fill="none" stroke="${{T.arrowColor}}" stroke-width="1.8" stroke-linejoin="round" stroke-linecap="round" marker-end="url(#arrow-dep)" />
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
  document.getElementById('project-title').textContent = `PBL Gantta – ${{pTitle}}`;
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

  const st = getStatusStyle(it, true);
  let html = `<div><strong>#${{it.number}} ${{escapeXml(it.title)}}</strong></div>`;
  html += `<div style="color:#cbd5e1; margin-top:4px;">Stan: <span style="display:inline-flex;align-items:center;gap:5px;padding:1px 8px;border-radius:10px;background:${{st.badgeBg}};border:1px solid ${{st.badgeBorder}};color:${{st.textColor}};font-weight:600;"><span style="width:8px;height:8px;border-radius:50%;background:${{st.fill}};border:2px solid ${{st.ring}};display:inline-block;"></span>${{escapeXml(st.label)}}</span></div>`;
  html += `<div style="color:#cbd5e1; margin-top:4px;">Start: <b>${{formatDate(dInfo.start)}}</b> | Koniec: <b>${{formatDate(dInfo.end)}}</b></div>`;
  const assignees = it.assignees || [];
  if (assignees.length > 0) {{
    const avatarsHtml = assignees.map(u => `<span style="display:inline-flex;align-items:center;gap:4px;background:#1e293b;padding:2px 6px;border-radius:12px;margin-right:4px;"><img src="https://github.com/${{encodeURIComponent(u)}}.png?size=32" style="width:14px;height:14px;border-radius:50%;"/>${{escapeXml(u)}}</span>`).join('');
    html += `<div style="margin-top:5px;">Przypisani: ${{avatarsHtml}}</div>`;
  }} else {{
    html += `<div style="color:#64748b; margin-top:2px;">Przypisani: <i>brak</i></div>`;
  }}
  html += `<div style="color:#94a3b8; margin-top:2px;">Rodzic (Parent): ${{escapeXml(parentStr)}}</div>`;
  if (it.milestone && it.milestone.title) {{
    const mDue = it.milestone.due_on ? ` (${{it.milestone.due_on.slice(0, 10)}})` : '';
    html += `<div style="color:#86efac; margin-top:3px;">&#9670; Kamień milowy: <b>#${{it.milestone.number}} ${{escapeXml(it.milestone.title)}}${{mDue}}</b></div>`;
  }}
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

function showMilestoneTooltip(evt, mIdx) {{
  const m = MODEL.milestones[mIdx];
  if (!m) return;
  let html = `<div style="color:#86efac;"><strong>&#9670; Kamień milowy #${{m.number}}: ${{escapeXml(m.title)}}</strong></div>`;
  html += `<div style="color:#cbd5e1; margin-top:4px;">Termin (Due date): <b>${{m.dueStr}}</b> | Status: <b>${{escapeXml(m.state)}}</b></div>`;
  const tt = document.getElementById('tooltip');
  tt.innerHTML = html;
  tt.style.display = 'block';
  tt.style.left = (evt.clientX + 14) + 'px';
  tt.style.top = (evt.clientY + 14) + 'px';
}}

function hideTooltip() {{
  document.getElementById('tooltip').style.display = 'none';
}}

const avatarDataUrlCache = new Map();

async function fetchAvatarAsDataUrl(url) {{
  if (avatarDataUrlCache.has(url)) return avatarDataUrlCache.get(url);
  try {{
    const resp = await fetch(url, {{ mode: 'cors', credentials: 'omit' }});
    if (!resp.ok) return null;
    const blob = await resp.blob();
    const dataUrl = await new Promise((resolve) => {{
      const reader = new FileReader();
      reader.onloadend = () => resolve(reader.result);
      reader.onerror = () => resolve(null);
      reader.readAsDataURL(blob);
    }});
    if (dataUrl) avatarDataUrlCache.set(url, dataUrl);
    return dataUrl;
  }} catch (e) {{
    return null;
  }}
}}

async function downloadPNG() {{
  const svgEl = document.getElementById('gantt-svg');
  if (!svgEl) return;
  const btn = document.getElementById('png-btn');
  const origText = btn ? btn.textContent : '';
  if (btn) {{
    btn.textContent = '⏳ Generowanie PNG...';
    btn.disabled = true;
  }}

  try {{
    const clone = svgEl.cloneNode(true);
    const width = parseInt(svgEl.getAttribute('width'), 10) || svgEl.clientWidth || 1400;
    const height = parseInt(svgEl.getAttribute('height'), 10) || svgEl.clientHeight || 800;

    // Zamień zewnętrzne obrazy awatarów na wbudowane data:image/png;base64, aby płótno Canvas (PNG) zawierało awatary i nie rzucało błędu CORS
    const images = Array.from(clone.querySelectorAll('image'));
    await Promise.all(images.map(async (imgEl) => {{
      const href = imgEl.getAttribute('href') || imgEl.getAttribute('xlink:href');
      if (!href || href.startsWith('data:')) return;
      const dataUrl = await fetchAvatarAsDataUrl(href);
      if (dataUrl) {{
        imgEl.setAttribute('href', dataUrl);
      }} else {{
        // Jeśli brak sieci, zostaw inicjały pod spodem
        imgEl.remove();
      }}
    }}));

    const serializer = new XMLSerializer();
    const svgString = serializer.serializeToString(clone);
    const svgBlob = new Blob([svgString], {{ type: 'image/svg+xml;charset=utf-8' }});
    const url = URL.createObjectURL(svgBlob);

    const img = new Image();
    img.onload = () => {{
      const scale = 2; // Jakość Retina 2x
      const canvas = document.createElement('canvas');
      canvas.width = width * scale;
      canvas.height = height * scale;
      const ctx = canvas.getContext('2d');
      ctx.scale(scale, scale);
      ctx.drawImage(img, 0, 0, width, height);
      URL.revokeObjectURL(url);

      canvas.toBlob((pngBlob) => {{
        if (!pngBlob) return;
        const pngUrl = URL.createObjectURL(pngBlob);
        const a = document.createElement('a');
        a.href = pngUrl;
        a.download = 'pbl_gantt.png';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        setTimeout(() => URL.revokeObjectURL(pngUrl), 1000);
      }}, 'image/png');
    }};
    img.src = url;
  }} finally {{
    if (btn) {{
      btn.textContent = origText;
      btn.disabled = false;
    }}
  }}
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
document.getElementById('show-milestones').addEventListener('change', render);
document.getElementById('show-dep-arrows').addEventListener('change', render);
document.getElementById('show-hier-arrows').addEventListener('change', render);
document.getElementById('day-width').addEventListener('change', render);

// Domyślnie na starcie zwijamy podzadania do widoku: Etap -> Podetapy
collapseToDepth(1);

// Tryb czystego eksportu wykresu SVG (?export=1) dla automatycznego zapisu PNG bez pasków narzędzi i marginesów
if (window.location.search.includes('export=1')) {{
  const svgEl = document.getElementById('gantt-svg');
  if (svgEl) {{
    document.body.style.margin = '0';
    document.body.style.padding = '0';
    document.body.style.overflow = 'hidden';
    document.body.innerHTML = '';
    document.body.appendChild(svgEl);
  }}
}}
</script>
</body>
</html>
"""

    with open(output_html, "w", encoding="utf-8") as f:
        f.write(html_content)

    if output_png:
        png_res = render_png_from_html(output_html, output_png)
        if png_res:
            print(f"Wygenerowano obraz PNG wykresu Gantta: {png_res}")

    return os.path.abspath(output_html)


if __name__ == "__main__":
    json_file = sys.argv[1] if len(sys.argv) > 1 else "project_export.json"
    out_file = sys.argv[2] if len(sys.argv) > 2 else "gantt_chart.html"
    png_file = sys.argv[3] if len(sys.argv) > 3 else os.path.splitext(out_file)[0] + ".png"
    path = generate_gantt_html(json_file, out_file, png_file)
    print(f"Wygenerowano interaktywny wykres Gantta: {path}")
