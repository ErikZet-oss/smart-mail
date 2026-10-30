"""Typed settings schema for W12 (SETTINGS_SPEC 01–07, 09, 09b, 10–12).

Exported as `settings_schema.json` for the web client and a CI snapshot vs the spec.
Section 07 in Phase 2b is summaries-only; autonomy matrix lands in 2f.
"""

from __future__ import annotations

from typing import Any, Literal

Control = Literal[
    "text",
    "textarea",
    "email",
    "tel",
    "url",
    "number",
    "select",
    "segmented",
    "switch",
    "slider",
    "button",
    "info",
    "html",
    "list",
    "table",
    "readonly",
]
Scope = Literal["P", "A", "M", "G", "B", "device"]


def field(
    id: str,
    *,
    label: str,
    control: Control,
    default: Any = None,
    help: str | None = None,
    scope: Scope = "P",
    options: list[dict[str, str]] | None = None,
    validation: dict[str, Any] | None = None,
    admin_only: bool = False,
) -> dict[str, Any]:
    return {
        "id": id,
        "label": label,
        "control": control,
        "default": default,
        "help": help,
        "scope": scope,
        "options": options or [],
        "validation": validation or {},
        "admin_only": admin_only,
    }


PHASE_1F_SECTIONS: list[dict[str, Any]] = [
    {
        "id": "01",
        "path": "preferences",
        "title": "Nastavenia",
        "admin_only": False,
        "subs": [
            {
                "id": "01a",
                "path": "ui",
                "title": "Používateľské rozhranie",
                "fields": [
                    field(
                        "language",
                        label="Jazyk rozhrania",
                        control="select",
                        default="sk",
                        help="Aplikácia je len v slovenčine.",
                    ),
                    field("timezone", label="Časové pásmo", control="select", default="Europe/Bratislava"),
                    field(
                        "date_format",
                        label="Formát dátumu",
                        control="select",
                        default="d_m_yyyy",
                        options=[
                            {"value": "d_m_yyyy", "label": "25. 10. 2026"},
                            {"value": "d.m.yyyy", "label": "25.10.2026"},
                            {"value": "yyyy-mm-dd", "label": "2026-10-25"},
                        ],
                    ),
                    field(
                        "time_format",
                        label="Formát času",
                        control="segmented",
                        default="24h",
                        options=[{"value": "24h", "label": "24 h"}, {"value": "12h", "label": "12 h"}],
                    ),
                    field(
                        "theme",
                        label="Vzhľad",
                        control="segmented",
                        default="system",
                        options=[
                            {"value": "light", "label": "Svetlý"},
                            {"value": "dark", "label": "Tmavý"},
                            {"value": "system", "label": "Podľa systému"},
                        ],
                    ),
                    field(
                        "classic",
                        label="Klasické zobrazenie",
                        control="switch",
                        default=False,
                        help="Skryje AI triedenie, zhrnutia a asistenta – vyzerá ako Roundcube.",
                    ),
                    field(
                        "home_after_login",
                        label="Po prihlásení otvoriť",
                        control="select",
                        default="inbox",
                        options=[
                            {"value": "inbox", "label": "Doručená pošta"},
                            {"value": "today", "label": "Dnes"},
                        ],
                    ),
                ],
            },
            {
                "id": "01b",
                "path": "mailbox-view",
                "title": "Zobrazenie schránky",
                "fields": [
                    field(
                        "layout",
                        label="Rozloženie",
                        control="segmented",
                        default="three",
                        options=[
                            {"value": "three", "label": "Tri stĺpce"},
                            {"value": "list", "label": "Zoznam bez náhľadu"},
                        ],
                    ),
                    field(
                        "density",
                        label="Hustota zoznamu",
                        control="segmented",
                        default="compact",
                        options=[
                            {"value": "compact", "label": "Kompaktná"},
                            {"value": "comfortable", "label": "Pohodlná"},
                        ],
                    ),
                    field("show_ai_summary", label="Zobraziť AI zhrnutie v zozname", control="switch", default=True),
                    field(
                        "mode",
                        label="Režim zoznamu",
                        control="segmented",
                        default="list",
                        options=[
                            {"value": "list", "label": "Zoznam"},
                            {"value": "conversations", "label": "Konverzácie"},
                        ],
                    ),
                    field(
                        "sort",
                        label="Zoraďovanie",
                        control="select",
                        default="date_received",
                        options=[
                            {"value": "date_received", "label": "Dátum prijatia"},
                            {"value": "date_sent", "label": "Dátum odoslania"},
                            {"value": "subject", "label": "Predmet"},
                            {"value": "from", "label": "Od/Komu"},
                            {"value": "size", "label": "Veľkosť"},
                        ],
                    ),
                    field(
                        "sort_dir",
                        label="Systém zoraďovania",
                        control="segmented",
                        default="desc",
                        options=[
                            {"value": "asc", "label": "vzostupne"},
                            {"value": "desc", "label": "zostupne"},
                        ],
                    ),
                    field(
                        "page_size",
                        label="Počet správ na stránku",
                        control="select",
                        default=50,
                        options=[
                            {"value": "25", "label": "25"},
                            {"value": "50", "label": "50"},
                            {"value": "100", "label": "100"},
                            {"value": "200", "label": "200"},
                        ],
                    ),
                    field(
                        "mark_read",
                        label="Označiť ako prečítané",
                        control="select",
                        default="delay3",
                        options=[
                            {"value": "immediate", "label": "Ihneď"},
                            {"value": "delay3", "label": "Po 3 sekundách"},
                            {"value": "never", "label": "Nikdy"},
                        ],
                    ),
                    field(
                        "after_delete",
                        label="Po vymazaní alebo archivovaní otvoriť",
                        control="select",
                        default="next",
                        options=[
                            {"value": "next", "label": "Ďalšiu správu"},
                            {"value": "previous", "label": "Predchádzajúcu"},
                            {"value": "list", "label": "Zoznam"},
                        ],
                    ),
                ],
            },
            {
                "id": "01c",
                "path": "reading",
                "title": "Zobrazovanie správ",
                "fields": [
                    field(
                        "remote_images",
                        label="Obrázky z internetu",
                        control="select",
                        default="known",
                        help="Blokovanie chráni pred sledovaním.",
                        options=[
                            {"value": "never", "label": "Nikdy"},
                            {"value": "known", "label": "Od známych odosielateľov"},
                            {"value": "always", "label": "Vždy"},
                        ],
                    ),
                    field("prefer_html", label="Uprednostniť HTML", control="switch", default=True),
                    field(
                        "show_attachments_below", label="Zobraziť prílohy pod správou", control="switch", default=True
                    ),
                ],
            },
            {
                "id": "01d",
                "path": "composing",
                "title": "Vytváranie správ",
                "fields": [
                    field(
                        "compose_format",
                        label="Formát správy",
                        control="segmented",
                        default="html",
                        options=[
                            {"value": "html", "label": "HTML"},
                            {"value": "plain", "label": "Čistý text"},
                        ],
                    ),
                    field(
                        "autosave",
                        label="Automaticky ukladať koncept",
                        control="select",
                        default="30",
                        options=[
                            {"value": "30", "label": "30 s"},
                            {"value": "60", "label": "1 min"},
                            {"value": "300", "label": "5 min"},
                            {"value": "never", "label": "Nikdy"},
                        ],
                    ),
                    field(
                        "undo_send_seconds",
                        label="Oneskorenie odoslania (Späť)",
                        control="slider",
                        default=10,
                        help="Počas tohto času môžete odoslanie zrušiť.",
                        validation={"min": 0, "max": 30, "step": 5},
                    ),
                    field("default_mdn", label="Potvrdenie o doručení predvolene", control="switch", default=False),
                    field(
                        "signature_on_reply",
                        label="Pridať podpis pri odpovedi a preposlaní",
                        control="switch",
                        default=True,
                    ),
                    field("pre_send_check", label="Kontrola pred odoslaním", control="switch", default=True),
                ],
            },
            {
                "id": "01e",
                "path": "shortcuts",
                "title": "Klávesové skratky",
                "fields": [
                    field("shortcuts_enabled", label="Klávesové skratky zapnuté", control="switch", default=True),
                    field(
                        "shortcuts_list",
                        label="Zoznam skratiek",
                        control="info",
                        help="Skratky sú pre všetkých rovnaké. Ťahák príde vo fáze 1h.",
                    ),
                ],
            },
        ],
    },
    {
        "id": "02",
        "path": "folders",
        "title": "Priečinky",
        "admin_only": False,
        "subs": [],
        "fields": [
            field(
                "hint",
                label="Správa priečinkov",
                control="info",
                help="Správa priečinkov je aj v stĺpci G3; tu nastavíte odber a súkromné priečinky.",
                scope="M",
            ),
        ],
    },
    {
        "id": "03",
        "path": "identity",
        "title": "Identity a Môj profil",
        "admin_only": False,
        "subs": [
            {"id": "03a", "path": "list", "title": "Identity", "fields": []},
            {"id": "03b", "path": "profile", "title": "Môj profil", "fields": []},
        ],
    },
    {
        "id": "04",
        "path": "responses",
        "title": "Odpovede",
        "admin_only": False,
        "subs": [],
        "fields": [],
    },
    {
        "id": "05",
        "path": "filters",
        "title": "Filtre",
        "admin_only": False,
        "subs": [],
        "fields": [
            field(
                "server_note",
                label="Filtre",
                control="info",
                help="Filtre fungujú na serveri – aj keď je aplikácia zatvorená, aj v Roundcube.",
                scope="M",
            ),
        ],
    },
    {
        "id": "06",
        "path": "vacation",
        "title": "Mimo kancelárie",
        "admin_only": False,
        "subs": [],
        "fields": [
            field("enabled", label="Automatická odpoveď", control="switch", default=False, scope="M"),
            field("subject", label="Predmet", control="text", default="Mimo kancelárie: {predmet}", scope="M"),
            field("body_sk", label="Text odpovede (SK)", control="textarea", scope="M"),
            field(
                "days",
                label="Odpovedať tomu istému odosielateľovi najviac raz za",
                control="select",
                default=7,
                scope="M",
                options=[
                    {"value": "1", "label": "1 deň"},
                    {"value": "3", "label": "3 dni"},
                    {"value": "7", "label": "7 dní"},
                ],
            ),
        ],
    },
    {
        "id": "07",
        "path": "ai",
        "title": "AI asistent",
        "admin_only": False,
        "subs": [],
        "fields": [
            field(
                "show_ai_summary",
                label="Zhrnutia v zozname",
                control="switch",
                default=True,
                help="Pod predmetom v zozname zobrazí krátke AI zhrnutie. V Klasickom zobrazení je vypnuté.",
                scope="P",
            ),
            # ⚠ per login (D8): re-auth + audit; external send and Money writes locked at 2 in code
            field(
                "ai.autonomy",
                label="Samostatnosť ⚠",
                control="table",
                default=None,
                help="Koľko smie AI urobiť sama. Odoslanie von a zápis do Money vždy schvaľuje človek.",
                scope="A",
            ),
        ],
    },
    {
        "id": "09",
        "path": "security",
        "title": "Bezpečnosť",
        "admin_only": False,
        "subs": [],
        "fields": [
            field(
                "login_info",
                label="Prihlásenie",
                control="info",
                help="Prihlasujete sa e-mailom a heslom k pošte. Heslo sa mení na mailovom serveri.",
                scope="A",
            ),
            field("sessions", label="Aktívne relácie", control="table", scope="A"),
        ],
    },
    {
        "id": "09b",
        "path": "provider",
        "title": "Nastavenia e-mail schránky",
        "admin_only": False,
        "subs": [],
        "fields": [
            field(
                "provider_info",
                label="Informácie o schránke",
                control="info",
                help="Tieto nastavenia sú na mailovom serveri (D20).",
                scope="M",
            ),
            field(
                "vacation_hint",
                label="Automatická odpoveď",
                control="info",
                help="Používajte Mimo kancelárie (06) – je to tá istá automatická odpoveď na serveri.",
            ),
        ],
    },
    {
        "id": "10",
        "path": "users",
        "title": "Používatelia a role",
        "admin_only": True,
        "subs": [],
        "fields": [],
    },
    {
        "id": "11",
        "path": "branches",
        "title": "Pobočky a osoby",
        "admin_only": True,
        "subs": [
            {"id": "11a", "path": "details", "title": "Údaje", "fields": []},
            {"id": "11b", "path": "people", "title": "Osoby", "fields": []},
            {"id": "11c", "path": "signature", "title": "Podpis", "fields": []},
            {"id": "11d", "path": "login", "title": "Prihlasovanie", "fields": []},
            {"id": "11e", "path": "money", "title": "Money", "fields": []},
        ],
    },
    {
        "id": "12",
        "path": "mailboxes",
        "title": "Schránky",
        "admin_only": True,
        "subs": [],
        "fields": [],
    },
    {
        # SETTINGS_SPEC 17 AI – správa (G, admin); Phase 2e brings 17d, the other tabs follow in 2e/2f.
        "id": "17",
        "path": "ai-admin",
        "title": "AI – správa",
        "admin_only": True,
        "subs": [
            {"id": "17b", "path": "autonomy", "title": "Samostatnosť AI", "fields": []},
            {"id": "17d", "path": "style", "title": "Štýl a znalosti", "fields": []},
            {"id": "17e", "path": "rules", "title": "Pravidlá", "fields": []},
            {
                "id": "17f",
                "path": "shadow",
                "title": "Tieňový režim, spotreba a presnosť",
                "fields": [
                    # ⚠ change (SETTINGS_SPEC §0): confirm dialog + re-auth; off shows AI suggestions to everybody
                    field(
                        "ai.shadow_replies",
                        label="Tieňový režim návrhov odpovedí ⚠",
                        control="switch",
                        default=True,
                        help="Návrhy sa tvoria, ale nikto ich nevidí. Vypnutie vyžaduje potvrdenie heslom.",
                        scope="G",
                        admin_only=True,
                    )
                ],
            },
        ],
        "fields": [],
    },
]


def schema_document() -> dict[str, Any]:
    return {
        "version": "2b",
        "phase": "2b",
        "sections": PHASE_1F_SECTIONS,
    }


SECTION_PATHS = {
    "preferences": "01",
    "folders": "02",
    "identity": "03",
    "responses": "04",
    "filters": "05",
    "vacation": "06",
    "ai": "07",
    "security": "09",
    "provider": "09b",
    "users": "10",
    "branches": "11",
    "mailboxes": "12",
    "ai-admin": "17",
}
