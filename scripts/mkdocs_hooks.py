"""Хуки MkDocs: страницы справочника, которые строятся из кода, и журнал изменений.

Маркеры в markdown заменяются сгенерированным текстом:
    <!-- amxpy:events -->       каталог событий из amxpy.events
    <!-- amxpy:diagnostics -->  коды amxpyc из amxpy/compiler
    <!-- amxpy:cli -->          команды amxpy из amxpy.cli.build_parser()
    <!-- amxpy:changelog -->    релизы из docs/releases.yml

Релизы попадают и в config.extra.releases — из них главная строит чип новостей
и карточку «Что нового».
"""

from __future__ import annotations

import argparse
import ast
import datetime as dt
import html
import inspect
import re
from pathlib import Path
from typing import Any

import markdown
import yaml
from markupsafe import Markup

ROOT = Path(__file__).resolve().parent.parent
MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"]
SHORT_MONTHS = ["янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]
KINDS = {"new": "Новое", "improved": "Улучшено", "fixed": "Исправлено"}


# --- релизы ---
def _releases() -> list[dict[str, Any]]:
    data = yaml.safe_load((ROOT / "docs" / "releases.yml").read_text(encoding="utf-8"))
    for release in data:
        release["date_text"] = _date(release["date"])
        for change in release["changes"]:
            change["kind_text"] = KINDS[change.get("kind", "new")]
            change["short_date"] = _short(change["date"]) if change.get("date") else ""
    return data


def _date(d: dt.date) -> str:
    return f"{d.day} {MONTHS[d.month - 1]} {d.year}"


def _short(d: dt.date) -> str:
    return f"{d.day} {SHORT_MONTHS[d.month - 1]}"


def _changelog(releases: list[dict[str, Any]]) -> str:
    out = []
    for r in releases:
        out.append(f"## v{r['version']} — {r['title']} {{ #v{r['version'].replace('.', '-')} }}\n")
        out.append(f'<p class="ax-rel-meta">{r["date_text"]}</p>\n\n{r["summary"]}\n')
        for c in r["changes"]:
            when = f' <span class="ax-when">{c["short_date"]}</span>' if c["short_date"] else ""
            more = f" [Подробнее →]({c['link']})" if c.get("link") else ""
            out.append(
                f'<div class="ax-change" markdown>\n<span class="ax-kind ax-kind--{c.get("kind", "new")}">{c["kind_text"]}</span>{when}\n\n'
                f'**{c["title"]}**\n\n{c["text"]}{more}\n\n</div>\n'
            )
    return "\n".join(out)


# --- события ---
TYPES = {
    "str": "str", "player": "Player", "player?": "Player | None", "entity": "Player | Entity | None",
    "float": "float", "int": "int", "bool": "bool", "winner": "Winner", "money_reason": "MoneyReason",
}  # fmt: skip
EVENT_GROUPS = [
    ("Плагин и карта", ["Init", "MapStart", "MapEnd", "Unload", "Frame"]),
    ("Подключение и чат", ["Connect", "PutInServer", "Authorized", "Disconnected", "Say", "NameChange"]),
    ("Игрок в игре", ["PlayerSpawn", "TakeDamage", "PlayerKilled", "TeamSelect", "MoneyChange", "BuyWeapon", "DropItem"]),
    ("Раунд", ["RoundStart", "FreezeEnd", "RoundEnd"]),
    ("Бомба и гранаты", ["GrenadeThrow", "BombPlanted", "BombDefuseStart", "BombDefuseEnd", "BombExploded"]),
]
FIELD_LINE = re.compile(r"^- `(\w+): [^`]+` — (.+)$")


def _split_doc(doc: str) -> tuple[str, dict[str, str], str]:
    """Описание, поля из «#### Поля» и блок «#### Пример» докстринга события."""
    parts = re.split(r"^#### (.+)$", doc, flags=re.M)
    intro, sections = parts[0].strip(), dict(zip(parts[1::2], (p.strip() for p in parts[2::2])))
    fields = {}
    for line in sections.get("Поля", "").splitlines():
        if m := FIELD_LINE.match(line.strip()):
            fields[m[1]] = m[2]
    return intro, fields, sections.get("Пример", "")


def _event(cls: type) -> str:
    doc = inspect.getdoc(cls) or ""
    intro, described, example = _split_doc(doc)
    intro = re.sub(r"\s*\((?:pre и post, )?нужен ReGameDLL[^)]*\)", "", intro, count=1)
    phases = ["pre" if not p else "post" for p in cls.phases]
    badges = [f'<span class="ax-badge ax-badge--{p}">{p}</span>' for p in phases]
    if m := re.search(r"нужен ReGameDLL(?: (\d\.\d)\+)?", doc):
        badges.append(f'<span class="ax-badge ax-badge--re">ReGameDLL{" " + m[1] + "+" if m[1] else ""}</span>')
    if cls.cancellable:
        badges.append('<span class="ax-badge ax-badge--cancel">cancel()</span>')
    if cls.has_result:
        badges.append('<span class="ax-badge ax-badge--result">result</span>')
    out = [f"### {cls.__name__}\n", f'<div class="ax-badges">{"".join(badges)}</div>\n', intro + "\n"]
    fields = cls.fields()
    if fields:
        out.append("| Поле | Тип | Описание |\n|---|---|---|")
        for name, f in fields.items():
            text = described.get(name) or f.doc or ""
            if f.mutable:
                text += ' <span class="ax-mut">меняется в pre</span>'
            out.append(f"| `{name}` | `{TYPES.get(f.kind, f.kind)}` | {text} |")
        out.append("")
    if example:
        out.append(example + "\n")
    return "\n".join(out)


def _events() -> str:
    from amxpy import events

    out = []
    listed = {n for _, names in EVENT_GROUPS for n in names}
    every = {n for n, c in vars(events).items() if inspect.isclass(c) and issubclass(c, events.Event) and c is not events.Event}
    if every != listed:
        raise RuntimeError(f"каталог событий не совпадает с amxpy.events: {sorted(every ^ listed)}")
    for title, names in EVENT_GROUPS:
        out.append(f"## {title}\n")
        out.extend(_event(getattr(events, n)) for n in names)
    return "\n".join(out)


# --- диагностики ---
DIAG_GROUPS = [
    ("0", "Плагин и его метаданные"),
    ("1", "События"),
    ("2", "Нативы и форварды"),
    ("3", "Импорт модуля"),
    ("4", "Команды и cvar'ы"),
]


def _message(node: ast.AST, assigned: dict[str, ast.AST]) -> str:
    if isinstance(node, ast.Name) and node.id in assigned:  # message = f"..."; report(..., message)
        return _message(assigned[node.id], {})
    if isinstance(node, ast.Constant):
        return str(node.value)
    if isinstance(node, ast.JoinedStr):
        return "".join(v.value if isinstance(v, ast.Constant) else "…" for v in node.values)
    return "…"


def _diagnostics() -> str:
    from amxpy.compiler.diagnostics import WARNING_CODES

    found: dict[str, list[str]] = {}
    for file in ["analyzer.py", "build.py"]:
        tree = ast.parse((ROOT / "amxpy" / "compiler" / file).read_text(encoding="utf-8"))
        assigned = {
            t.id: n.value for n in ast.walk(tree) if isinstance(n, ast.Assign) for t in n.targets if isinstance(t, ast.Name)
        }
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            args = node.args
            # Diagnostic(код, уровень, файл, строка, колонка, сообщение) или report(..., код, сообщение)
            direct = isinstance(node.func, ast.Name) and node.func.id == "Diagnostic"
            for i, arg in enumerate(args[:-1]):
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and re.fullmatch(r"AMX\d{3}", arg.value):
                    text = args[i + 5] if direct and len(args) > i + 5 else args[i + 1]
                    msg = re.sub(r"……$", "…", _message(text, assigned))
                    msgs = found.setdefault(arg.value, [])
                    if msg not in msgs:
                        msgs.append(msg)
    out = []
    for digit, title in DIAG_GROUPS:
        codes = sorted(c for c in found if c[3] == digit)
        if not codes:
            continue
        out.append(f"## {title}\n\n| Код | Уровень | Сообщения |\n|---|---|---|")
        for code in codes:
            level = (
                '<span class="ax-badge ax-badge--warn">предупреждение</span>'
                if code in WARNING_CODES
                else '<span class="ax-badge ax-badge--err">ошибка</span>'
            )
            msgs = "<br>".join(re.sub(r"([|_*])", r"\\\1", html.escape(m)) for m in found[code])
            out.append(f'| <span id="{code.lower()}">`{code}`</span> | {level} | {msgs} |')
        out.append("")
    return "\n".join(out)


# --- CLI ---
def _cli() -> str:
    from amxpy.cli import build_parser

    parser = build_parser()
    sub = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    helps = {a.dest: a.help or "" for a in sub._choices_actions}
    out = []
    for name, p in sub.choices.items():
        out.append(f"## amxpy {name}\n\n{helps[name][:1].upper() + helps[name][1:]}.\n\n```text\n{p.format_usage().strip()}\n```\n")
        rows = []
        for a in p._actions:
            if isinstance(a, argparse._HelpAction):
                continue
            flag = ", ".join(a.option_strings) or a.dest
            default = "" if not a.option_strings or a.default in (None, False) else f" По умолчанию: `{a.default}`."
            rows.append(f"| `{flag}` | {html.escape(a.help or '')}{default} |")
        if rows:
            out.append("| Параметр | Описание |\n|---|---|\n" + "\n".join(rows) + "\n")
    return "\n".join(out)


# --- хуки MkDocs ---
GENERATORS = {"events": _events, "diagnostics": _diagnostics, "cli": _cli}
ROLE = re.compile(r":(?:class|meth|func|mod|attr|data|exc):(<code>[^<]+</code>)")


def on_config(config: Any) -> Any:
    config.extra["releases"] = _releases()
    return config


def on_env(env: Any, config: Any, files: Any) -> Any:
    def markdown_inline(text: str) -> Markup:  # `код` и **жирный** в текстах релизов
        rendered = markdown.markdown(str(text))
        return Markup(re.sub(r"^<p>(.*)</p>$", r"\1", rendered, flags=re.S))

    env.filters["markdown_inline"] = markdown_inline
    return env


def on_page_markdown(markdown: str, page: Any, config: Any, files: Any) -> str:
    for name, make in GENERATORS.items():
        marker = f"<!-- amxpy:{name} -->"
        if marker in markdown:
            markdown = markdown.replace(marker, make())
    if "<!-- amxpy:changelog -->" in markdown:
        markdown = markdown.replace("<!-- amxpy:changelog -->", _changelog(config.extra["releases"]))
    return markdown


def on_page_content(html_text: str, page: Any, config: Any, files: Any) -> str:
    return ROLE.sub(r"\1", html_text)  # reST-роли из докстрингов: :class:`X` → `X`
