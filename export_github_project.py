#!/usr/bin/env python3
"""
Eksport pełnych danych z GitHub Projects v2 (Issues, Sub-issues, Parents,
Relationships, Milestones oraz Custom Fields takie jak Start date / End date)
do plików JSON oraz CSV.

Nie wymaga instalacji zewnętrznych bibliotek (korzysta wyłącznie ze standardowej biblioteki Pythona).
"""

import argparse
import base64
import concurrent.futures
import csv
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple


GRAPHQL_URL = "https://api.github.com/graphql"

PROJECT_QUERY = """
query($owner: String!, $number: Int!, $cursor: String) {
  repositoryOwner(login: $owner) {
    login
    ... on ProjectV2Owner {
      projectV2(number: $number) {
        id
        number
        title
        shortDescription
        url
        closed
        fields(first: 50) {
          nodes {
            ... on ProjectV2FieldCommon {
              id
              name
              dataType
            }
          }
        }
        items(first: 100, after: $cursor) {
          totalCount
          pageInfo {
            hasNextPage
            endCursor
          }
          nodes {
            id
            type
            createdAt
            updatedAt
            isArchived
            fieldValues(first: 50) {
              nodes {
                __typename
                ... on ProjectV2ItemFieldTextValue {
                  text
                  field { ... on ProjectV2FieldCommon { name } }
                }
                ... on ProjectV2ItemFieldNumberValue {
                  number
                  field { ... on ProjectV2FieldCommon { name } }
                }
                ... on ProjectV2ItemFieldDateValue {
                  date
                  field { ... on ProjectV2FieldCommon { name } }
                }
                ... on ProjectV2ItemFieldSingleSelectValue {
                  name
                  field { ... on ProjectV2FieldCommon { name } }
                }
                ... on ProjectV2ItemFieldIterationValue {
                  title
                  startDate
                  duration
                  field { ... on ProjectV2FieldCommon { name } }
                }
              }
            }
            content {
              __typename
              ... on DraftIssue {
                title
                body
                createdAt
                updatedAt
                assignees(first: 20) {
                  nodes { login }
                }
              }
              ... on Issue {
                id
                number
                title
                url
                state
                stateReason
                body
                createdAt
                updatedAt
                closedAt
                repository {
                  nameWithOwner
                }
                issueType {
                  name
                }
                author {
                  login
                }
                assignees(first: 20) {
                  nodes { login }
                }
                labels(first: 30) {
                  nodes { name color }
                }
                milestone {
                  number
                  title
                  state
                  dueOn
                  description
                  url
                }
                parent {
                  number
                  title
                  state
                  url
                  repository { nameWithOwner }
                }
                subIssuesSummary {
                  total
                  completed
                  percentCompleted
                }
                subIssues(first: 100) {
                  totalCount
                  nodes {
                    number
                    title
                    state
                    url
                    repository { nameWithOwner }
                  }
                }
                trackedInIssues(first: 50) {
                  totalCount
                  nodes {
                    number
                    title
                    state
                    url
                    repository { nameWithOwner }
                  }
                }
                trackedIssues(first: 50) {
                  totalCount
                  nodes {
                    number
                    title
                    state
                    url
                    repository { nameWithOwner }
                  }
                }
                closedByPullRequestsReferences(first: 20) {
                  nodes {
                    number
                    title
                    state
                    url
                  }
                }
              }
              ... on PullRequest {
                id
                number
                title
                url
                state
                body
                createdAt
                updatedAt
                closedAt
                mergedAt
                repository {
                  nameWithOwner
                }
                author {
                  login
                }
                assignees(first: 20) {
                  nodes { login }
                }
                labels(first: 30) {
                  nodes { name }
                }
                milestone {
                  number
                  title
                  state
                  dueOn
                  url
                }
              }
            }
          }
        }
      }
    }
  }
}
"""


def get_github_token(explicit_token: Optional[str] = None) -> str:
    """Pobiera token z argumentu, zmiennej środowiskowej lub GitHub CLI (gh)."""
    if explicit_token:
        return explicit_token.strip()

    env_token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if env_token:
        return env_token.strip()

    try:
        result = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True,
            text=True,
            check=True,
        )
        token = result.stdout.strip()
        if token:
            return token
    except (subprocess.SubprocessError, FileNotFoundError):
        pass

    print(
        "Brak tokenu GitHub. Zaloguj się przez `gh auth login` (z uprawnieniem `read:project`),\n"
        "ustaw zmienną środowiskową GITHUB_TOKEN lub przekaż --token.",
        file=sys.stderr,
    )
    token = input("Wklej swój GitHub Personal Access Token (lub naciśnij Enter, aby przerwać): ").strip()
    if not token:
        sys.exit(1)
    return token


def parse_project_url(url: str) -> Tuple[str, int]:
    """Wyciąga ownera (user/org) i numer projektu z URL GitHub Projects."""
    pattern = r"github\.com/(?:users|orgs)/([^/]+)/projects/(\d+)"
    match = re.search(pattern, url)
    if not match:
        raise ValueError(
            f"Nieprawidłowy URL projektu: {url}. "
            "Oczekiwany format: https://github.com/users/LOGIN/projects/1 lub https://github.com/orgs/ORG/projects/1"
        )
    return match.group(1), int(match.group(2))


def execute_graphql(token: str, query: str, variables: Dict[str, Any]) -> Dict[str, Any]:
    """Wykonuje zapytanie GraphQL do API GitHuba z obsługą sub-issues."""
    payload = json.dumps({"query": query, "variables": variables}).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/vnd.github+json",
        "GraphQL-Features": "sub_issues",
        "User-Agent": "GitHub-Project-Exporter-Python",
    }

    req = urllib.request.Request(GRAPHQL_URL, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Błąd HTTP {e.code}: {err_body}") from e

    if "errors" in data:
        errors_str = json.dumps(data["errors"], indent=2, ensure_ascii=False)
        raise RuntimeError(
            f"Błąd GraphQL API:\n{errors_str}\n\n"
            "Wskazówka: Upewnij się, że Twój token ma uprawnienia `read:project` oraz `repo`\n"
            "(np. wykonaj: `gh auth refresh -s read:project,repo`)."
        )

    return data["data"]


def execute_rest_get(token: str, url: str) -> Any:
    """Wykonuje zapytanie GET do REST API GitHuba (np. dla Issue Dependencies)."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "GitHub-Project-Exporter-Python",
    }
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError:
        return []


def fetch_issue_dependencies(token: str, repo: str, issue_number: int) -> Dict[str, List[Dict[str, Any]]]:
    """Pobiera zależności 'blocked_by' oraz 'blocking' (strzałki na wykresie Gantta/Roadmap)."""
    base_url = f"https://api.github.com/repos/{repo}/issues/{issue_number}/dependencies"
    blocked_by_raw = execute_rest_get(token, f"{base_url}/blocked_by?per_page=100")
    blocking_raw = execute_rest_get(token, f"{base_url}/blocking?per_page=100")

    def simplify(items: Any) -> List[Dict[str, Any]]:
        if not isinstance(items, list):
            return []
        return [
            {
                "number": i.get("number"),
                "title": i.get("title"),
                "state": i.get("state"),
                "url": i.get("html_url") or i.get("url"),
            }
            for i in items
            if isinstance(i, dict)
        ]

    return {
        "blocked_by": simplify(blocked_by_raw),
        "blocking": simplify(blocking_raw),
    }


def extract_custom_fields(field_values_nodes: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Mapuje listę fieldValues z ProjectV2Item na prosty słownik {nazwa_pola: wartość}."""
    fields: Dict[str, Any] = {}
    for node in field_values_nodes:
        if not node:
            continue
        field_info = node.get("field") or {}
        field_name = field_info.get("name")
        if not field_name:
            continue

        typename = node.get("__typename")
        if typename == "ProjectV2ItemFieldTextValue":
            fields[field_name] = node.get("text")
        elif typename == "ProjectV2ItemFieldNumberValue":
            fields[field_name] = node.get("number")
        elif typename == "ProjectV2ItemFieldDateValue":
            fields[field_name] = node.get("date")
        elif typename == "ProjectV2ItemFieldSingleSelectValue":
            fields[field_name] = node.get("name")
        elif typename == "ProjectV2ItemFieldIterationValue":
            fields[field_name] = {
                "title": node.get("title"),
                "startDate": node.get("startDate"),
                "duration": node.get("duration"),
            }
    return fields


def normalize_item(raw_item: Dict[str, Any]) -> Dict[str, Any]:
    """Przekształca surowy węzeł ProjectV2Item w czytelny słownik ze wszystkimi relacjami."""
    custom_fields = extract_custom_fields(raw_item.get("fieldValues", {}).get("nodes", []))
    content = raw_item.get("content") or {}
    content_type = content.get("__typename") or raw_item.get("type")

    milestone = content.get("milestone")
    parent = content.get("parent")
    sub_issues = (content.get("subIssues") or {}).get("nodes", [])
    sub_summary = content.get("subIssuesSummary") or {}
    tracked_in = (content.get("trackedInIssues") or {}).get("nodes", [])
    tracked = (content.get("trackedIssues") or {}).get("nodes", [])
    linked_prs = (content.get("closedByPullRequestsReferences") or {}).get("nodes", [])
    assignees = [a["login"] for a in (content.get("assignees") or {}).get("nodes", []) if a]
    labels = [l["name"] for l in (content.get("labels") or {}).get("nodes", []) if l]

    return {
        "project_item_id": raw_item.get("id"),
        "type": content_type,
        "is_archived": raw_item.get("isArchived", False),
        "repository": (content.get("repository") or {}).get("nameWithOwner"),
        "number": content.get("number"),
        "title": content.get("title") or custom_fields.get("Title"),
        "url": content.get("url"),
        "state": content.get("state"),
        "state_reason": content.get("stateReason"),
        "issue_type": (content.get("issueType") or {}).get("name"),
        "author": (content.get("author") or {}).get("login"),
        "created_at": content.get("createdAt") or raw_item.get("createdAt"),
        "updated_at": content.get("updatedAt") or raw_item.get("updatedAt"),
        "closed_at": content.get("closedAt"),
        "assignees": assignees,
        "labels": labels,
        "project_fields": custom_fields,
        "milestone": {
            "number": milestone.get("number"),
            "title": milestone.get("title"),
            "state": milestone.get("state"),
            "due_on": milestone.get("dueOn"),
            "description": milestone.get("description"),
            "url": milestone.get("url"),
        }
        if milestone
        else None,
        "parent_issue": {
            "number": parent.get("number"),
            "title": parent.get("title"),
            "state": parent.get("state"),
            "url": parent.get("url"),
            "repository": (parent.get("repository") or {}).get("nameWithOwner"),
        }
        if parent
        else None,
        "sub_issues_summary": {
            "total": sub_summary.get("total", 0),
            "completed": sub_summary.get("completed", 0),
            "percent_completed": sub_summary.get("percentCompleted", 0),
        }
        if sub_summary
        else None,
        "sub_issues": [
            {
                "number": s.get("number"),
                "title": s.get("title"),
                "state": s.get("state"),
                "url": s.get("url"),
                "repository": (s.get("repository") or {}).get("nameWithOwner"),
            }
            for s in sub_issues
            if s
        ],
        "relationships": {
            "tracked_in_issues": [
                {
                    "number": t.get("number"),
                    "title": t.get("title"),
                    "state": t.get("state"),
                    "url": t.get("url"),
                }
                for t in tracked_in
                if t
            ],
            "tracked_issues": [
                {
                    "number": t.get("number"),
                    "title": t.get("title"),
                    "state": t.get("state"),
                    "url": t.get("url"),
                }
                for t in tracked
                if t
            ],
            "linked_pull_requests": [
                {
                    "number": pr.get("number"),
                    "title": pr.get("title"),
                    "state": pr.get("state"),
                    "url": pr.get("url"),
                }
                for pr in linked_prs
                if pr
            ],
        },
        "body": content.get("body"),
    }


def fetch_full_project(token: str, owner: str, project_number: int) -> Dict[str, Any]:
    """Pobiera cały projekt z uwzględnieniem paginacji wszystkich elementów."""
    cursor: Optional[str] = None
    all_items: List[Dict[str, Any]] = []
    project_meta: Optional[Dict[str, Any]] = None
    page = 1

    while True:
        print(f"Pobieranie strony {page} z GitHub GraphQL API...")
        data = execute_graphql(
            token,
            PROJECT_QUERY,
            {"owner": owner, "number": project_number, "cursor": cursor},
        )

        repo_owner = data.get("repositoryOwner")
        if not repo_owner or not repo_owner.get("projectV2"):
            raise RuntimeError(
                f"Nie znaleziono projektu #{project_number} dla właściciela '{owner}'. "
                "Sprawdź login/organizację, numer projektu oraz uprawnienia tokenu (`read:project`)."
            )

        project = repo_owner["projectV2"]
        if project_meta is None:
            project_meta = {
                "id": project.get("id"),
                "number": project.get("number"),
                "title": project.get("title"),
                "short_description": project.get("shortDescription"),
                "url": project.get("url"),
                "closed": project.get("closed"),
                "owner": repo_owner.get("login"),
                "fields": [
                    f for f in (project.get("fields") or {}).get("nodes", []) if f
                ],
            }

        items_block = project["items"]
        nodes = items_block.get("nodes") or []
        for raw_node in nodes:
            if raw_node:
                all_items.append(normalize_item(raw_node))

        page_info = items_block.get("pageInfo") or {}
        if page_info.get("hasNextPage"):
            cursor = page_info.get("endCursor")
            page += 1
        else:
            break

    print(f"Pobieranie zależności (blocked_by / blocking) dla {len(all_items)} zadań (równolegle)...")

    def _populate_deps(item: Dict[str, Any]) -> None:
        repo = item.get("repository")
        num = item.get("number")
        if item.get("type") == "Issue" and repo and num:
            deps = fetch_issue_dependencies(token, repo, num)
            item["relationships"]["blocked_by"] = deps["blocked_by"]
            item["relationships"]["blocking"] = deps["blocking"]
        else:
            item["relationships"]["blocked_by"] = []
            item["relationships"]["blocking"] = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        list(executor.map(_populate_deps, all_items))

    # Pobierz awatary przypisanych użytkowników jako data:image/png;base64 (aby HTML i PNG działały również offline)
    unique_logins = sorted({u for item in all_items for u in (item.get("assignees") or []) if u})
    avatars_base64: Dict[str, str] = {}
    for login in unique_logins:
        avatar_url = f"https://avatars.githubusercontent.com/{urllib.parse.quote(login)}?size=64"
        try:
            req = urllib.request.Request(avatar_url, headers={"User-Agent": "PBL-Gantt-Exporter"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                raw = resp.read()
                ctype = resp.headers.get("Content-Type", "image/png").split(";")[0]
                avatars_base64[login] = f"data:{ctype};base64,{base64.b64encode(raw).decode('ascii')}"
        except Exception:
            pass

    return {
        "project": project_meta,
        "total_items": len(all_items),
        "avatars_base64": avatars_base64,
        "items": all_items,
    }


def export_to_csv(export_data: Dict[str, Any], csv_path: str) -> None:
    """Zapisuje spłaszczone dane projektu (wraz z dynamicznymi polami takimi jak Start/End Date) do CSV."""
    items = export_data.get("items", [])

    # Zbierz nazwy wszystkich niestandardowych pól z projektu (np. Status, Start date, End date, Priority)
    project_field_names: List[str] = []
    for f in (export_data.get("project") or {}).get("fields", []):
        name = f.get("name")
        if name and name not in ("Title", "Assignees", "Labels", "Milestone", "Repository", "Parent issue", "Sub-issues progress") and name not in project_field_names:
            project_field_names.append(name)

    for item in items:
        for k in item.get("project_fields", {}).keys():
            if k not in ("Title",) and k not in project_field_names:
                project_field_names.append(k)

    base_columns = [
        "number",
        "type",
        "title",
        "state",
        "issue_type",
        "repository",
        "url",
        "assignees",
        "labels",
        "milestone_title",
        "milestone_due_on",
        "milestone_state",
        "parent_issue_number",
        "parent_issue_title",
        "sub_issues_count",
        "sub_issues_completed",
        "sub_issues_list",
        "blocked_by",
        "blocking",
        "tracked_in_issues",
        "tracked_issues",
        "linked_prs",
        "created_at",
        "updated_at",
        "closed_at",
    ]
    custom_columns = [f"field:{name}" for name in project_field_names]
    fieldnames = base_columns + custom_columns + ["body"]

    with open(csv_path, mode="w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for item in items:
            milestone = item.get("milestone") or {}
            parent = item.get("parent_issue") or {}
            sub_summary = item.get("sub_issues_summary") or {}
            sub_issues = item.get("sub_issues") or []
            rels = item.get("relationships") or {}

            row: Dict[str, Any] = {
                "number": item.get("number", ""),
                "type": item.get("type", ""),
                "title": item.get("title", ""),
                "state": item.get("state", ""),
                "issue_type": item.get("issue_type", ""),
                "repository": item.get("repository", ""),
                "url": item.get("url", ""),
                "assignees": ", ".join(item.get("assignees", [])),
                "labels": ", ".join(item.get("labels", [])),
                "milestone_title": milestone.get("title", ""),
                "milestone_due_on": milestone.get("due_on", ""),
                "milestone_state": milestone.get("state", ""),
                "parent_issue_number": parent.get("number", ""),
                "parent_issue_title": parent.get("title", ""),
                "sub_issues_count": sub_summary.get("total", len(sub_issues)),
                "sub_issues_completed": sub_summary.get("completed", ""),
                "sub_issues_list": "; ".join(
                    f"#{s['number']} {s['title']} ({s['state']})" for s in sub_issues
                ),
                "blocked_by": "; ".join(
                    f"#{b['number']} {b['title']}" for b in rels.get("blocked_by", [])
                ),
                "blocking": "; ".join(
                    f"#{b['number']} {b['title']}" for b in rels.get("blocking", [])
                ),
                "tracked_in_issues": "; ".join(
                    f"#{t['number']} {t['title']}" for t in rels.get("tracked_in_issues", [])
                ),
                "tracked_issues": "; ".join(
                    f"#{t['number']} {t['title']}" for t in rels.get("tracked_issues", [])
                ),
                "linked_prs": "; ".join(
                    f"#{pr['number']} {pr['title']}" for pr in rels.get("linked_pull_requests", [])
                ),
                "created_at": item.get("created_at", ""),
                "updated_at": item.get("updated_at", ""),
                "closed_at": item.get("closed_at", ""),
                "body": item.get("body", ""),
            }

            p_fields = item.get("project_fields", {})
            for name in project_field_names:
                val = p_fields.get(name, "")
                if isinstance(val, dict):
                    # np. pole typu Iteration (Sprint)
                    val = f"{val.get('title', '')} ({val.get('startDate', '')}, {val.get('duration', '')}d)"
                row[f"field:{name}"] = val

            writer.writerow(row)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Eksportuje GitHub Project v2 (Issues, Sub-issues, Parents, Milestones, Custom Fields) do JSON i CSV."
    )
    parser.add_argument(
        "--url",
        help="Pełny URL projektu (np. https://github.com/users/LOGIN/projects/1 lub https://github.com/orgs/ORG/projects/1)",
    )
    parser.add_argument("--owner", help="Login użytkownika lub nazwa organizacji na GitHubie")
    parser.add_argument("--project-number", type=int, help="Numer projektu (widoczny w URL projektu)")
    parser.add_argument("--token", help="GitHub Personal Access Token (opcjonalnie, domyślnie używa GITHUB_TOKEN lub `gh auth token`)")
    parser.add_argument("--output-prefix", default="project_export", help="Prefiks plików wyjściowych (domyślnie: project_export)")

    args = parser.parse_args()

    owner = args.owner
    project_number = args.project_number

    if args.url:
        owner, project_number = parse_project_url(args.url)

    if not owner or not project_number:
        user_input = input(
            "Podaj URL projektu GitHub (np. https://github.com/users/LOGIN/projects/1) "
            "lub wpisz OWNER/NUMER (np. kamil/1): "
        ).strip()
        if "github.com" in user_input:
            owner, project_number = parse_project_url(user_input)
        elif "/" in user_input:
            parts = user_input.split("/", 1)
            owner = parts[0].strip()
            project_number = int(parts[1].strip())
        else:
            print("Nie podano poprawnego projektu.", file=sys.stderr)
            sys.exit(1)

    token = get_github_token(args.token)

    print(f"Eksportowanie projektu #{project_number} właściciela '{owner}'...")
    export_data = fetch_full_project(token, owner, project_number)

    json_path = f"{args.output_prefix}.json"
    csv_path = f"{args.output_prefix}.csv"

    with open(json_path, mode="w", encoding="utf-8") as f:
        json.dump(export_data, f, indent=2, ensure_ascii=False)

    export_to_csv(export_data, csv_path)

    gantt_path = f"{args.output_prefix}_gantt.html" if args.output_prefix != "project_export" else "gantt_chart.html"
    try:
        try:
            from generate_gantt import generate_gantt_html
        except ImportError:
            from wykres_gantta.generate_gantt import generate_gantt_html
        gantt_abs = generate_gantt_html(json_path, gantt_path)
    except Exception as exc:
        gantt_abs = f"(Nie udało się wygenerować HTML: {exc})"

    print(f"\nGotowe! Wyeksportowano {export_data['total_items']} elementów:")
    print(f"  - Pełny JSON (hierarchia i relacje): {os.path.abspath(json_path)}")
    print(f"  - Tabela CSV (gotowa do Excela):     {os.path.abspath(csv_path)}")
    print(f"  - Interaktywny Wykres Gantta (SVG):  {gantt_abs}")


if __name__ == "__main__":
    main()

