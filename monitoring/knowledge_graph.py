#!/usr/bin/env python3
"""Knowledge graph of the MARS development process.

Parses git log and working tree status to build a graph that shows
where the engineering process went wrong: big-bang commits, branch
divergence, file coupling, churn hotspots, orphaned work, and the
overall chaos timeline.

Usage:
  python3 knowledge_graph.py                   # run from repo root
  python3 knowledge_graph.py --repo /path/to/repo
  python3 knowledge_graph.py --out dev_graph.html
"""

import argparse
import json
import re
import subprocess
from collections import Counter, defaultdict
from pathlib import Path


# ═══════════════════════════════════════════════════════════════════════
#  Git data extraction
# ═══════════════════════════════════════════════════════════════════════

def _run(cmd, cwd=None):
    result = subprocess.run(
        cmd, capture_output=True, text=True, cwd=cwd, shell=True
    )
    return result.stdout.strip()


def extract_commits(repo_path):
    """Parse git log into structured commit objects."""
    raw = _run(
        'git log --all --numstat --format="COMMIT|%h|%an|%ad|%s" --date=iso',
        cwd=repo_path,
    )
    commits = []
    current = None

    for line in raw.splitlines():
        if line.startswith("COMMIT|"):
            if current:
                commits.append(current)
            parts = line.split("|", 4)
            current = {
                "hash": parts[1],
                "author": parts[2],
                "date": parts[3],
                "message": parts[4] if len(parts) > 4 else "",
                "files": [],
                "additions": 0,
                "deletions": 0,
            }
        elif current and line.strip():
            match = re.match(r"^(\d+|-)\t(\d+|-)\t(.+)$", line.strip())
            if match:
                adds = int(match.group(1)) if match.group(1) != "-" else 0
                dels = int(match.group(2)) if match.group(2) != "-" else 0
                filepath = match.group(3)
                current["files"].append({
                    "path": filepath,
                    "additions": adds,
                    "deletions": dels,
                })
                current["additions"] += adds
                current["deletions"] += dels

    if current:
        commits.append(current)

    return commits


def extract_branches(repo_path):
    """Get all branches and their relationships."""
    raw = _run("git branch -a --format='%(refname:short)|%(upstream:short)|%(HEAD)'", cwd=repo_path)
    branches = []
    for line in raw.splitlines():
        parts = line.strip().strip("'").split("|")
        if len(parts) >= 3:
            branches.append({
                "name": parts[0],
                "upstream": parts[1] if parts[1] else None,
                "is_head": parts[2].strip() == "*",
            })
    return branches


def extract_working_tree(repo_path):
    """Get current unstaged/untracked changes."""
    raw = _run("git status --short", cwd=repo_path)
    changes = []
    for line in raw.splitlines():
        if len(line) >= 4:
            status = line[:2].strip()
            filepath = line[3:].strip()
            # handle renames: "R  old -> new"
            if " -> " in filepath:
                old, new = filepath.split(" -> ", 1)
                changes.append({"status": status, "path": new, "old_path": old})
            else:
                changes.append({"status": status, "path": filepath, "old_path": None})
    return changes


def extract_branch_divergence(repo_path):
    """Find commits unique to each branch vs main."""
    # commits on current branch not in main
    ahead = _run("git log main..HEAD --oneline 2>/dev/null", cwd=repo_path)
    behind = _run("git log HEAD..main --oneline 2>/dev/null", cwd=repo_path)
    return {
        "ahead": len(ahead.splitlines()) if ahead else 0,
        "behind": len(behind.splitlines()) if behind else 0,
        "ahead_commits": ahead.splitlines() if ahead else [],
        "behind_commits": behind.splitlines() if behind else [],
    }


# ═══════════════════════════════════════════════════════════════════════
#  Graph construction
# ═══════════════════════════════════════════════════════════════════════

def _get_module(filepath):
    """Extract the top-level module/directory from a file path."""
    parts = Path(filepath).parts
    if len(parts) <= 1:
        return "root"
    return parts[0]


def _commit_size_class(commit):
    """Classify commit by size: normal, large, massive."""
    n = len(commit["files"])
    if n >= 15:
        return "massive"
    if n >= 8:
        return "large"
    return "normal"


def _time_label(date_str):
    """'2026-04-12 07:38:57 -0400' → 'Apr 12 07:38'"""
    try:
        # parse ISO-ish date from git
        parts = date_str.rsplit(" ", 1)  # strip timezone
        from datetime import datetime
        dt = datetime.fromisoformat(parts[0].replace(" ", "T"))
        return dt.strftime("%b %d %H:%M")
    except Exception:
        return date_str[:16]


def build_graph(commits, branches, working_tree, divergence):
    """Build the development knowledge graph.

    Node types:
      - commit: individual commits (sized by file count)
      - author: people who committed
      - file: files that were touched
      - module: top-level directories
      - branch: git branches
      - wt_change: working tree changes (uncommitted)

    Edge types:
      - authored: author → commit
      - touched: commit → file
      - contains: module → file
      - branched: branch → commit
      - coupled: file ↔ file (changed together)
      - renamed: old_path → new_path
      - uncommitted: wt_change cluster
    """
    nodes = {}
    edges = []
    analysis = {
        "smells": [],          # things that went wrong
        "hotspots": [],        # most-churned files
        "coupling": [],        # files always changed together
        "timeline": [],        # chronological story
        "big_bangs": [],       # oversized commits
        "orphan_work": [],     # work that got deleted or diverged
    }

    # ── Author nodes ──
    authors = set(c["author"] for c in commits)
    for author in authors:
        nid = f"author:{author}"
        commit_count = sum(1 for c in commits if c["author"] == author)
        total_lines = sum(c["additions"] + c["deletions"] for c in commits if c["author"] == author)
        nodes[nid] = {
            "id": nid, "label": author, "type": "author",
            "commit_count": commit_count, "total_lines": total_lines,
        }

    # ── Commit nodes ──
    for c in commits:
        nid = f"commit:{c['hash']}"
        size_class = _commit_size_class(c)
        nodes[nid] = {
            "id": nid,
            "label": f"{c['hash'][:7]}",
            "type": "commit",
            "message": c["message"],
            "author": c["author"],
            "date": _time_label(c["date"]),
            "file_count": len(c["files"]),
            "additions": c["additions"],
            "deletions": c["deletions"],
            "size_class": size_class,
        }
        # edge: author → commit
        edges.append({
            "source": f"author:{c['author']}",
            "target": nid,
            "type": "authored",
            "weight": 1,
        })

    # ── File nodes (aggregate across commits) ──
    file_touches = Counter()  # path → number of commits touching it
    file_churn = Counter()    # path → total lines changed
    for c in commits:
        for f in c["files"]:
            file_touches[f["path"]] += 1
            file_churn[f["path"]] += f["additions"] + f["deletions"]

    # only create nodes for files touched more than once OR with high churn
    # (otherwise the graph is too dense)
    interesting_files = set()
    for path, count in file_touches.items():
        if count > 1 or file_churn[path] > 100:
            interesting_files.add(path)
    # also include files from big commits
    for c in commits:
        if _commit_size_class(c) in ("large", "massive"):
            for f in c["files"]:
                interesting_files.add(f["path"])

    for path in interesting_files:
        nid = f"file:{path}"
        module = _get_module(path)
        nodes[nid] = {
            "id": nid,
            "label": Path(path).name,
            "type": "file",
            "full_path": path,
            "module": module,
            "touch_count": file_touches[path],
            "churn": file_churn[path],
            "is_hotspot": file_touches[path] > 2 or file_churn[path] > 200,
        }

    # ── Module nodes ──
    modules = set(_get_module(p) for p in interesting_files)
    for mod in modules:
        nid = f"module:{mod}"
        mod_files = [p for p in interesting_files if _get_module(p) == mod]
        nodes[nid] = {
            "id": nid, "label": f"{mod}/", "type": "module",
            "file_count": len(mod_files),
        }

    # ── Edges: commit → file (touched) ──
    for c in commits:
        for f in c["files"]:
            if f["path"] in interesting_files:
                edges.append({
                    "source": f"commit:{c['hash']}",
                    "target": f"file:{f['path']}",
                    "type": "touched",
                    "weight": f["additions"] + f["deletions"],
                    "label": f"+{f['additions']}/−{f['deletions']}",
                })

    # ── Edges: module → file (contains) ──
    for path in interesting_files:
        mod = _get_module(path)
        edges.append({
            "source": f"module:{mod}",
            "target": f"file:{path}",
            "type": "contains",
            "weight": 1,
        })

    # ── Branch nodes ──
    for b in branches:
        nid = f"branch:{b['name']}"
        nodes[nid] = {
            "id": nid, "label": b["name"], "type": "branch",
            "is_head": b.get("is_head", False),
        }

    # ── Working tree change nodes ──
    wt_renames = 0
    wt_new = 0
    wt_deleted = 0
    wt_modified = 0
    for change in working_tree:
        s = change["status"]
        if "R" in s:
            wt_renames += 1
        elif "?" in s:
            wt_new += 1
        elif "D" in s:
            wt_deleted += 1
        elif "M" in s:
            wt_modified += 1

    if working_tree:
        nid = "wt:uncommitted"
        nodes[nid] = {
            "id": nid,
            "label": f"UNCOMMITTED ({len(working_tree)} files)",
            "type": "wt_change",
            "total": len(working_tree),
            "renames": wt_renames,
            "new_files": wt_new,
            "deleted": wt_deleted,
            "modified": wt_modified,
        }

    # ── File coupling (files changed together across commits) ──
    coupling_counts = Counter()
    for c in commits:
        paths = [f["path"] for f in c["files"] if f["path"] in interesting_files]
        for i, p1 in enumerate(paths):
            for p2 in paths[i+1:]:
                key = tuple(sorted([p1, p2]))
                coupling_counts[key] += 1

    for (p1, p2), count in coupling_counts.most_common(20):
        if count >= 2:  # only show meaningful coupling
            edges.append({
                "source": f"file:{p1}",
                "target": f"file:{p2}",
                "type": "coupled",
                "weight": count,
                "label": f"coupled {count}x",
            })
            analysis["coupling"].append({
                "file_a": p1, "file_b": p2, "count": count,
            })

    # ═══════════════════════════════════════════════════════════════
    #  Analysis: where did the process go wrong?
    # ═══════════════════════════════════════════════════════════════

    # Timeline
    for c in sorted(commits, key=lambda x: x["date"]):
        analysis["timeline"].append({
            "hash": c["hash"],
            "author": c["author"],
            "date": _time_label(c["date"]),
            "message": c["message"],
            "files": len(c["files"]),
            "lines": c["additions"] + c["deletions"],
            "size_class": _commit_size_class(c),
        })

    # Big bang commits
    for c in commits:
        sc = _commit_size_class(c)
        if sc in ("large", "massive"):
            analysis["big_bangs"].append({
                "hash": c["hash"],
                "author": c["author"],
                "date": _time_label(c["date"]),
                "message": c["message"],
                "files": len(c["files"]),
                "lines": c["additions"] + c["deletions"],
                "size_class": sc,
            })

    # Hotspots
    for path, count in file_touches.most_common(15):
        if count >= 2:
            analysis["hotspots"].append({
                "path": path,
                "touches": count,
                "churn": file_churn[path],
            })

    # Smells (process anti-patterns)

    # 1. Giant initial commit
    if commits:
        first = min(commits, key=lambda c: c["date"])
        if len(first["files"]) >= 15:
            analysis["smells"].append({
                "type": "giant_initial_commit",
                "severity": "high",
                "message": f"Initial commit dropped {len(first['files'])} files and {first['additions']}+ lines at once. No incremental build-up.",
                "commit": first["hash"],
            })

    # 2. "wip" commits
    for c in commits:
        if c["message"].strip().lower() in ("wip", "wip.", "work in progress", "temp", "tmp"):
            analysis["smells"].append({
                "type": "wip_commit",
                "severity": "medium",
                "message": f"'{c['message']}' commit from {c['author']} -no context for future readers.",
                "commit": c["hash"],
            })

    # 3. Branch divergence without merge
    if divergence["ahead"] > 0 and divergence["behind"] > 0:
        analysis["smells"].append({
            "type": "branch_divergence",
            "severity": "high",
            "message": f"Current branch is {divergence['ahead']} commits ahead and {divergence['behind']} behind main. Branches diverged and never merged.",
        })
    elif divergence["ahead"] > 0:
        analysis["smells"].append({
            "type": "unmerged_branch",
            "severity": "medium",
            "message": f"Current branch is {divergence['ahead']} commits ahead of main. Work hasn't been integrated.",
        })

    # 4. Massive uncommitted changes
    if len(working_tree) >= 10:
        analysis["smells"].append({
            "type": "uncommitted_sprawl",
            "severity": "high",
            "message": f"{len(working_tree)} uncommitted changes including {wt_renames} renames, {wt_new} new files, {wt_deleted} deletions. Major restructure happening outside version control.",
        })

    # 5. Destructive README changes
    for c in commits:
        for f in c["files"]:
            if f["path"].endswith("README.md") and f["deletions"] > f["additions"] * 3 and f["deletions"] > 50:
                analysis["smells"].append({
                    "type": "readme_nuke",
                    "severity": "medium",
                    "message": f"{c['author']} deleted {f['deletions']} lines from README and added only {f['additions']}. Content nuke.",
                    "commit": c["hash"],
                })

    # 6. No small commits (everything is batched)
    normal_commits = [c for c in commits if _commit_size_class(c) == "normal"]
    if len(commits) > 2 and len(normal_commits) < len(commits) * 0.3:
        analysis["smells"].append({
            "type": "no_granularity",
            "severity": "high",
            "message": f"Only {len(normal_commits)}/{len(commits)} commits are reasonably sized. Work is being batched into massive drops instead of incremental progress.",
        })

    # 7. Single-person bus factor
    author_counts = Counter(c["author"] for c in commits)
    if len(author_counts) >= 2:
        top_author, top_count = author_counts.most_common(1)[0]
        if top_count >= len(commits) * 0.7:
            analysis["smells"].append({
                "type": "bus_factor",
                "severity": "medium",
                "message": f"{top_author} authored {top_count}/{len(commits)} commits. High bus factor -most knowledge concentrated in one person.",
            })

    # 8. Parallel work on same files without coordination
    author_files = defaultdict(set)
    for c in commits:
        for f in c["files"]:
            author_files[f["path"]].add(c["author"])
    contested = [(p, a) for p, a in author_files.items() if len(a) > 1]
    if contested:
        for path, authset in contested:
            analysis["smells"].append({
                "type": "contested_file",
                "severity": "medium",
                "message": f"{path} was edited by {', '.join(authset)} -potential merge conflicts or uncoordinated work.",
            })

    # 9. Orphaned work (files created then deleted)
    created_files = set()
    for c in sorted(commits, key=lambda x: x["date"]):
        for f in c["files"]:
            if f["additions"] > 0 and f["deletions"] == 0:
                created_files.add(f["path"])
    deleted_in_wt = set(ch["path"] for ch in working_tree if "D" in ch["status"])
    orphaned = created_files & deleted_in_wt
    if orphaned:
        analysis["orphan_work"].extend([{"path": p} for p in orphaned])
        analysis["smells"].append({
            "type": "orphaned_files",
            "severity": "low",
            "message": f"{len(orphaned)} files created in commits then deleted in working tree: {', '.join(list(orphaned)[:5])}",
        })

    return {"nodes": list(nodes.values()), "edges": edges, "analysis": analysis}


# ═══════════════════════════════════════════════════════════════════════
#  HTML visualization
# ═══════════════════════════════════════════════════════════════════════

def _node_color(node):
    t = node["type"]
    if t == "author":
        return "#60a5fa"       # blue
    if t == "commit":
        sc = node.get("size_class", "normal")
        if sc == "massive":
            return "#ef4444"   # red
        if sc == "large":
            return "#f59e0b"   # amber
        return "#34d399"       # green
    if t == "file":
        if node.get("is_hotspot"):
            return "#f87171"   # red
        return "#94a3b8"       # slate
    if t == "module":
        return "#c084fc"       # purple
    if t == "branch":
        return "#22d3ee"       # cyan
    if t == "wt_change":
        return "#fb923c"       # orange
    return "#64748b"


def _node_size(node):
    t = node["type"]
    if t == "author":
        return 30 + min(node.get("commit_count", 1) * 5, 20)
    if t == "commit":
        return 10 + min(node.get("file_count", 1) * 2, 30)
    if t == "file":
        return 8 + min(node.get("touch_count", 1) * 4, 20)
    if t == "module":
        return 20 + min(node.get("file_count", 1) * 2, 20)
    if t == "branch":
        return 25
    if t == "wt_change":
        return 40
    return 15


def _node_shape(node):
    return {
        "author": "dot",
        "commit": "diamond",
        "file": "dot",
        "module": "square",
        "branch": "triangle",
        "wt_change": "star",
    }.get(node["type"], "dot")


def _edge_color(edge):
    t = edge["type"]
    return {
        "authored": "#60a5fa",
        "touched": "#94a3b8",
        "contains": "#6b7280",
        "coupled": "#f59e0b",
        "branched": "#22d3ee",
        "uncommitted": "#fb923c",
    }.get(t, "#64748b")


def _smell_icon(smell_type):
    return {
        "giant_initial_commit": "DUMP",
        "wip_commit": "???",
        "branch_divergence": "FORK",
        "unmerged_branch": "DRIFT",
        "uncommitted_sprawl": "CHAOS",
        "readme_nuke": "NUKE",
        "no_granularity": "BLOB",
        "bus_factor": "BUS",
        "contested_file": "CLASH",
        "orphaned_files": "GHOST",
    }.get(smell_type, "SMELL")


def _severity_color(severity):
    return {"high": "#ef4444", "medium": "#f59e0b", "low": "#94a3b8"}.get(severity, "#64748b")


def render_html(graph, output_path):
    """Render the development knowledge graph as interactive HTML."""
    vis_nodes = []
    for n in graph["nodes"]:
        tooltip_data = {k: v for k, v in n.items() if k not in ("id",)}
        vis_nodes.append({
            "id": n["id"],
            "label": n["label"],
            "color": _node_color(n),
            "size": _node_size(n),
            "shape": _node_shape(n),
            "font": {"color": "#e2e8f0", "size": 12},
            "title": json.dumps(tooltip_data, indent=2),
        })

    vis_edges = []
    for e in graph["edges"]:
        vis_edges.append({
            "from": e["source"],
            "to": e["target"],
            "label": e.get("label", ""),
            "color": {"color": _edge_color(e), "opacity": 0.7},
            "width": min(1 + (e.get("weight", 1) / 50), 6),
            "arrows": "to" if e["type"] != "coupled" else "",
            "font": {"color": "#64748b", "size": 9, "strokeWidth": 0},
            "title": e.get("type", ""),
            "dashes": e["type"] in ("contains", "uncommitted"),
            "smooth": {"type": "curvedCW", "roundness": 0.2} if e["type"] == "coupled" else True,
        })

    a = graph["analysis"]

    # Build smells HTML
    smells_html = ""
    if a["smells"]:
        smells_html = '<h2>Process Smells</h2><div class="grid">'
        for s in sorted(a["smells"], key=lambda x: {"high": 0, "medium": 1, "low": 2}[x["severity"]]):
            sev_class = {"high": "critical", "medium": "warning", "low": "info"}[s["severity"]]
            icon = _smell_icon(s["type"])
            smells_html += f'''<div class="card {sev_class}">
  <div class="smell-header"><span class="smell-icon">[{icon}]</span> <span class="smell-severity" style="color:{_severity_color(s['severity'])}">{s['severity'].upper()}</span></div>
  <div class="smell-msg">{s['message']}</div>
</div>'''
        smells_html += "</div>"

    # Timeline HTML
    timeline_html = '<h2>Timeline</h2><div class="timeline">'
    for t in a["timeline"]:
        sc_class = {"massive": "critical", "large": "warning", "normal": "info"}[t["size_class"]]
        timeline_html += f'''<div class="card {sc_class} timeline-item">
  <div class="chain"><code>{t['hash'][:7]}</code> {t['message']}</div>
  <div class="meta">{t['author']} -{t['date']} -{t['files']} files, {t['lines']} lines -[{t['size_class'].upper()}]</div>
</div>'''
    timeline_html += "</div>"

    # Hotspots HTML
    hotspots_html = ""
    if a["hotspots"]:
        hotspots_html = '<h2>Churn Hotspots (files touched across multiple commits)</h2><div class="grid">'
        for h in a["hotspots"]:
            hotspots_html += f'''<div class="card warning">
  <div class="chain">{h['path']}</div>
  <div class="meta">{h['touches']} commits, {h['churn']} lines churned</div>
</div>'''
        hotspots_html += "</div>"

    # Coupling HTML
    coupling_html = ""
    if a["coupling"]:
        coupling_html = '<h2>File Coupling (always changed together)</h2>'
        for c in a["coupling"]:
            coupling_html += f'''<div class="matrix-row">
  <span class="matrix-label">{Path(c['file_a']).name} + {Path(c['file_b']).name}</span>
  <span class="matrix-bar" style="width:{c['count'] * 60}px"></span>
  <span>{c['count']}x</span>
</div>'''

    # Stats
    total_commits = len(a["timeline"])
    total_smells = len(a["smells"])
    high_smells = len([s for s in a["smells"] if s["severity"] == "high"])
    big_bangs = len(a["big_bangs"])
    authors = set(n["label"] for n in graph["nodes"] if n["type"] == "author")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>MARS Dev Process -Knowledge Graph</title>
<script src="https://unpkg.com/vis-network@9.1.6/standalone/umd/vis-network.min.js"></script>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ background: #0f172a; color: #e2e8f0; font-family: 'SF Mono', 'Fira Code', 'Cascadia Code', monospace; }}
  #graph {{ width: 100vw; height: 55vh; border-bottom: 1px solid #334155; }}
  #analysis {{ padding: 24px; max-width: 1200px; margin: 0 auto; overflow-y: auto; max-height: 45vh; }}
  h1 {{ font-size: 1.5rem; margin-bottom: 4px; color: #f8fafc; }}
  .subtitle {{ color: #64748b; font-size: 0.85rem; margin-bottom: 16px; }}
  h2 {{ font-size: 1rem; margin: 20px 0 10px; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.1em; }}
  .card {{ background: #1e293b; border-radius: 8px; padding: 14px; margin-bottom: 10px; border-left: 3px solid #334155; }}
  .card.critical {{ border-left-color: #ef4444; }}
  .card.warning {{ border-left-color: #f59e0b; }}
  .card.info {{ border-left-color: #3b82f6; }}
  .chain {{ font-size: 1rem; }}
  .meta {{ color: #64748b; font-size: 0.8rem; margin-top: 3px; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 10px; }}
  .legend {{ display: flex; gap: 14px; flex-wrap: wrap; margin-bottom: 16px; }}
  .legend-item {{ display: flex; align-items: center; gap: 5px; font-size: 0.8rem; }}
  .dot {{ width: 10px; height: 10px; border-radius: 50%; display: inline-block; }}
  .diamond {{ width: 10px; height: 10px; transform: rotate(45deg); display: inline-block; }}
  .stats {{ display: flex; gap: 28px; flex-wrap: wrap; margin-bottom: 16px; }}
  .stat {{ text-align: center; }}
  .stat-value {{ font-size: 2rem; font-weight: bold; }}
  .stat-value.bad {{ color: #ef4444; }}
  .stat-label {{ font-size: 0.7rem; color: #64748b; text-transform: uppercase; }}
  .smell-header {{ display: flex; gap: 8px; align-items: center; margin-bottom: 4px; }}
  .smell-icon {{ color: #f8fafc; font-weight: bold; font-size: 0.85rem; }}
  .smell-severity {{ font-size: 0.75rem; font-weight: bold; }}
  .smell-msg {{ font-size: 0.9rem; line-height: 1.4; }}
  .matrix-row {{ display: flex; gap: 8px; font-size: 0.85rem; padding: 3px 0; align-items: center; }}
  .matrix-label {{ min-width: 240px; color: #94a3b8; }}
  .matrix-bar {{ background: #f59e0b; height: 16px; border-radius: 3px; min-width: 2px; }}
  .timeline {{ max-height: 300px; overflow-y: auto; }}
  .timeline-item {{ padding: 10px 14px; }}
  code {{ background: #334155; padding: 2px 6px; border-radius: 4px; font-size: 0.85rem; }}
</style>
</head>
<body>

<div id="graph"></div>
<div id="analysis">
  <h1>Where the Process Went Wrong</h1>
  <div class="subtitle">Knowledge graph of the MARS development log -{total_commits} commits analyzed</div>

  <div class="legend">
    <div class="legend-item"><span class="dot" style="background:#60a5fa"></span> Author</div>
    <div class="legend-item"><span class="diamond" style="background:#34d399"></span> Commit (normal)</div>
    <div class="legend-item"><span class="diamond" style="background:#f59e0b"></span> Commit (large)</div>
    <div class="legend-item"><span class="diamond" style="background:#ef4444"></span> Commit (massive)</div>
    <div class="legend-item"><span class="dot" style="background:#94a3b8"></span> File</div>
    <div class="legend-item"><span class="dot" style="background:#f87171"></span> Hotspot file</div>
    <div class="legend-item"><span class="dot" style="background:#c084fc"></span> Module</div>
    <div class="legend-item"><span class="dot" style="background:#22d3ee"></span> Branch</div>
    <div class="legend-item"><span class="dot" style="background:#fb923c"></span> Uncommitted</div>
  </div>

  <div class="stats">
    <div class="stat">
      <div class="stat-value">{total_commits}</div>
      <div class="stat-label">Commits</div>
    </div>
    <div class="stat">
      <div class="stat-value{' bad' if total_smells > 3 else ''}">{total_smells}</div>
      <div class="stat-label">Smells</div>
    </div>
    <div class="stat">
      <div class="stat-value{' bad' if high_smells > 0 else ''}">{high_smells}</div>
      <div class="stat-label">High Severity</div>
    </div>
    <div class="stat">
      <div class="stat-value{' bad' if big_bangs > 0 else ''}">{big_bangs}</div>
      <div class="stat-label">Big Bangs</div>
    </div>
    <div class="stat">
      <div class="stat-value">{len(authors)}</div>
      <div class="stat-label">Authors</div>
    </div>
  </div>

  {smells_html}
  {timeline_html}
  {hotspots_html}
  {coupling_html}
</div>

<script>
var nodes = new vis.DataSet({json.dumps(vis_nodes)});
var edges = new vis.DataSet({json.dumps(vis_edges)});

var container = document.getElementById("graph");
var data = {{ nodes: nodes, edges: edges }};
var options = {{
  physics: {{
    solver: "forceAtlas2Based",
    forceAtlas2Based: {{
      gravitationalConstant: -120,
      centralGravity: 0.008,
      springLength: 150,
      springConstant: 0.03,
      damping: 0.6,
    }},
    stabilization: {{ iterations: 300 }},
  }},
  interaction: {{
    hover: true,
    tooltipDelay: 100,
    navigationButtons: true,
    zoomView: true,
  }},
  edges: {{
    smooth: {{ type: "continuous" }},
  }},
  layout: {{
    improvedLayout: true,
  }},
}};

var network = new vis.Network(container, data, options);

// Highlight connected nodes on click
network.on("click", function(params) {{
  if (params.nodes.length > 0) {{
    var nodeId = params.nodes[0];
    var connected = network.getConnectedNodes(nodeId);
    connected.push(nodeId);
    nodes.forEach(function(n) {{
      if (connected.indexOf(n.id) === -1) {{
        nodes.update({{id: n.id, opacity: 0.15}});
      }} else {{
        nodes.update({{id: n.id, opacity: 1.0}});
      }}
    }});
  }} else {{
    nodes.forEach(function(n) {{
      nodes.update({{id: n.id, opacity: 1.0}});
    }});
  }}
}});
</script>
</body>
</html>"""

    Path(output_path).write_text(html, encoding="utf-8")
    return output_path


# ═══════════════════════════════════════════════════════════════════════
#  CLI
# ═══════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Build a knowledge graph from git development logs")
    parser.add_argument("--repo", default=".", help="Path to git repo (default: current dir)")
    parser.add_argument("--out", default="dev_knowledge_graph.html", help="Output HTML file")
    parser.add_argument("--json", default=None, help="Also dump graph as JSON")
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    print(f"Analyzing git history in {repo}...")

    commits = extract_commits(repo)
    branches = extract_branches(repo)
    working_tree = extract_working_tree(repo)
    divergence = extract_branch_divergence(repo)

    print(f"  commits:      {len(commits)}")
    print(f"  branches:     {len(branches)}")
    print(f"  uncommitted:  {len(working_tree)} changes")
    print(f"  divergence:   {divergence['ahead']} ahead, {divergence['behind']} behind main")

    print("\nBuilding knowledge graph...")
    graph = build_graph(commits, branches, working_tree, divergence)

    print(f"  nodes: {len(graph['nodes'])}")
    print(f"  edges: {len(graph['edges'])}")

    a = graph["analysis"]
    if a["smells"]:
        print(f"\n  PROCESS SMELLS ({len(a['smells'])}):")
        for s in sorted(a["smells"], key=lambda x: {"high": 0, "medium": 1, "low": 2}[x["severity"]]):
            icon = _smell_icon(s["type"])
            print(f"    [{icon}] {s['severity'].upper()}: {s['message']}")

    if a["big_bangs"]:
        print(f"\n  BIG BANG COMMITS ({len(a['big_bangs'])}):")
        for bb in a["big_bangs"]:
            print(f"    {bb['hash'][:7]} ({bb['author']}): {bb['files']} files, {bb['lines']} lines -\"{bb['message']}\"")

    if a["hotspots"]:
        print(f"\n  CHURN HOTSPOTS:")
        for h in a["hotspots"]:
            print(f"    {h['path']}: {h['touches']} commits, {h['churn']} lines")

    out_path = render_html(graph, args.out)
    print(f"\nGraph -> {out_path}")
    print("Open in browser to explore.")

    if args.json:
        Path(args.json).write_text(json.dumps(graph, indent=2, default=str), encoding="utf-8")
        print(f"JSON -> {args.json}")


if __name__ == "__main__":
    main()
