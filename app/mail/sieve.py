"""ManageSieve for Filtre (05) and Mimo kancelárie (06).

Roundcube-compatible scripts use ``# rule:[Name]`` markers (ManageSieve plugin).
Filters and vacation live in the **same active script** — never activate another set.
What we cannot edit stays as raw Sieve and is shown read-only in the UI.
"""

from __future__ import annotations

import re
import socket
import uuid
from dataclasses import dataclass, field
from typing import Any

from sievelib import commands
from sievelib.managesieve import Client as ManageSieveClient
from sievelib.parser import Parser

from app.core.config import Settings
from app.mail.models import Mailbox

# Historical Roundcube ManageSieve plugin name; we keep it when it is already active.
DEFAULT_SCRIPT_NAME = "roundcube"
VACATION_RULE_NAME = "Mimo kancelárie"
VACATION_RULE_NAME_EN = "Mimo kancelárie EN"  # legacy multi-rule scripts only
VACATION_RULE_NAME_DE = "Mimo kancelárie DE"  # legacy multi-rule scripts only
VACATION_MARKER = "# smartmail:vacation"
VACATION_MARKER_EN = "# smartmail:vacation:en"  # legacy — merged on load
VACATION_MARKER_DE = "# smartmail:vacation:de"  # legacy — merged on load
# One vacation action, one text: SK then EN then DE (only filled languages). Roundcube shows one rule.
VACATION_BODY_SEPARATOR = "\n\n---\n\n"

_TEST_SIEVE_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "imap-test"})

# Back-compat aliases used by older imports / ADR text
FILTER_SCRIPT = DEFAULT_SCRIPT_NAME
VACATION_SCRIPT = DEFAULT_SCRIPT_NAME

_RULE_SPLIT = re.compile(r"(?m)^(# rule:\[)")
_RULE_NAME = re.compile(r"^# rule:\[([^\]]*)\]\s*\n?", re.M)
_EDITABLE_FIELDS = frozenset({"from", "to", "cc", "subject", "size", "header", "body"})
_EDITABLE_OPS = frozenset({"contains", "notcontains", "is", "isnot", "startswith", "endswith", "gt", "lt"})
_EDITABLE_ACTIONS = frozenset({"fileinto", "redirect", "reject", "discard", "addflag", "seen", "stop", "keep"})


class SieveError(Exception):
    def __init__(self, code: str, detail: str | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.detail = detail


@dataclass
class FilterCondition:
    field: str  # subject|from|to|cc|body|size|header
    op: str  # contains|notcontains|is|isnot|startswith|endswith|gt|lt
    value: str
    header_name: str | None = None  # custom header when field == "header"


class FilterValidationError(Exception):
    """Structured filter validation for API 422 (Slovak message for the UI)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(code)
        self.code = code
        self.message = message


@dataclass
class FilterAction:
    type: str  # fileinto|redirect|reject|discard|addflag|seen|stop|keep
    value: str = ""


@dataclass
class FilterRule:
    id: str
    name: str
    enabled: bool = True
    match: str = "allof"  # allof|anyof|all
    conditions: list[FilterCondition] = field(default_factory=list)
    actions: list[FilterAction] = field(default_factory=list)
    editable: bool = True
    raw: str | None = None
    kind: str = "filter"  # filter | vacation


@dataclass
class VacationSettings:
    enabled: bool = False
    subject: str = "Mimo kancelárie: {predmet}"
    body_sk: str = "Ďakujem za správu. Momentálne som mimo kancelárie."
    body_en: str = "Thank you for your message. I am currently out of office."
    body_de: str = "Danke für Ihre Nachricht. Ich bin derzeit außer Haus."
    days: int = 7
    start: str | None = None  # ISO date-time
    end: str | None = None


@dataclass
class ParsedScript:
    """Structured view of one Roundcube ManageSieve script."""

    preamble: str  # require […] plus any leading comments
    rules: list[FilterRule]
    vacation: VacationSettings
    script_name: str = DEFAULT_SCRIPT_NAME


def sieve_host_allowed(settings: Settings, host: str) -> bool:
    if settings.app_env == "prod" or settings.mail_sync_allow_real_server:
        return True
    return host.lower() in _TEST_SIEVE_HOSTS


def resolve_sieve_endpoint(mailbox: Mailbox, settings: Settings) -> tuple[str, int]:
    host = mailbox.sieve_host or mailbox.imap_host
    port = mailbox.sieve_port or 4190
    return host, port


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _unescape(value: str) -> str:
    return value.replace('\\"', '"').replace("\\\\", "\\")


def _strip_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] == '"':
        return _unescape(value[1:-1])
    return value


def _uncomment_disabled_body(body: str) -> str:
    """Turn Roundcube ``# disabled`` commented rule body back into live Sieve."""
    lines_out: list[str] = []
    for line in body.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("# rule:["):
            lines_out.append(stripped)
            continue
        if stripped.startswith("# disabled"):
            continue
        if stripped.startswith("#"):
            # "# if …" / "#\tfileinto …" — drop one leading # and optional space
            rest = stripped[1:]
            if rest.startswith(" ") or rest.startswith("\t"):
                rest = rest[1:]
            lines_out.append(rest)
        else:
            lines_out.append(line)
    joined = "\n".join(lines_out).strip()
    return joined + ("\n" if joined else "")


def _comment_out_rule_body(live: str) -> str:
    lines = ["# disabled"]
    for line in live.splitlines():
        if not line.strip():
            lines.append("#")
            continue
        lines.append(f"# {line}" if not line.startswith("#") else f"#{line}")
    return "\n".join(lines) + "\n"


def _op_from_tag(tag: str) -> tuple[str, bool]:
    """Map Sieve match-type tag → (op, negated)."""
    tag = tag.lstrip(":")
    negated = False
    if tag.startswith("not"):
        negated = True
        tag = tag[3:]
    mapping = {
        "contains": "contains",
        "is": "is",
        "matches": "startswith",  # refined with value shape below
        "over": "gt",
        "under": "lt",
    }
    return mapping.get(tag, "contains"), negated


def _field_from_header_name(name: str) -> str:
    low = name.strip('"').lower()
    if low == "from":
        return "from"
    if low == "to":
        return "to"
    if low == "cc":
        return "cc"
    if low == "subject":
        return "subject"
    return "header"


def _extract_test(test: commands.Command) -> tuple[str, list[FilterCondition], bool]:
    """Return (match, conditions, fully_editable)."""
    if isinstance(test, commands.TrueCommand):
        return "all", [], True
    if isinstance(test, (commands.AllofCommand, commands.AnyofCommand)):
        match = "allof" if isinstance(test, commands.AllofCommand) else "anyof"
        conditions: list[FilterCondition] = []
        editable = True
        for child in test["tests"]:
            _m, conds, ok = _extract_test(child)
            conditions.extend(conds)
            editable = editable and ok and len(conds) == 1
        return match, conditions, editable and bool(conditions)
    if isinstance(test, commands.NotCommand):
        # not header :contains → notcontains when single child
        inner = test["test"]
        match, conds, ok = _extract_test(inner)
        if len(conds) == 1 and ok:
            c = conds[0]
            flip = {
                "contains": "notcontains",
                "notcontains": "contains",
                "is": "isnot",
                "isnot": "is",
            }
            c.op = flip.get(c.op, c.op)
            return match, [c], True
        return match, conds, False
    if isinstance(test, commands.AddressCommand):
        return _extract_address_or_header(test, address=True)
    if isinstance(test, commands.HeaderCommand):
        return _extract_address_or_header(test, address=False)
    if isinstance(test, commands.SizeCommand):
        args = test.arguments
        size_tag = str(args.get("comparator") or args.get("tag") or ":over")
        limit = args.get("limit") or args.get("number") or 0
        try:
            number = int(limit)
        except (TypeError, ValueError):
            number = 0
        op = "gt" if size_tag == ":over" else "lt"
        kb = max(1, number // 1024) if number >= 1024 else number
        return "allof", [FilterCondition("size", op, str(kb))], True
    if test.name == "body":
        args = test.arguments
        match_type = str(args.get("match-type") or ":contains")
        if match_type == ":regex":
            return "allof", [], False
        keys = _as_str_list(args.get("key-list") or args.get("keys") or args.get("string"))
        if not keys:
            return "allof", [], False
        op, _neg = _op_from_tag(match_type)
        return "allof", [FilterCondition("body", op, keys[0])], True
    # regex / envelope / unknown → not editable as structured form
    return "allof", [], False


def _as_str_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [_strip_quotes(str(x)) for x in value]
    if isinstance(value, str):
        return [_strip_quotes(value)]
    return []


def _extract_address_or_header(test: commands.Command, *, address: bool) -> tuple[str, list[FilterCondition], bool]:
    args = test.arguments
    match_type = str(args.get("match-type") or args.get("match_type") or ":contains")
    if match_type == ":regex":
        return "allof", [], False
    header_list = args.get("header-list") or args.get("header-names") or args.get("headers")
    key_list = args.get("key-list") or args.get("keylist") or args.get("keys")
    headers = _as_str_list(header_list)
    keys = _as_str_list(key_list)
    if not headers or not keys:
        return "allof", [], False
    op, _neg = _op_from_tag(match_type)
    header0 = headers[0]
    if address or header0.lower() in {"from", "to", "cc", "subject"}:
        field = _field_from_header_name(header0)
        header_name = None
    else:
        field = "header"
        header_name = header0
    conditions = [FilterCondition(field, op, k, header_name=header_name) for k in keys]
    if match_type == ":matches" and len(keys) == 1:
        k = keys[0]
        if k.endswith("*") and not k.startswith("*"):
            conditions[0].op = "startswith"
            conditions[0].value = k[:-1]
        elif k.startswith("*") and not k.endswith("*"):
            conditions[0].op = "endswith"
            conditions[0].value = k[1:]
    return "allof", conditions, True


def _extract_actions(if_cmd: commands.Command) -> tuple[list[FilterAction], bool]:
    actions: list[FilterAction] = []
    editable = True
    for child in if_cmd.children:
        name = child.name
        if name == "fileinto":
            mailbox = child.arguments.get("mailbox") or child.arguments.get("filename")
            if isinstance(mailbox, list):
                mailbox = mailbox[0] if mailbox else ""
            actions.append(FilterAction("fileinto", _strip_quotes(str(mailbox or ""))))
        elif name == "redirect":
            addr = child.arguments.get("address") or child.arguments.get("string")
            if isinstance(addr, list):
                addr = addr[0] if addr else ""
            actions.append(FilterAction("redirect", _strip_quotes(str(addr or ""))))
        elif name == "reject":
            reason = child.arguments.get("reason") or child.arguments.get("string") or ""
            if isinstance(reason, list):
                reason = reason[0] if reason else ""
            actions.append(FilterAction("reject", _strip_quotes(str(reason))))
        elif name == "discard":
            actions.append(FilterAction("discard"))
        elif name == "stop":
            actions.append(FilterAction("stop"))
        elif name == "keep":
            actions.append(FilterAction("keep"))
        elif name in {"addflag", "setflag"}:
            flags = child.arguments.get("flag-list") or child.arguments.get("flags") or []
            flag_s = " ".join(_strip_quotes(str(f)) for f in flags) if isinstance(flags, list) else str(flags)
            if "\\Seen" in flag_s or "Seen" in flag_s:
                actions.append(FilterAction("seen"))
            else:
                actions.append(FilterAction("addflag"))
        elif name == "vacation":
            actions.append(FilterAction("vacation", ""))
            editable = False
        else:
            editable = False
    return actions, editable and all(a.type in _EDITABLE_ACTIONS or a.type == "vacation" for a in actions)


def _parse_rule_block(name: str, block: str, *, index: int) -> FilterRule:
    """Parse one ``# rule:[Name]…`` block into a FilterRule (raw preserved)."""
    raw = block if block.endswith("\n") else block + "\n"
    disabled = bool(re.search(r"(?m)^#\s*disabled\b", block)) or (
        "\n# if " in block or block.lstrip().startswith("# if ")
    )
    # Vacation markers (SK default + optional EN/DE language rules in the same script)
    name_s = name.strip()
    is_vacation = (
        VACATION_MARKER in block
        or VACATION_MARKER_EN in block
        or VACATION_MARKER_DE in block
        or name_s in {VACATION_RULE_NAME, VACATION_RULE_NAME_EN, VACATION_RULE_NAME_DE}
        or name_s.startswith(VACATION_RULE_NAME)
    )
    live = _uncomment_disabled_body(block) if disabled else block
    # drop the # rule:[…] line for parsing
    live_body = _RULE_NAME.sub("", live, count=1).strip()
    if is_vacation:
        vac = _vacation_from_sieve_body(live_body)
        rule_name = VACATION_RULE_NAME
        if VACATION_MARKER_EN in block or name_s == VACATION_RULE_NAME_EN:
            rule_name = VACATION_RULE_NAME_EN
        elif VACATION_MARKER_DE in block or name_s == VACATION_RULE_NAME_DE:
            rule_name = VACATION_RULE_NAME_DE
        return FilterRule(
            id=f"vacation-{index}",
            name=rule_name,
            enabled=not disabled and vac.enabled,
            match="all",
            conditions=[],
            actions=[FilterAction("vacation")],
            editable=True,
            raw=raw,
            kind="vacation",
        )

    require = 'require ["fileinto","reject","vacation","imap4flags","regex","body","envelope","date","relational"];'
    mini = f"{require}\n{live_body}\n"
    parser = Parser()
    ok = parser.parse(mini)
    if not ok or not parser.result:
        return FilterRule(
            id=f"rc-{index}-{uuid.uuid4().hex[:6]}",
            name=name,
            enabled=not disabled,
            editable=False,
            raw=raw,
            conditions=[],
            actions=[FilterAction("keep")],
        )

    if_cmd = next((c for c in parser.result if isinstance(c, commands.IfCommand)), None)
    if if_cmd is None:
        return FilterRule(
            id=f"rc-{index}-{uuid.uuid4().hex[:6]}",
            name=name,
            enabled=not disabled,
            editable=False,
            raw=raw,
            conditions=[],
            actions=[FilterAction("keep")],
        )

    match, conditions, cond_ok = _extract_test(if_cmd["test"])
    actions, act_ok = _extract_actions(if_cmd)
    # vacation action inside a normal-looking rule
    if any(a.type == "vacation" for a in actions):
        return FilterRule(
            id=f"vacation-{index}",
            name=name or VACATION_RULE_NAME,
            enabled=not disabled,
            match="all",
            conditions=[],
            actions=actions,
            editable=True,
            raw=raw,
            kind="vacation",
        )

    editable = cond_ok and act_ok and bool(actions)
    if editable:
        for c in conditions:
            if c.field not in _EDITABLE_FIELDS or c.op not in _EDITABLE_OPS:
                editable = False
                break
        for a in actions:
            if a.type not in _EDITABLE_ACTIONS:
                editable = False
                break
    # regex in raw → not editable even if we guessed wrong
    if re.search(r":regex\b", live_body):
        editable = False

    return FilterRule(
        id=f"f{index}-{uuid.uuid4().hex[:8]}" if editable else f"rc-{index}-{uuid.uuid4().hex[:6]}",
        name=name,
        enabled=not disabled,
        match=match if match != "all" else "allof",
        conditions=conditions or ([FilterCondition("from", "contains", "")] if editable else []),
        actions=actions or [FilterAction("keep")],
        editable=editable,
        raw=raw,
        kind="filter",
    )


def combine_vacation_bodies(v: VacationSettings) -> str:
    """SK, then separator, then EN, then DE — only languages that are filled in."""
    parts: list[str] = []
    for part in (v.body_sk, v.body_en, v.body_de):
        text = (part or "").strip()
        if text:
            parts.append(text)
    return VACATION_BODY_SEPARATOR.join(parts)


def split_vacation_body(combined: str) -> tuple[str, str, str]:
    """Split a combined vacation reason back into SK / EN / DE (best-effort)."""
    parts = combined.split(VACATION_BODY_SEPARATOR)
    sk = parts[0].strip() if parts else combined.strip()
    en = parts[1].strip() if len(parts) > 1 else ""
    de = parts[2].strip() if len(parts) > 2 else ""
    return sk, en, de


def _vacation_subject_from_sieve(raw: str) -> str:
    """Map Sieve ``:subject`` (``${orig}`` / ``%s``) back to UI ``{predmet}``."""
    subject = raw.replace("${orig}", "{predmet}").replace("%s", "{predmet}")
    return subject or "Mimo kancelárie: {predmet}"


def _vacation_from_sieve_body(body: str) -> VacationSettings:
    """Best-effort vacation fields from a Sieve vacation command."""
    enabled = "vacation" in body
    subject = "Mimo kancelárie: {predmet}"
    body_sk = VacationSettings().body_sk
    body_en = ""
    body_de = ""
    days = 7
    start = end = None
    if m := re.search(r':subject\s+"([^"]*)"', body):
        subject = _vacation_subject_from_sieve(m.group(1))
    if m := re.search(r":days\s+(\d+)", body):
        days = int(m.group(1))
    reason = ""
    if m := re.search(r"text:\s*\n(.*?)\n\s*\.\s*;", body, re.S):
        reason = m.group(1)
    elif m := re.search(r'vacation[^;]*\n?\s*"([^"]*)"\s*;', body, re.S):
        reason = m.group(1)
    if reason:
        if VACATION_BODY_SEPARATOR in reason:
            body_sk, body_en, body_de = split_vacation_body(reason)
            if not body_sk:
                body_sk = reason.strip()
        else:
            body_sk = reason.strip()
    if m := re.search(r'currentdate[^"]*"ge"[^"]*"([^"]+)"', body):
        start = m.group(1)
    if m := re.search(r'currentdate[^"]*"le"[^"]*"([^"]+)"', body):
        end = m.group(1)
    return VacationSettings(
        enabled=enabled,
        subject=subject,
        body_sk=body_sk,
        body_en=body_en,
        body_de=body_de,
        days=days,
        start=start,
        end=end,
    )


def parse_roundcube_script(script: str, *, script_name: str = DEFAULT_SCRIPT_NAME) -> ParsedScript:
    """Split a Roundcube ManageSieve script into editable / read-only rules + vacation."""
    if not script or not script.strip():
        return ParsedScript(
            preamble='require ["fileinto","reject","vacation","date","relational","imap4flags"];\n',
            rules=[],
            vacation=VacationSettings(),
            script_name=script_name,
        )

    parts = _RULE_SPLIT.split(script)
    preamble = parts[0]
    rules: list[FilterRule] = []
    vacation = VacationSettings()
    # parts: [preamble, '# rule:[', 'Name]\nbody', '# rule:[', ...]
    i = 1
    index = 0
    while i < len(parts):
        if parts[i] == "# rule:[" and i + 1 < len(parts):
            rest = parts[i + 1]
            name, _, after = rest.partition("]")
            block = f"# rule:[{name}]{after}"
            # trim trailing whitespace but keep final newline for stable round-trip
            if i + 2 < len(parts):
                # next marker starts next rule; after already ends before next split piece
                pass
            rule = _parse_rule_block(name, block.rstrip() + "\n", index=index)
            index += 1
            if rule.kind == "vacation":
                vac_body = _uncomment_disabled_body(block) if not rule.enabled else block
                vac_body = _RULE_NAME.sub("", vac_body, count=1)
                extracted = _vacation_from_sieve_body(vac_body)
                if rule.name == VACATION_RULE_NAME_EN or VACATION_MARKER_EN in block:
                    # Legacy Accept-Language EN rule — body is the EN text alone
                    vacation.body_en = extracted.body_sk
                elif rule.name == VACATION_RULE_NAME_DE or VACATION_MARKER_DE in block:
                    vacation.body_de = extracted.body_sk
                else:
                    vacation.subject = extracted.subject
                    vacation.body_sk = extracted.body_sk
                    if extracted.body_en:
                        vacation.body_en = extracted.body_en
                    if extracted.body_de:
                        vacation.body_de = extracted.body_de
                    vacation.days = extracted.days
                    vacation.start = extracted.start
                    vacation.end = extracted.end
                vacation.enabled = vacation.enabled or rule.enabled
                rules.append(rule)
            else:
                rules.append(rule)
            i += 2
        else:
            i += 1

    # Scripts without # rule:[ markers — try sievelib FiltersSet-style parse of whole file
    if not rules and script.strip():
        parser = Parser()
        if parser.parse(script):
            # treat whole as one readonly blob so we never destroy it on save
            rules.append(
                FilterRule(
                    id=f"rc-whole-{uuid.uuid4().hex[:6]}",
                    name="Pravidlá schránky",
                    enabled=True,
                    editable=False,
                    raw=script if script.endswith("\n") else script + "\n",
                    conditions=[],
                    actions=[FilterAction("keep")],
                )
            )
            preamble = ""

    return ParsedScript(preamble=preamble, rules=rules, vacation=vacation, script_name=script_name)


def parse_filters_from_script(script: str) -> list[FilterRule]:
    """Public helper: filter rules only (vacation excluded)."""
    parsed = parse_roundcube_script(script)
    return [r for r in parsed.rules if r.kind != "vacation"]


def validate_condition(c: FilterCondition) -> None:
    """Raise FilterValidationError when a condition would match-all or is invalid."""
    if c.field == "size":
        try:
            kb = int(str(c.value).strip())
        except ValueError as exc:
            raise FilterValidationError(
                "filter_size_invalid",
                "Veľkosť musí byť kladné celé číslo (kB).",
            ) from exc
        if kb <= 0:
            raise FilterValidationError(
                "filter_size_invalid",
                "Veľkosť musí byť kladné celé číslo (kB).",
            )
        return
    if c.field == "header":
        if not (c.header_name or "").strip():
            raise FilterValidationError(
                "filter_header_required",
                "Hlavička musí mať názov (napr. X-Priority).",
            )
        if not str(c.value).strip():
            raise FilterValidationError(
                "filter_condition_required",
                "Filter musí mať aspoň jednu podmienku s vyplnenou hodnotou.",
            )
        return
    if not str(c.value).strip():
        raise FilterValidationError(
            "filter_condition_required",
            "Filter musí mať aspoň jednu podmienku s vyplnenou hodnotou.",
        )


def validate_editable_rules(rules: list[FilterRule]) -> None:
    """Every editable rule needs ≥ 1 non-empty condition (unless match=all / všetky správy)."""
    for rule in rules:
        if not rule.editable or rule.kind == "vacation":
            continue
        if rule.match == "all":
            continue
        usable = [c for c in rule.conditions if str(c.value).strip() or c.field == "size"]
        if not usable:
            raise FilterValidationError(
                "filter_condition_required",
                "Filter musí mať aspoň jednu podmienku s vyplnenou hodnotou.",
            )
        for cond in usable:
            validate_condition(cond)


def compile_condition(c: FilterCondition) -> str:
    """Compile one test. Never emits a match-all test (empty contains / bad size)."""
    validate_condition(c)
    val = _escape(c.value.strip())
    if c.field == "size":
        kb = int(str(c.value).strip())
        op = ":over" if c.op in {"gt", "contains"} else ":under"
        return f"size {op} {kb * 1024}"
    if c.field == "body":
        # RFC 5173 body extension — never silently become a Subject test
        tag = {
            "contains": ":contains",
            "notcontains": ":contains",
            "is": ":is",
            "isnot": ":is",
            "startswith": ":matches",
            "endswith": ":matches",
        }.get(c.op, ":contains")
        if c.op == "startswith":
            body = f'body {tag} "{val}*"'
        elif c.op == "endswith":
            body = f'body {tag} "*{val}"'
        else:
            body = f'body {tag} "{val}"'
        return f"not {body}" if c.op in {"notcontains", "isnot"} else body
    if c.field == "header":
        header = _escape((c.header_name or "").strip())
        use_address = False
    elif c.field == "from":
        header, use_address = "From", True
    elif c.field == "to":
        header, use_address = "To", True
    elif c.field == "cc":
        header, use_address = "Cc", True
    elif c.field == "subject":
        header, use_address = "Subject", False
    else:
        raise FilterValidationError(
            "filter_field_unsupported",
            f"Nepodporované pole podmienky: {c.field}.",
        )
    test = "address" if use_address else "header"
    if c.op == "contains":
        return f'{test} :contains "{header}" "{val}"'
    if c.op == "notcontains":
        return f'not {test} :contains "{header}" "{val}"'
    if c.op == "is":
        return f'{test} :is "{header}" "{val}"'
    if c.op == "isnot":
        return f'not {test} :is "{header}" "{val}"'
    if c.op == "startswith":
        return f'{test} :matches "{header}" "{val}*"'
    if c.op == "endswith":
        return f'{test} :matches "{header}" "*{val}"'
    return f'{test} :contains "{header}" "{val}"'


def apply_live_raw_to_readonly(client_rules: list[FilterRule], live_rules: list[FilterRule]) -> list[FilterRule]:
    """On save, readonly rules take ``raw`` from the live script (by id, else order) — never from the client."""
    live_readonly = [r for r in live_rules if not r.editable and r.kind != "vacation"]
    by_id = {r.id: r for r in live_readonly}
    used: set[str] = set()
    order_i = 0
    out: list[FilterRule] = []
    for rule in client_rules:
        if rule.editable or rule.kind == "vacation":
            out.append(rule)
            continue
        live = by_id.get(rule.id) if rule.id and rule.id not in used else None
        if live is None:
            while order_i < len(live_readonly) and live_readonly[order_i].id in used:
                order_i += 1
            if order_i < len(live_readonly):
                live = live_readonly[order_i]
                order_i += 1
        if live is not None:
            used.add(live.id)
            out.append(
                FilterRule(
                    id=live.id,
                    name=live.name,
                    enabled=live.enabled,
                    match=live.match,
                    conditions=list(live.conditions),
                    actions=list(live.actions),
                    editable=False,
                    raw=live.raw,
                    kind=live.kind,
                )
            )
        # drop client-only readonly noise that has no live counterpart
    # append any live readonly the client omitted (preserve script)
    for live in live_readonly:
        if live.id not in used:
            out.append(live)
    return out


def compile_rule_from_structured(rule: FilterRule) -> str:
    """Emit one Roundcube ``# rule:[…]`` block from structured editable fields."""
    lines: list[str] = [f"# rule:[{rule.name}]"]
    conds = [compile_condition(c) for c in rule.conditions if str(c.value).strip() or c.field == "size"]
    match = "anyof" if rule.match in {"any", "anyof"} else "allof"
    if rule.match == "all":
        test = "true"
    elif not conds:
        raise FilterValidationError(
            "filter_condition_required",
            "Filter musí mať aspoň jednu podmienku s vyplnenou hodnotou.",
        )
    elif len(conds) == 1:
        test = conds[0]
    else:
        test = f"{match} ({', '.join(conds)})"
    body_lines = [f"if {test} {{"]
    for action in rule.actions:
        if action.type == "fileinto" and action.value:
            body_lines.append(f'\tfileinto "{_escape(action.value)}";')
        elif action.type == "redirect" and action.value:
            body_lines.append(f'\tredirect "{_escape(action.value)}";')
        elif action.type == "reject" and action.value:
            body_lines.append(f'\treject "{_escape(action.value)}";')
        elif action.type == "discard":
            body_lines.append("\tdiscard;")
        elif action.type == "addflag":
            body_lines.append('\taddflag "\\\\Flagged";')
        elif action.type == "seen":
            body_lines.append('\taddflag "\\\\Seen";')
        elif action.type == "stop":
            body_lines.append("\tstop;")
        elif action.type == "keep":
            body_lines.append("\tkeep;")
    body_lines.append("}")
    live = "\n".join(body_lines) + "\n"
    if not rule.enabled:
        lines.append(_comment_out_rule_body(live).rstrip("\n"))
        return "\n".join(lines) + "\n"
    lines.append(live.rstrip("\n"))
    return "\n".join(lines) + "\n"


def _vacation_date_tests(v: VacationSettings) -> list[str]:
    tests: list[str] = []
    if v.start:
        tests.append(f'currentdate :value "ge" "iso8601" "{_escape(v.start)}"')
    if v.end:
        tests.append(f'currentdate :value "le" "iso8601" "{_escape(v.end)}"')
    return tests


def _vacation_subject_for_sieve(v: VacationSettings) -> str:
    """UI ``{predmet}`` / legacy ``%s`` → variables ``${orig}`` (Sieve does not expand ``%s``)."""
    raw = (v.subject or "Mimo kancelárie: {predmet}").strip() or "Mimo kancelárie: {predmet}"
    return raw.replace("{predmet}", "${orig}").replace("%s", "${orig}")


def compile_vacation_rule(v: VacationSettings, *, supports_variables: bool = True) -> str:
    """One vacation rule in the active script: combined SK/EN/DE text, optional ``:subject`` via variables.

    Clients rarely send Accept-Language, so language variants are one reason string (SK, separator, EN,
    DE — only filled languages). No extra rules and no ``stop``. If the server lacks ``variables``,
    ``:subject`` is omitted (Dovecot then uses ``Auto: <original subject>``).
    """
    if not v.enabled:
        lines = [f"# rule:[{VACATION_RULE_NAME}]", VACATION_MARKER]
        stub = 'if true {\n\tvacation :days 7 "";\n}\n'
        lines.append(_comment_out_rule_body(stub).rstrip("\n"))
        return "\n".join(lines) + "\n"

    date_tests = _vacation_date_tests(v)
    test = date_tests[0] if len(date_tests) == 1 else (f"allof ({', '.join(date_tests)})" if date_tests else "true")
    reason = combine_vacation_bodies(v) or (v.body_sk or "").strip() or VacationSettings().body_sk
    lines = [f"# rule:[{VACATION_RULE_NAME}]", VACATION_MARKER, f"if {test} {{"]
    if supports_variables:
        lines.append('\tif header :matches "subject" "*" {')
        lines.append('\t\tset "orig" "${1}";')
        lines.append("\t}")
        subject = _escape(_vacation_subject_for_sieve(v))
        vac_head = f'\tvacation :days {int(v.days)} :subject "{subject}"'
    else:
        vac_head = f"\tvacation :days {int(v.days)}"
    if "\n" in reason:
        lines.append(f"{vac_head} text:")
        lines.append(reason)
        lines.append(".")
        lines.append(";")
    else:
        lines.append(vac_head)
        lines.append(f'\t"{_escape(reason)}";')
    lines.append("}")
    return "\n".join(lines) + "\n"


def _ensure_requires(preamble: str, *, vacation: bool, body: bool = False, variables: bool = False) -> str:
    """Ensure needed extensions appear in ``require […]``.

    Preserves a single existing require line byte-for-byte when it already lists everything
    we need (load→save identity for filter-only scripts). Collapses stacked require lines
    (legacy / ManageSieve uploads) into one.
    """
    extras: list[str] = []
    if vacation:
        extras.append("vacation")
    if body:
        extras.append("body")
    if variables:
        extras.append("variables")

    requires = re.findall(r"require\s*\[[^\]]*\]\s*;", preamble or "")
    if not requires:
        base = ["fileinto", "reject", "imap4flags", "vacation", "date", "relational", *extras]
        # dedupe preserving order
        caps: list[str] = []
        for c in base:
            if c not in caps:
                caps.append(c)
        return "require [" + ", ".join(f'"{c}"' for c in caps) + "];\n"

    if len(requires) == 1:
        out = preamble
        for cap in extras:
            if f'"{cap}"' in out or f"'{cap}'" in out:
                continue

            def add(m: re.Match[str], *, _cap: str = cap) -> str:
                inner = m.group(1)
                return f'require [{inner.rstrip()}, "{_cap}"];'

            out = re.sub(r"require\s*\[([^\]]*)\]\s*;", add, out, count=1)
        return out

    # Multiple require lines → merge (keeps first-seen order, appends missing extras)
    caps = []
    for req in requires:
        for cap in re.findall(r'"([^"]+)"', req):
            if cap not in caps:
                caps.append(cap)
    for cap in extras:
        if cap not in caps:
            caps.append(cap)
    rest = re.sub(r"require\s*\[[^\]]*\]\s*;\s*", "", preamble or "")
    return "require [" + ", ".join(f'"{c}"' for c in caps) + "];\n" + rest.lstrip("\n")


def compile_script(
    parsed: ParsedScript,
    *,
    vacation: VacationSettings | None = None,
    rules: list[FilterRule] | None = None,
    include_vacation: bool | None = None,
    supports_variables: bool = True,
) -> str:
    """Rebuild script. Prefer each rule's ``raw`` when present (load→save identical)."""
    vac = vacation if vacation is not None else parsed.vacation
    rule_list = rules if rules is not None else [r for r in parsed.rules if r.kind != "vacation"]
    had_vacation = any(r.kind == "vacation" for r in parsed.rules)
    write_vacation = include_vacation if include_vacation is not None else (vac.enabled or had_vacation)
    needs_body = any(c.field == "body" for rule in rule_list if rule.editable for c in rule.conditions)
    use_variables = bool(write_vacation and vac.enabled and supports_variables)

    preamble = _ensure_requires(
        parsed.preamble or "", vacation=write_vacation, body=needs_body, variables=use_variables
    )
    if not preamble.endswith("\n"):
        preamble += "\n"

    chunks: list[str] = [preamble.rstrip("\n") + "\n"]
    for rule in rule_list:
        if rule.kind == "vacation":
            continue
        if rule.raw:
            chunks.append(rule.raw if rule.raw.endswith("\n") else rule.raw + "\n")
        else:
            chunks.append(compile_rule_from_structured(rule))

    if write_vacation:
        chunks.append(compile_vacation_rule(vac, supports_variables=supports_variables))

    text = "".join(chunks)
    if not text.endswith("\n"):
        text += "\n"
    return text


def apply_vacation_to_script(
    script: str,
    vacation: VacationSettings,
    *,
    script_name: str = DEFAULT_SCRIPT_NAME,
    supports_variables: bool = True,
) -> str:
    """Replace vacation rule(s) with a single combined rule; filter rules keep their raw text."""
    parsed = parse_roundcube_script(script, script_name=script_name)
    filters = [r for r in parsed.rules if r.kind != "vacation"]
    rebuilt = ParsedScript(
        preamble=parsed.preamble,
        rules=filters,
        vacation=vacation,
        script_name=script_name,
    )
    return compile_script(rebuilt, vacation=vacation, rules=filters, supports_variables=supports_variables)


def compile_filters(rules: list[FilterRule]) -> str:
    """Compile structured filters (no vacation) — used when creating new Od→folder rules."""
    parsed = ParsedScript(
        preamble='require ["fileinto","reject","vacation","date","relational","imap4flags"];\n',
        rules=rules,
        vacation=VacationSettings(enabled=False),
    )
    # Force structured compile (clear raw)
    cleaned = [
        FilterRule(
            id=r.id,
            name=r.name,
            enabled=r.enabled,
            match=r.match,
            conditions=r.conditions,
            actions=r.actions,
            editable=True,
            raw=None,
            kind="filter",
        )
        for r in rules
        if r.kind != "vacation"
    ]
    return compile_script(parsed, vacation=VacationSettings(enabled=False), rules=cleaned)


def compile_vacation(v: VacationSettings, *, supports_variables: bool = True) -> str:
    """Deprecated standalone vacation script — kept for unit tests; prefer apply_vacation_to_script."""
    if not v.enabled:
        return 'require ["vacation"];\n'
    caps = '"vacation","date","relational"'
    if supports_variables:
        caps += ',"variables"'
    return f"require [{caps}];\n" + compile_vacation_rule(v, supports_variables=supports_variables)


def sieve_supports_variables(client: ManageSieveClient) -> bool:
    """True when the ManageSieve server advertises the ``variables`` extension (RFC 5229)."""
    try:
        caps = client.get_sieve_capabilities() or []
    except Exception:
        return False
    return any(str(c).lower() == "variables" for c in caps)


def connect_sieve(
    settings: Settings,
    mailbox: Mailbox,
    *,
    username: str,
    password: str,
) -> ManageSieveClient:
    """Connect to ManageSieve. Prefer STARTTLS; fall back to cleartext once.

    Callers that must not block the event loop use ``app.mail.sieve_async`` (TCP
    connect timeout 5 s, overall 10 s, Redis unavailable cache).
    """
    host, port = resolve_sieve_endpoint(mailbox, settings)
    if not mailbox.sieve_enabled:
        raise SieveError("sieve_disabled")
    if not sieve_host_allowed(settings, host):
        raise SieveError("sieve_host_not_allowed", host)
    client = ManageSieveClient(host, port)
    try:
        ok = client.connect(username, password, starttls=True, authmech="LOGIN")
    except SieveError:
        raise
    except Exception as exc:
        # Distinguishes black-hole / refused TCP from auth failure (pilot #18).
        if isinstance(exc, (TimeoutError, OSError, socket.timeout)):
            raise SieveError("sieve_unavailable", str(exc) or type(exc).__name__) from exc
        # sievelib.Error on connection failure
        if type(exc).__name__ == "Error" and "Connection to server failed" in str(exc):
            raise SieveError("sieve_unavailable", str(exc)) from exc
        ok = False
    if not ok:
        client = ManageSieveClient(host, port)
        try:
            if not client.connect(username, password, starttls=False, authmech="LOGIN"):
                raise SieveError("sieve_auth_failed")
        except SieveError:
            raise
        except Exception as exc:
            if isinstance(exc, (TimeoutError, OSError, socket.timeout)):
                raise SieveError("sieve_unavailable", str(exc) or type(exc).__name__) from exc
            if type(exc).__name__ == "Error" and "Connection to server failed" in str(exc):
                raise SieveError("sieve_unavailable", str(exc)) from exc
            raise SieveError("sieve_auth_failed") from exc
    return client


def active_script_name(client: ManageSieveClient) -> str:
    """Return the active ManageSieve script name (only one may be active)."""
    result = client.listscripts()
    if not result:
        return DEFAULT_SCRIPT_NAME
    active, _scripts = result
    return active or DEFAULT_SCRIPT_NAME


def get_script(client: ManageSieveClient, name: str) -> str:
    content = client.getscript(name)
    if content is None:
        return ""
    return content if isinstance(content, str) else content.decode("utf-8", errors="replace")


def put_script(client: ManageSieveClient, name: str, content: str, *, activate: bool = True) -> None:
    """Upload script. ``activate`` may only keep/set this same name — never switch sets for vacation."""
    ok = client.putscript(name, content)
    if not ok:
        raise SieveError("sieve_put_failed", getattr(client, "errmsg", None) or str(client))
    if activate:
        # Always SETACTIVE after PUTSCRIPT. Fresh mailboxes report no ACTIVE; falling back to
        # DEFAULT_SCRIPT_NAME and skipping SETACTIVE left vacation scripts inactive on imap-test.
        if not client.setactive(name):
            raise SieveError("sieve_setactive_failed", name)


def filters_to_dicts(rules: list[FilterRule]) -> list[dict[str, Any]]:
    return [
        {
            "id": r.id,
            "name": r.name,
            "enabled": r.enabled,
            "match": r.match,
            "conditions": [
                {
                    "field": c.field,
                    "op": c.op,
                    "value": c.value,
                    **({"header_name": c.header_name} if c.header_name else {}),
                }
                for c in r.conditions
            ],
            "actions": [{"type": a.type, "value": a.value} for a in r.actions],
            "editable": r.editable,
            "raw": r.raw,
            "kind": r.kind,
            "readonly_label": None if r.editable else "Pravidlo z Roundcube (len na čítanie)",
        }
        for r in rules
    ]


def dicts_to_filters(raw: list[dict[str, Any]]) -> list[FilterRule]:
    out: list[FilterRule] = []
    for item in raw:
        editable = bool(item.get("editable", True))
        raw_block = item.get("raw")
        out.append(
            FilterRule(
                id=str(item.get("id") or ""),
                name=str(item.get("name") or "Filter"),
                enabled=bool(item.get("enabled", True)),
                match=str(item.get("match") or "allof"),
                conditions=[
                    FilterCondition(
                        field=str(c.get("field") or "from"),
                        op=str(c.get("op") or "contains"),
                        value=str(c.get("value") or ""),
                        header_name=(str(c["header_name"]) if c.get("header_name") else None),
                    )
                    for c in (item.get("conditions") or [])
                ],
                actions=[
                    FilterAction(type=str(a.get("type") or "fileinto"), value=str(a.get("value") or ""))
                    for a in (item.get("actions") or [])
                ],
                editable=editable,
                raw=str(raw_block) if raw_block else None,
                kind=str(item.get("kind") or "filter"),
            )
        )
    return out
