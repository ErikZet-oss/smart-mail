"""ManageSieve client for Filtre (05) and Mimo kancelárie (06). Roundcube-compatible script names."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from sievelib.managesieve import Client as ManageSieveClient

from app.core.config import Settings
from app.mail.models import Mailbox

# Roundcube ManageSieve plugin historically activates a script named "roundcube".
FILTER_SCRIPT = "roundcube"
VACATION_SCRIPT = "vacation"

_TEST_SIEVE_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "imap-test"})


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


@dataclass
class FilterAction:
    type: str  # fileinto|redirect|reject|discard|addflag|stop|keep
    value: str = ""


@dataclass
class FilterRule:
    id: str
    name: str
    enabled: bool = True
    match: str = "allof"  # all|anyof|allof
    conditions: list[FilterCondition] = field(default_factory=list)
    actions: list[FilterAction] = field(default_factory=list)


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


def compile_filters(rules: list[FilterRule]) -> str:
    """Compile structured filter rules to a Sieve script (fileinto + basic tests)."""
    lines = ['require ["fileinto", "imap4flags", "reject"];', ""]
    for rule in rules:
        if not rule.enabled:
            continue
        conds: list[str] = []
        for c in rule.conditions:
            val = _escape(c.value)
            header = {
                "subject": "Subject",
                "from": "From",
                "to": "To",
                "cc": "Cc",
                "header": "Subject",
            }.get(c.field, "Subject")
            if c.field == "body":
                # body tests need the body extension; fall back to subject contains for Phase 1f
                conds.append(f'header :contains "Subject" "{val}"')
            elif c.field == "size":
                try:
                    kb = int(c.value)
                except ValueError:
                    continue
                op = ":over" if c.op in {"gt", "contains"} else ":under"
                conds.append(f"size {op} {kb * 1024}")
            elif c.op == "contains":
                conds.append(f'header :contains "{header}" "{val}"')
            elif c.op == "notcontains":
                conds.append(f'not header :contains "{header}" "{val}"')
            elif c.op == "is":
                conds.append(f'header :is "{header}" "{val}"')
            elif c.op == "isnot":
                conds.append(f'not header :is "{header}" "{val}"')
            elif c.op == "startswith":
                conds.append(f'header :matches "{header}" "{val}*"')
            elif c.op == "endswith":
                conds.append(f'header :matches "{header}" "*{val}"')
            else:
                conds.append(f'header :contains "{header}" "{val}"')
        match = "anyof" if rule.match in {"any", "anyof"} else "allof"
        if not conds:
            test = "true"
        elif len(conds) == 1:
            test = conds[0]
        else:
            test = f"{match} ({', '.join(conds)})"
        lines.append(f"# rule:{rule.id} name:{_escape(rule.name)}")
        lines.append(f"if {test} {{")
        for action in rule.actions:
            if action.type == "fileinto" and action.value:
                lines.append(f'  fileinto "{_escape(action.value)}";')
            elif action.type == "redirect" and action.value:
                lines.append(f'  redirect "{_escape(action.value)}";')
            elif action.type == "reject" and action.value:
                lines.append(f'  reject "{_escape(action.value)}";')
            elif action.type == "discard":
                lines.append("  discard;")
            elif action.type == "addflag":
                lines.append('  addflag "\\\\Flagged";')
            elif action.type == "seen":
                lines.append('  addflag "\\\\Seen";')
            elif action.type == "stop":
                lines.append("  stop;")
            elif action.type == "keep":
                lines.append("  keep;")
        lines.append("}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def compile_vacation(v: VacationSettings) -> str:
    if not v.enabled:
        return 'require ["vacation"];\n'
    subject = _escape(v.subject.replace("{predmet}", "%s"))
    body = _escape(v.body_sk)
    lines = [
        'require ["vacation"];',
        f'vacation :days {int(v.days)} :subject "{subject}"',
        f'"{body}";',
        "",
    ]
    return "\n".join(lines)


def parse_filters_from_script(script: str) -> list[FilterRule]:
    """Best-effort parse of scripts we wrote (rule: comments). Unknown scripts → one opaque rule."""
    rules: list[FilterRule] = []
    for match in re.finditer(r"# rule:(\S+) name:(.+)\nif (.+?) \{\n(.*?)\n\}", script, re.S):
        rid, name, _test, body = match.groups()
        actions: list[FilterAction] = []
        if m := re.search(r'fileinto "([^"]+)"', body):
            actions.append(FilterAction("fileinto", m.group(1)))
        if m := re.search(r'redirect "([^"]+)"', body):
            actions.append(FilterAction("redirect", m.group(1)))
        if "discard;" in body:
            actions.append(FilterAction("discard"))
        if "stop;" in body:
            actions.append(FilterAction("stop"))
        rules.append(
            FilterRule(
                id=rid,
                name=name.replace('\\"', '"'),
                enabled=True,
                conditions=[FilterCondition("subject", "contains", "")],
                actions=actions or [FilterAction("keep")],
            )
        )
    return rules


def connect_sieve(
    settings: Settings,
    mailbox: Mailbox,
    *,
    username: str,
    password: str,
) -> ManageSieveClient:
    host, port = resolve_sieve_endpoint(mailbox, settings)
    if not mailbox.sieve_enabled:
        raise SieveError("sieve_disabled")
    if not sieve_host_allowed(settings, host):
        raise SieveError("sieve_host_not_allowed", host)
    client = ManageSieveClient(host, port)
    if not client.connect(username, password, starttls=True, authmech="LOGIN"):
        # local dovecot often has no STARTTLS on 4190
        client = ManageSieveClient(host, port)
        if not client.connect(username, password, starttls=False, authmech="LOGIN"):
            raise SieveError("sieve_auth_failed")
    return client


def put_script(client: ManageSieveClient, name: str, content: str, *, activate: bool = True) -> None:
    ok = client.putscript(name, content)
    if not ok:
        raise SieveError("sieve_put_failed", getattr(client, "errmsg", None) or str(client))
    if activate:
        client.setactive(name)


def get_script(client: ManageSieveClient, name: str) -> str:
    content = client.getscript(name)
    if content is None:
        return ""
    return content if isinstance(content, str) else content.decode("utf-8", errors="replace")


def filters_to_dicts(rules: list[FilterRule]) -> list[dict[str, Any]]:
    return [
        {
            "id": r.id,
            "name": r.name,
            "enabled": r.enabled,
            "match": r.match,
            "conditions": [{"field": c.field, "op": c.op, "value": c.value} for c in r.conditions],
            "actions": [{"type": a.type, "value": a.value} for a in a_list(r.actions)],
        }
        for r in rules
    ]


def a_list(actions: list[FilterAction]) -> list[FilterAction]:
    return actions


def dicts_to_filters(raw: list[dict[str, Any]]) -> list[FilterRule]:
    out: list[FilterRule] = []
    for item in raw:
        out.append(
            FilterRule(
                id=str(item.get("id") or ""),
                name=str(item.get("name") or "Filter"),
                enabled=bool(item.get("enabled", True)),
                match=str(item.get("match") or "allof"),
                conditions=[
                    FilterCondition(
                        field=str(c.get("field") or "subject"),
                        op=str(c.get("op") or "contains"),
                        value=str(c.get("value") or ""),
                    )
                    for c in (item.get("conditions") or [])
                ],
                actions=[
                    FilterAction(type=str(a.get("type") or "keep"), value=str(a.get("value") or ""))
                    for a in (item.get("actions") or [])
                ],
            )
        )
    return out
