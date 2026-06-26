"""Wiki — Markdown files on disk with YAML-ish frontmatter.

Directory layout:
  ~/.cobaltax/wiki/
    _categories.json          [{slug, name, description, order}]
    <category-slug>/
      <article-slug>.md       --- frontmatter --- + markdown body
"""
from __future__ import annotations

import json
import pathlib
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

_WIKI_DIR  = pathlib.Path.home() / ".cobaltax" / "wiki"
_CATS_FILE = _WIKI_DIR / "_categories.json"

_FM_SEP = "---"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _slugify(text: str) -> str:
    s = text.lower().strip()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s_-]+", "-", s)
    return s[:60].strip("-") or "article"


def _unique_slug(directory: pathlib.Path, base: str) -> str:
    slug = _slugify(base)
    candidate = slug
    i = 2
    while (directory / f"{candidate}.md").exists():
        candidate = f"{slug}-{i}"
        i += 1
    return candidate


def init_wiki() -> None:
    _WIKI_DIR.mkdir(parents=True, exist_ok=True)
    if not _CATS_FILE.exists():
        _CATS_FILE.write_text("[]", encoding="utf-8")


# ── Categories ────────────────────────────────────────────

def _load_cats() -> List[Dict]:
    try:
        return json.loads(_CATS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_cats(cats: List[Dict]) -> None:
    _CATS_FILE.write_text(json.dumps(cats, ensure_ascii=False, indent=2), encoding="utf-8")


def list_categories() -> List[Dict]:
    return sorted(_load_cats(), key=lambda c: c.get("order", 99))


def get_category(slug: str) -> Optional[Dict]:
    return next((c for c in _load_cats() if c["slug"] == slug), None)


def save_category(slug: str, name: str, description: str = "", order: int = 99) -> Dict:
    cats = _load_cats()
    existing = next((c for c in cats if c["slug"] == slug), None)
    if existing:
        existing.update({"name": name, "description": description, "order": order})
    else:
        cats.append({"slug": slug, "name": name, "description": description, "order": order})
        (_WIKI_DIR / slug).mkdir(exist_ok=True)
    _save_cats(cats)
    return get_category(slug)


def create_category(name: str, description: str = "") -> Dict:
    slug = _slugify(name)
    # avoid collision
    existing_slugs = {c["slug"] for c in _load_cats()}
    base = slug
    i = 2
    while slug in existing_slugs:
        slug = f"{base}-{i}"; i += 1
    max_order = max((c.get("order", 0) for c in _load_cats()), default=0)
    return save_category(slug, name, description, max_order + 1)


def delete_category(slug: str) -> bool:
    cats = _load_cats()
    before = len(cats)
    cats = [c for c in cats if c["slug"] != slug]
    if len(cats) == before:
        return False
    _save_cats(cats)
    cat_dir = _WIKI_DIR / slug
    if cat_dir.exists():
        import shutil
        shutil.rmtree(cat_dir)
    return True


# ── Articles ──────────────────────────────────────────────

def _parse_article(path: pathlib.Path) -> Dict:
    raw = path.read_text(encoding="utf-8")
    meta: Dict[str, Any] = {}
    body = raw
    if raw.startswith(_FM_SEP):
        parts = raw.split(_FM_SEP, 2)
        if len(parts) >= 3:
            for line in parts[1].splitlines():
                if ":" in line:
                    k, _, v = line.partition(":")
                    k = k.strip(); v = v.strip()
                    if k == "tags":
                        meta["tags"] = [t.strip() for t in v.strip("[]").split(",") if t.strip()]
                    else:
                        meta[k] = v
            body = parts[2].lstrip("\n")
    return {
        "slug":       path.stem,
        "title":      meta.get("title", path.stem),
        "author":     meta.get("author", ""),
        "created_at": meta.get("created_at", ""),
        "updated_at": meta.get("updated_at", ""),
        "tags":       meta.get("tags", []),
        "content":    body,
    }


def _write_article(path: pathlib.Path, title: str, author: str,
                   created_at: str, updated_at: str,
                   tags: List[str], content: str) -> None:
    tags_str = "[" + ", ".join(tags) + "]"
    fm = (
        f"{_FM_SEP}\n"
        f"title: {title}\n"
        f"author: {author}\n"
        f"created_at: {created_at}\n"
        f"updated_at: {updated_at}\n"
        f"tags: {tags_str}\n"
        f"{_FM_SEP}\n\n"
    )
    path.write_text(fm + content, encoding="utf-8")


def list_articles(cat_slug: str) -> List[Dict]:
    cat_dir = _WIKI_DIR / cat_slug
    if not cat_dir.exists():
        return []
    arts = []
    for p in sorted(cat_dir.glob("*.md")):
        a = _parse_article(p)
        a.pop("content")  # omit body for list view
        arts.append(a)
    return sorted(arts, key=lambda a: a.get("updated_at", ""), reverse=True)


def get_article(cat_slug: str, art_slug: str) -> Optional[Dict]:
    path = _WIKI_DIR / cat_slug / f"{art_slug}.md"
    if not path.exists():
        return None
    art = _parse_article(path)
    art["cat_slug"] = cat_slug
    return art


def create_article(cat_slug: str, title: str, content: str,
                   author: str, tags: List[str]) -> Dict:
    cat_dir = _WIKI_DIR / cat_slug
    cat_dir.mkdir(exist_ok=True)
    slug = _unique_slug(cat_dir, title)
    now = _now()
    path = cat_dir / f"{slug}.md"
    _write_article(path, title, author, now, now, tags, content)
    return get_article(cat_slug, slug)


def update_article(cat_slug: str, art_slug: str, title: str,
                   content: str, author: str, tags: List[str]) -> Optional[Dict]:
    path = _WIKI_DIR / cat_slug / f"{art_slug}.md"
    if not path.exists():
        return None
    existing = _parse_article(path)
    _write_article(
        path, title, author,
        existing.get("created_at", _now()), _now(),
        tags, content,
    )
    return get_article(cat_slug, art_slug)


def delete_article(cat_slug: str, art_slug: str) -> bool:
    path = _WIKI_DIR / cat_slug / f"{art_slug}.md"
    if not path.exists():
        return False
    path.unlink()
    return True


def search_articles(query: str) -> List[Dict]:
    q = query.lower()
    results = []
    for cat in list_categories():
        cat_dir = _WIKI_DIR / cat["slug"]
        if not cat_dir.exists():
            continue
        for p in cat_dir.glob("*.md"):
            art = _parse_article(p)
            haystack = (art["title"] + " " + " ".join(art["tags"]) + " " + art["content"]).lower()
            if q in haystack:
                idx = art["content"].lower().find(q)
                excerpt = art["content"][max(0, idx - 60): idx + 120].replace("\n", " ")
                results.append({
                    "cat_slug":   cat["slug"],
                    "cat_name":   cat["name"],
                    "slug":       art["slug"],
                    "title":      art["title"],
                    "excerpt":    excerpt,
                    "updated_at": art["updated_at"],
                })
    return results


def export_all() -> List[Dict]:
    """Return all articles as a flat list — useful for LLM ingestion."""
    out = []
    for cat in list_categories():
        cat_dir = _WIKI_DIR / cat["slug"]
        if not cat_dir.exists():
            continue
        for p in cat_dir.glob("*.md"):
            art = _parse_article(p)
            out.append({
                "category":    cat["name"],
                "cat_slug":    cat["slug"],
                "slug":        art["slug"],
                "title":       art["title"],
                "tags":        art["tags"],
                "content":     art["content"],
                "updated_at":  art["updated_at"],
            })
    return out
