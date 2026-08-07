#!/usr/bin/env python3
"""
arXiv Daily Paper Fetcher
Fetches latest papers on Agent, RL, and Tool-use from arXiv,
scores by relevance, and generates daily Markdown digests.
"""

import argparse
import datetime
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# Fix Windows GBK encoding issue with emoji output
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import feedparser
import requests
import yaml

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

CONFIG_PATH = Path(__file__).resolve().parent / "config.yaml"
PAPERS_DIR = Path(__file__).resolve().parent / "papers"
README_PATH = Path(__file__).resolve().parent / "README.md"
INDEX_HTML_PATH = Path(__file__).resolve().parent / "index.html"

ARXIV_API = "https://export.arxiv.org/api/query"
MAX_RESULTS_PER_QUERY = 30
REQUEST_DELAY = 3  # seconds between queries (politeness)
TOP_N = 18  # target number of papers in daily digest


@dataclass
class Paper:
    arxiv_id: str
    title: str
    authors: list[str]
    abstract: str
    categories: list[str]
    published: str  # ISO date
    pdf_url: str
    score: int = 0
    score_reasons: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def load_config() -> dict:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


def clean_title(raw: str) -> str:
    return re.sub(r"\s+", " ", raw).strip()


def clean_abstract(raw: str) -> str:
    return re.sub(r"\s+", " ", raw).strip()


def extract_arxiv_id(entry: dict) -> str:
    id_url = entry.get("id", "")
    match = re.search(r"abs/([\w.-]+)", id_url)
    if match:
        raw = match.group(1)
        return re.sub(r"v\d+$", "", raw)
    return id_url


def get_authors(entry: dict) -> list[str]:
    return [a.get("name", "") for a in entry.get("authors", []) if a.get("name")]


def get_categories(entry: dict) -> list[str]:
    tags = entry.get("tags", [])
    return [t.get("term", "") for t in tags if t.get("term")]


def first_sentences(text: str, n: int = 4) -> str:
    sentences = re.split(r"(?<=[.!?])\s+", text)
    return " ".join(sentences[:n])


# ---------------------------------------------------------------------------
# arXiv API
# ---------------------------------------------------------------------------


def build_query(keywords: str, categories: list[str]) -> str:
    # Remove all whitespace/newlines from keywords (YAML multiline strings)
    cleaned_kw = re.sub(r"\s+", "", keywords)
    parts = [f"({cleaned_kw})"]
    if categories:
        cat_part = "+OR+".join(f"cat:{c}" for c in categories)
        parts.append(f"({cat_part})")
    return "+AND+".join(parts)


def fetch_from_arxiv(query_str: str, max_results: int = MAX_RESULTS_PER_QUERY) -> list[dict]:
    url = (
        f"{ARXIV_API}?search_query={query_str}"
        f"&start=0&max_results={max_results}"
        f"&sortBy=submittedDate&sortOrder=descending"
    )
    try:
        resp = requests.get(url, timeout=30, headers={"User-Agent": "arxiv-daily-papers/1.0"})
        if resp.status_code != 200:
            print(f"  [WARN] HTTP {resp.status_code} for query", file=sys.stderr)
            return []
        parsed = feedparser.parse(resp.content)
        if parsed.bozo:
            print(f"  [WARN] Feed parse issue: {parsed.bozo_exception}", file=sys.stderr)
        return parsed.entries
    except Exception as exc:
        print(f"  [ERROR] {exc}", file=sys.stderr)
        return []


# ---------------------------------------------------------------------------
# Scoring & Filtering
# ---------------------------------------------------------------------------


def compute_relevance(paper: Paper, rules: list[dict]) -> Paper:
    title_lower = paper.title.lower()
    abstract_lower = paper.abstract.lower()

    for rule in rules:
        keywords = rule.get("keywords", [])
        weight = rule.get("weight", 1)
        field = rule.get("field", "title")

        text = title_lower if field == "title" else abstract_lower
        effective_weight = weight if field == "title" else max(1, weight // 2)

        for kw in keywords:
            if kw.lower() in text:
                paper.score += effective_weight
                paper.score_reasons.append(f"{field}:{kw}")

    return paper


def hard_filter(paper: Paper, exclude_rules: list[dict]) -> bool:
    title_lower = paper.title.lower()
    abstract_lower = paper.abstract.lower()

    for rule in exclude_rules:
        keywords = rule.get("keywords", [])
        field = rule.get("field", "title")
        text = title_lower if field == "title" else abstract_lower

        for kw in keywords:
            if kw.lower() in text:
                return True
    return False


# ---------------------------------------------------------------------------
# Markdown generation
# ---------------------------------------------------------------------------


def generate_daily_md(papers: list[Paper], date_str: str) -> str:
    highlights = [p for p in papers if p.score >= 5]
    papers_sorted = sorted(papers, key=lambda p: p.score, reverse=True)

    lines = [
        f"# 📄 arXiv Papers — {date_str}",
        "",
        f"**Agent / RL / Tool-use** | 共 {len(papers)} 篇 | 更新时间: {date_str}",
        "",
        "---",
        "",
    ]

    # Highlights table
    if highlights:
        lines.append("## ⭐ Highlights（推荐阅读）")
        lines.append("")
        lines.append("| # | Score | Title |")
        lines.append("|---|-------|-------|")
        for i, p in enumerate(highlights, 1):
            title_escaped = p.title.replace("|", "\\|")
            lines.append(f"| {i} | {p.score} | [{title_escaped}]({p.pdf_url}) |")
        lines.append("")
        lines.append("---")
        lines.append("")

    # All papers table
    lines.append("## 📋 All Papers")
    lines.append("")
    lines.append("| # | Score | Title | Authors | Categories |")
    lines.append("|---|-------|-------|---------|------------|")
    for i, p in enumerate(papers_sorted, 1):
        title_escaped = p.title.replace("|", "\\|")
        authors_short = p.authors[0].split()[-1] if p.authors else "Unknown"
        if len(p.authors) > 1:
            authors_short += " et al."
        cats = ", ".join(p.categories[:3])
        lines.append(f"| {i} | {p.score} | [{title_escaped}]({p.pdf_url}) | {authors_short} | {cats} |")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Detailed entries
    lines.append("## 📖 Detailed Entries")
    lines.append("")
    for i, p in enumerate(papers_sorted, 1):
        lines.append(f"### {i}. {p.title}")
        lines.append("")
        lines.append(f"- **arXiv ID**: [{p.arxiv_id}]({p.pdf_url})")
        lines.append(f"- **Authors**: {', '.join(p.authors[:8])}")
        if len(p.authors) > 8:
            lines.append(f"  *(and {len(p.authors) - 8} more)*")
        lines.append(f"- **Categories**: {', '.join(p.categories)}")
        lines.append(f"- **Published**: {p.published}")
        if p.score_reasons:
            lines.append(f"- **Relevance**: {', '.join(p.score_reasons[:6])}")
        lines.append(f"- **Abstract**: {first_sentences(p.abstract, 5)}")
        lines.append("")

    return "\n".join(lines)


def update_readme_index(papers_dir: Path, today_str: str) -> None:
    md_files = sorted(papers_dir.glob("*.md"), reverse=True)

    lines = [
        "# 📄 arXiv Daily Papers — Agent / RL / Tool-use",
        "",
        "每天自动从 arXiv 爬取 Agent、Reinforcement Learning、Tool-use 方向的最新论文，精选 10-20 篇。",
        "",
        "> 🔄 每日 UTC 22:00 自动更新（北京时间次日 06:00）",
        "",
        f"**最新**: [{today_str}](papers/{today_str}.md)",
        "",
        "## 📅 论文日报索引",
        "",
        "| 日期 | 论文数 |",
        "|------|--------|",
    ]

    for md_file in md_files:
        date_str = md_file.stem
        content = md_file.read_text(encoding="utf-8")
        count = len(re.findall(r"^### \d+\.", content, re.MULTILINE))
        lines.append(f"| [{date_str}](papers/{date_str}.md) | {count} |")

    lines.append("")
    lines.append("## 🔍 搜索范围")
    lines.append("")
    lines.append("| 主题 | 关键词 |")
    lines.append("|------|--------|")
    lines.append('| **Agent** | "reinforcement learning" + agent, "LLM agent", "AI agent", "autonomous agent" |')
    lines.append('| **Tool-use** | "tool use", "tool-use", "tool calling", "function calling" |')
    lines.append('| **Reasoning** | "reasoning" + agent, "planning" + agent |')

    with open(README_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="arXiv Daily Paper Fetcher")
    parser.add_argument("--date", default=datetime.date.today().isoformat(), help="Target date YYYY-MM-DD")
    parser.add_argument("--days", type=int, default=1, help="Days back to search (default: 1)")
    parser.add_argument("--top", type=int, default=TOP_N, help=f"Target papers count (default: {TOP_N})")
    args = parser.parse_args()

    config = load_config()
    queries = config.get("queries", [])
    score_rules = config.get("score_rules", [])
    exclude_rules = config.get("exclude_rules", [])

    if not queries:
        print("[ERROR] No queries defined in config.yaml", file=sys.stderr)
        sys.exit(1)

    target_date = args.date
    print(f"[*] Fetching papers for {target_date} (last {args.days} day(s))...")
    print(f"   {len(queries)} query groups configured\n")

    # --- Phase 1: Fetch ---
    all_entries: dict[str, dict] = {}

    for qgroup in queries:
        keywords = qgroup.get("keywords", "")
        categories = qgroup.get("categories", [])
        label = qgroup.get("label", keywords[:50])

        query_str = build_query(keywords, categories)
        print(f"  [>>] {label} ...", end=" ", flush=True)
        entries = fetch_from_arxiv(query_str, MAX_RESULTS_PER_QUERY)
        print(f"{len(entries)} results")

        for e in entries:
            aid = extract_arxiv_id(e)
            if aid and aid not in all_entries:
                all_entries[aid] = e

        time.sleep(REQUEST_DELAY)

    print(f"\n  [i] Total unique before date filter: {len(all_entries)}")

    # --- Phase 2: Parse & filter by date ---
    papers: list[Paper] = []
    for aid, e in all_entries.items():
        pub = e.get("published", "")
        pub_date = pub[:10]

        if args.days == 1 and pub_date != target_date:
            continue
        elif args.days > 1:
            target_dt = datetime.date.fromisoformat(target_date)
            pub_dt = datetime.date.fromisoformat(pub_date)
            if (target_dt - pub_dt).days >= args.days:
                continue

        paper = Paper(
            arxiv_id=aid,
            title=clean_title(e.get("title", "")),
            authors=get_authors(e),
            abstract=clean_abstract(e.get("summary", "")),
            categories=get_categories(e),
            published=pub_date,
            pdf_url=e.get("link", f"https://arxiv.org/abs/{aid}"),
        )
        papers.append(paper)

    print(f"  [i] After date filter: {len(papers)} papers")

    # --- Phase 3: Hard filter + Score ---
    filtered: list[Paper] = []
    for p in papers:
        if hard_filter(p, exclude_rules):
            continue
        p = compute_relevance(p, score_rules)
        filtered.append(p)

    print(f"  [X] After hard filter: {len(filtered)} papers")

    # --- Phase 4: Rank & select ---
    ranked = sorted(filtered, key=lambda p: p.score, reverse=True)
    selected = ranked[: args.top]

    print(f"\n  [OK] Top {len(selected)} papers:")
    for i, p in enumerate(selected, 1):
        reasons = "; ".join(p.score_reasons[:3])
        print(f"      {i:2d}. [score={p.score}] {p.title[:80]}...  ({reasons})")

    # --- Phase 5: Generate Markdown ---
    PAPERS_DIR.mkdir(parents=True, exist_ok=True)
    md_content = generate_daily_md(selected, target_date)
    md_path = PAPERS_DIR / f"{target_date}.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_content)
    print(f"\n[SAVED] {md_path}")

    # --- Phase 6: Update README ---
    update_readme_index(PAPERS_DIR, target_date)
    print(f"[SAVED] README: {README_PATH}")


if __name__ == "__main__":
    main()
