#!/usr/bin/env python3
"""
money_probe.py - READ-ONLY probe of the Money S4 API module: GraphQL (/graphql) and REST (S5Api swagger).

Purpose
  Verifies on YOUR server what the Smart Mail integration depends on: token (/connect/token, scope S5Api),
  GraphQL filters (Field~op~value, date format, OR), supplier codes (ArticleSuppliers -> article link),
  stock (WarehouseStocks), customer prices (ProdejniCeny), delivery notes with article/warehouse items,
  whether received invoice items link to delivery note items, REST filter syntax, Person -> Company link,
  and the PDF Report endpoint with your report ID.
  This script finds out empirically and writes probe_output/report.md + report.json.
  Give report.md to Claude Code / Cursor at the start of Phase 3 (Money Bridge).

  With --orders it also probes customer orders (Objednávka prijatá) for docs/ORDERS_SPEC.md and writes
  probe_output/orders.md.

  With --branches (read-only) it lists the codebooks for Settings 11e (Centres, Warehouses, PriceLists,
  NumericalSeries, AccountAssignments) and analyses existing received delivery notes (counts only): numerical series
  per centre, warehouse per centre, Cenik_ID on items, stock-movement times, vratky, side costs, and - with
  PROBE_DL_NUMBER + PROBE_DL_DOKLAD_PRIJATY - whether "Doklad prijatý" is stored in Odkaz. -> probe_output/branches.md

Safety
  - Only GET requests and read-only GraphQL queries (plus the token POST). By default it never creates, changes or
    deletes anything.
  - The ONLY exception is "--orders --allow-write-test": it creates 1-2 test orders (Odkaz "SMPROBE-...") on the
    agenda, reads them back and deletes them again. It refuses to run unless MONEY_AGENDA_LABEL=TEST is set and you
    type TEST when asked. Never use it on the production agenda.
  - Run it against the TEST agenda first.
  - Values of business data are NOT written to the report unless --show-values is used
    (field names and types only), so the report can be shared with a coding agent.

Requirements
  Python 3.8+, standard library only (works on the Windows server next to Money too).

Usage
  1) Copy the block below into a file "probe.env" next to this script and fill it in:

     MONEY_BASE_URL=http://money-server:1080        # API URL from Money: Administrácia > Výmena dát > REST API > Konfigurácia API
     MONEY_CLIENT_ID=...                             # from "Kľúče API"
     MONEY_CLIENT_SECRET=...
     # MONEY_TOKEN_URL=http://money-server:1080/connect/token   # optional, if you know it
     # MONEY_TOKEN=eyJ...                                       # optional, paste a ready JWT instead
     # MONEY_SCOPE=                                              # optional
     PROBE_INVOICE_NUMBER=FV2026/0123               # an existing issued invoice number (cisloDokladu)
     # PROBE_DL_NUMBER=302600123                     # --branches: an existing received delivery note number
     # PROBE_DL_DOKLAD_PRIJATY=FA-2026-00456       # --branches: its "Doklad prijatý" exactly as shown in Money
     PROBE_EMAIL=novak@abcstav.sk                    # e-mail of a contact person that exists in the address book
     PROBE_ARTICLE=DIN 933                           # a code or name fragment of an existing article
     PROBE_COMPANY_ICO=12345678                      # IČO of an existing customer (for customer prices)
     # MONEY_REST_VERSION=v2.0                       # REST API version prefix (v1.0 or v2.0)
     # PROBE_REPORT_ID=00000000-0000-0000-0000-000000000000  # GUID of the invoice print report (or an integer report config id)
     # MONEY_INSECURE=1                                # only if the API uses a self-signed HTTPS certificate in the LAN
     # --- only for --orders --allow-write-test (TEST agenda!) ---
     # MONEY_AGENDA_LABEL=TEST
     # PROBE_ORDER_COMPANY_ICO=12345678              # test customer, ideally WITH a discount (HodnotaSlevy > 0)
     # PROBE_ORDER_ARTICLE_CODE=DIN933M10X30A2       # Kod of a stock article with a price for that customer
     # PROBE_ORDER_SERIES_ID=                        # optional GUID of the numerical series for received orders

  2) python money_probe.py --env probe.env            (add --save-pdf to save the generated PDF)
  3) python money_probe.py --env probe.env --orders   (customer orders, read-only)
     python money_probe.py --env probe.env --orders --allow-write-test   (TEST agenda only, see Safety)
"""
import argparse
import base64
import datetime as dt
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API = "/v2.0"
OUT_DIR = "probe_output"
SAFE_VALUE_FIELDS = {"cisloDokladu", "datumVystaveni"}

report = {"generated_at": dt.datetime.now().isoformat(timespec="seconds"), "steps": []}


# ----------------------------------------------------------------------------- helpers
def load_env(path):
    if not path:
        return
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            val = val.split(" #", 1)[0].strip().strip('"').strip("'")
            os.environ.setdefault(key.strip(), val)


def env(name, default=None):
    v = os.environ.get(name)
    return v if v not in (None, "") else default


def step(name, ok, **details):
    entry = {"step": name, "ok": ok, **details}
    report["steps"].append(entry)
    mark = "OK " if ok else ("-- " if ok is None else "ERR")
    print(f"[{mark}] {name}" + (f" | {details.get('note')}" if details.get("note") else ""))
    return entry


class Http:
    def __init__(self, base, insecure=False):
        self.base = base.rstrip("/")
        self.token = None
        self.ctx = None
        if insecure:
            self.ctx = ssl.create_default_context()
            self.ctx.check_hostname = False
            self.ctx.verify_mode = ssl.CERT_NONE

    def request(self, method, url, data=None, headers=None, raw=False, timeout=60):
        if not url.startswith("http"):
            url = self.base + url
        hdrs = {"Accept": "application/json"}
        if self.token:
            hdrs["Authorization"] = f"Bearer {self.token}"
        if headers:
            hdrs.update(headers)
        req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
        started = time.time()
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=self.ctx) as resp:
                body = resp.read()
                ms = int((time.time() - started) * 1000)
                ctype = resp.headers.get("Content-Type", "")
                if raw:
                    return resp.status, ctype, body, ms
                return resp.status, ctype, _unwrap(_json(body)), ms
        except urllib.error.HTTPError as e:
            body = e.read()
            ms = int((time.time() - started) * 1000)
            return e.code, e.headers.get("Content-Type", ""), (body if raw else _json(body)), ms
        except Exception as e:  # network errors
            return 0, "", str(e), int((time.time() - started) * 1000)

    def get(self, path, params=None, raw=False):
        qs = ""
        if params:
            qs = "?" + urllib.parse.urlencode(params, doseq=True)
        return self.request("GET", path + qs, raw=raw)


def _unwrap(res):
    """Money S4 API 1.15.11 wraps every answer: {"PageCount","RowCount","Data":...,"Status":1,"Message","StackTrace"}.
    Status 1 -> return Data (REST list / GraphQL root object); any other status keeps the envelope (= error)."""
    if isinstance(res, dict) and "Status" in res and "Data" in res and res.get("Status") == 1:
        return res["Data"]
    return res


def _json(body):
    try:
        return json.loads(body.decode("utf-8-sig"))
    except Exception:
        try:
            return body.decode("utf-8", "replace")[:500]
        except Exception:
            return None


def shape(obj, show_values=False):
    """Field -> type map (values hidden unless allowed)."""
    if not isinstance(obj, dict):
        return type(obj).__name__
    out = {}
    for k, v in obj.items():
        if isinstance(v, list):
            out[k] = f"list[{len(v)}]"
        elif isinstance(v, dict):
            out[k] = "object"
        elif v is None:
            out[k] = "null"
        else:
            out[k] = type(v).__name__
            if show_values or k in SAFE_VALUE_FIELDS:
                out[k] += f" = {str(v)[:40]}"
    return out


def get_ci(obj, name):
    """Case-insensitive property access (camelCase JSON vs PascalCase DB names)."""
    if not isinstance(obj, dict):
        return None
    if name in obj:
        return obj[name]
    low = name.lower()
    for k, v in obj.items():
        if k.lower() == low:
            return v
    return None


def as_list(res):
    if isinstance(res, dict) and "Status" in res and isinstance(res.get("Data"), list):
        return res["Data"]  # Money S4 envelope
    return res if isinstance(res, list) else []


def norm(s):
    return re.sub(r"[\s/\-_.]", "", str(s or "")).lower()


def parse_date(v):
    if not v:
        return None
    try:
        return dt.datetime.fromisoformat(str(v)[:19]).date()
    except Exception:
        return None


# ----------------------------------------------------------------------------- steps
def get_token(http):
    if env("MONEY_TOKEN"):
        http.token = env("MONEY_TOKEN")
        return step("token", True, method="MONEY_TOKEN (pasted)", note="using pasted token")

    cid, secret = env("MONEY_CLIENT_ID"), env("MONEY_CLIENT_SECRET")
    if not (cid and secret):
        return step("token", False, note="set MONEY_CLIENT_ID + MONEY_CLIENT_SECRET or MONEY_TOKEN")

    candidates = []
    if env("MONEY_TOKEN_URL"):
        candidates.append(env("MONEY_TOKEN_URL"))
    candidates.append(http.base + "/connect/token")  # documented by Money (docs.moneyerp.com/developer/autorizace)
    # OpenID discovery
    status, _, disc, _ = http.request("GET", "/.well-known/openid-configuration")
    if status == 200 and isinstance(disc, dict) and disc.get("token_endpoint"):
        candidates.append(disc["token_endpoint"])
    for p in ("/connect/token", "/token", "/oauth/token", "/api/token", "/v1.0/token", "/oauth2/token"):
        candidates.append(http.base + p)

    tried = []
    for url in dict.fromkeys(candidates):
        for style in ("form", "basic"):
            form = {"grant_type": "client_credentials"}
            headers = {"Content-Type": "application/x-www-form-urlencoded"}
            if style == "form":
                form.update({"client_id": cid, "client_secret": secret})
            else:
                headers["Authorization"] = "Basic " + base64.b64encode(f"{cid}:{secret}".encode()).decode()
            form["scope"] = env("MONEY_SCOPE", "S5Api")
            status, ctype, body, ms = http.request("POST", url, data=urllib.parse.urlencode(form).encode(), headers=headers)
            tried.append({"url": url, "style": style, "status": status})
            if status == 200 and isinstance(body, dict) and body.get("access_token"):
                http.token = body["access_token"]
                return step("token", True, token_url=url, client_auth=style, expires_in=body.get("expires_in"),
                            token_type=body.get("token_type"), note=f"token from {url} ({style})")
    return step("token", False, tried=tried,
                note="no token endpoint worked - ask the Money implementer for the token URL, or paste MONEY_TOKEN")


def smoke(http, show):
    status, ctype, res, ms = http.get(f"{API}/IssuedInvoice/0/1")
    ok = status == 200 and isinstance(res, list)
    sample = res[0] if ok and res else None
    step("smoke GET REST /IssuedInvoice/0/1", ok, status=status, ms=ms, content_type=ctype,
         fields=len(sample) if isinstance(sample, dict) else None,
         note=f"HTTP {status}, {ms} ms" + ("" if ok else f", body type {type(res).__name__}, keys "
                                            f"{sorted(res)[:8] if isinstance(res, dict) else '-'}"))  # never values
    return sample


def page_limit(http):
    status, _, res, ms = http.get(f"{API}/IssuedInvoice")
    n = len(res) if isinstance(res, list) else None
    step("default page limit (GET /IssuedInvoice without paging)", status == 200, status=status, returned=n, ms=ms,
         note=f"returned {n} items in {ms} ms (likely DefaultPageLimit if this is a round number)")


def find_probe_invoice(http, number):
    """Find the probe invoice: GraphQL `CisloDokladu~eq~` -> REST detail by ID; fallback = scan the first pages
    (REST pages are oldest first - with 27 750 invoices a recent number was never reached, pilot 2026-10-31)."""
    target = norm(number)
    _, data, err, _ = gql(http, 'query($f:String){ IssuedInvoices(Filter:$f, Count:5){ ID CisloDokladu } }',
                          {"f": f"CisloDokladu~eq~{number}"})
    for row in (data or {}).get("IssuedInvoices") or []:
        if norm(row.get("CisloDokladu")) == target and row.get("ID"):
            status, _, res, _ = http.get(f"{API}/IssuedInvoice/{row['ID']}")
            if isinstance(res, list):
                res = res[0] if res else None
            if status == 200 and isinstance(res, dict):
                return res
    for start in range(0, 2000, 200):
        status, _, res, _ = http.get(f"{API}/IssuedInvoice/{start}/200")
        rows = as_list(res)
        for r in rows:
            if norm(get_ci(r, "cisloDokladu")) == target:
                return r
        if len(rows) < 200:
            break
    return None


FILTER_SYNTAXES = {
    "A_plain": lambda p, op, v: {"PropertyName": p, "Operation": op, "ExpectedValue": v},
    "B_filter_prefix": lambda p, op, v: {"filter.PropertyName": p, "filter.Operation": op, "filter.ExpectedValue": v},
    "C_filters_array": lambda p, op, v: {"LogicOperator": 0, "Filters[0].PropertyName": p,
                                          "Filters[0].Operation": op, "Filters[0].ExpectedValue": v},
    "D_filter_filters_array": lambda p, op, v: {"filter.LogicOperator": 0, "filter.Filters[0].PropertyName": p,
                                                 "filter.Filters[0].Operation": op,
                                                 "filter.Filters[0].ExpectedValue": v},
}


def detect_filter_syntax(http, number, baseline_count):
    results = {}
    winner = None
    for prop in ("CisloDokladu", "cisloDokladu"):
        for name, build in FILTER_SYNTAXES.items():
            for op in range(0, 9):
                params = build(prop, op, number)
                status, _, res, ms = http.get(f"{API}/IssuedInvoice/0/50", params)
                rows = as_list(res)
                exact = rows and all(norm(get_ci(r, "cisloDokladu")) == norm(number) for r in rows)
                key = f"{name}|{prop}|op{op}"
                results[key] = {"status": status, "count": len(rows), "all_equal": bool(exact)}
                if status == 200 and exact and len(rows) < max(baseline_count, 2):
                    winner = {"syntax": name, "property_case": prop, "eq_op_guess": op}
                    break
            if winner:
                break
        if winner:
            break
    step("filter syntax", bool(winner), winner=winner, tried=len(results),
         note=(f"works: {winner}" if winner else "no syntax returned only the probe invoice - see report.json"))
    report["filter_attempts"] = results
    return winner


def detect_ops(http, syntax, prop_case, number, inv):
    """Infer what ExpressionOperation codes 0-8 mean, using a string and a date property."""
    build = FILTER_SYNTAXES[syntax]
    pname = (lambda s: s) if prop_case[0].isupper() else (lambda s: s[0].lower() + s[1:])
    ops = {}
    n = str(number)
    subs = {"full": n, "prefix": n[: max(2, len(n) - 2)], "suffix": n[2:], "middle": n[1:-1] if len(n) > 3 else n}
    d0 = parse_date(get_ci(inv, "datumVystaveni"))
    for op in range(0, 9):
        info = {}
        for label, val in subs.items():
            status, _, res, _ = http.get(f"{API}/IssuedInvoice/0/50", build(pname("CisloDokladu"), op, val))
            rows = as_list(res)
            vals = [str(get_ci(r, "cisloDokladu") or "") for r in rows]
            info[label] = {
                "status": status, "count": len(rows),
                "eq": bool(vals) and all(v == val for v in vals),
                "contains": bool(vals) and all(val.lower() in v.lower() for v in vals),
                "starts": bool(vals) and all(v.lower().startswith(val.lower()) for v in vals),
                "ends": bool(vals) and all(v.lower().endswith(val.lower()) for v in vals),
                "none_eq": bool(vals) and all(v != val for v in vals),
            }
        if d0:
            dates = []
            for direction in (0, 1):  # both ends of the result set (default paging would hide e.g. ">=")
                params = build(pname("DatumVystaveni"), op, d0.isoformat())
                params.update({"OrderProperties[0].PropertyName": pname("DatumVystaveni"),
                               "OrderProperties[0].Direction": direction})
                status, _, res, _ = http.get(f"{API}/IssuedInvoice/0/50", params)
                dates += [parse_date(get_ci(r, "datumVystaveni")) for r in as_list(res)]
            dates = [x for x in dates if x]
            if dates:
                info["date"] = {
                    "count": len(dates),
                    "eq": sum(1 for x in dates if x == d0),
                    "gt": sum(1 for x in dates if x > d0),
                    "lt": sum(1 for x in dates if x < d0),
                }
            else:
                info["date"] = {"status": status, "count": 0}
        ops[op] = {"guess": guess_op(info), "evidence": info}
    report["operations"] = ops
    summary = ", ".join(f"{k}={v['guess']}" for k, v in ops.items())
    step("ExpressionOperation meaning (heuristic)", True, mapping={k: v["guess"] for k, v in ops.items()},
         note=summary)


def guess_op(info):
    f, p, s_, m = info["full"], info["prefix"], info["suffix"], info["middle"]
    d = info.get("date", {})
    n = d.get("count", 0)
    if n:
        eq, gt, lt = d["eq"], d["gt"], d["lt"]
        if gt == n:
            return "GreaterThan"
        if lt == n:
            return "LessThan"
        if eq and gt and not lt:
            return "GreaterThanOrEqual"
        if eq and lt and not gt:
            return "LessThanOrEqual"
        if gt and lt and not eq:
            return "NotEqual"
    # string evidence (CisloDokladu)
    if m.get("count") and m.get("contains") and not m.get("starts"):
        return "Contains"
    if p.get("count") and p.get("starts") and not m.get("count"):
        return "StartsWith"
    if s_.get("count") and s_.get("ends") and not p.get("count"):
        return "EndsWith"
    if f.get("eq") and not p.get("count") and not m.get("count"):
        return "Equal"
    if f.get("none_eq"):
        return "NotEqual"
    return "unknown"


def text_search(http, number):
    status, _, res, ms = http.get(f"{API}/IssuedInvoice/0/20", {"text": number, "propertyName": "CisloDokladu"})
    rows = as_list(res)
    hit = any(norm(get_ci(r, "cisloDokladu")) == norm(number) for r in rows)
    step("text search ?text=&propertyName=CisloDokladu", status == 200 and hit, status=status, count=len(rows),
         note=f"{len(rows)} results, probe invoice found: {hit}")


def projection(http):
    status, _, res, _ = http.get(f"{API}/IssuedInvoice/0/3", {"Properties": ["CisloDokladu", "DatumVystaveni", "ID"]})
    rows = as_list(res)
    nkeys = [len(r) for r in rows if isinstance(r, dict)]
    non_null = [sum(1 for v in r.values() if v not in (None, "", 0, False, [])) for r in rows if isinstance(r, dict)]
    step("Properties projection", status == 200, status=status, keys_per_row=nkeys, non_empty_per_row=non_null,
         note=f"keys per row {nkeys}, non-empty {non_null} (small numbers = projection works)")


def ordering(http):
    params = {"OrderProperties[0].PropertyName": "DatumVystaveni", "OrderProperties[0].Direction": 1}
    status, _, res, _ = http.get(f"{API}/IssuedInvoice/0/20", params)
    dates = [parse_date(get_ci(r, "datumVystaveni")) for r in as_list(res)]
    dates = [d for d in dates if d]
    desc = dates == sorted(dates, reverse=True) and len(set(dates)) > 1
    asc = dates == sorted(dates) and len(set(dates)) > 1
    step("OrderProperties (DatumVystaveni, Direction=1)", status == 200, status=status,
         result=("descending" if desc else "ascending" if asc else "unclear"),
         note=f"Direction=1 gives {'descending' if desc else 'ascending' if asc else 'unclear'} order")


def invoice_detail(http, inv, show):
    iid = get_ci(inv, "id")
    status, _, res, ms = http.get(f"{API}/IssuedInvoice/{iid}")
    ok = status == 200 and isinstance(res, dict)
    items = get_ci(res, "polozky") if ok else None
    item0 = items[0] if isinstance(items, list) and items else None
    report["issued_invoice_shape"] = shape(res, show) if ok else None
    report["issued_invoice_item_shape"] = shape(item0, show) if item0 else None
    content = get_ci(item0, "obsahPolozky") if item0 else None
    report["issued_invoice_item_content_shape"] = shape(content, show) if isinstance(content, dict) else None
    att = get_ci(res, "attachmentsList") if ok else None
    step("GET /IssuedInvoice/{id} detail", ok, status=status, ms=ms,
         items=len(items) if isinstance(items, list) else None,
         item_has_content=isinstance(content, dict),
         stock_nested=isinstance(get_ci(content, "zasoba"), dict) if isinstance(content, dict) else False,
         attachments=len(att) if isinstance(att, list) else None,
         note=f"items: {len(items) if isinstance(items, list) else 'n/a'}, attachmentsList: "
              f"{len(att) if isinstance(att, list) else 'n/a'}")
    return res if ok else None


def pdf_report(http, inv, save):
    rid = env("PROBE_REPORT_ID")
    if not rid:
        return step("PDF report", None, note="skipped - set PROBE_REPORT_ID (GUID of the print report or int config id)")
    iid = get_ci(inv, "id")
    params = {"reportDesignId": env("PROBE_REPORT_DESIGN_ID")} if env("PROBE_REPORT_DESIGN_ID") else None
    status, ctype, body, ms = http.get(f"{API}/IssuedInvoice/{iid}/Report/{rid}", params, raw=True)
    is_pdf = isinstance(body, (bytes, bytearray)) and body[:4] == b"%PDF"
    b64 = False
    if not is_pdf and isinstance(body, (bytes, bytearray)):
        try:  # maybe base64 or JSON-wrapped
            txt = body.decode("utf-8", "ignore").strip().strip('"')
            dec = base64.b64decode(txt[:4000] + "=" * (-len(txt[:4000]) % 4), validate=False)
            b64 = dec[:4] == b"%PDF"
        except Exception:
            pass
    if save and is_pdf:
        os.makedirs(OUT_DIR, exist_ok=True)
        with open(os.path.join(OUT_DIR, "probe_invoice.pdf"), "wb") as fh:
            fh.write(body)
    step("PDF report GET /IssuedInvoice/{id}/Report/{reportId}", is_pdf or b64, status=status, content_type=ctype,
         bytes=len(body) if isinstance(body, (bytes, bytearray)) else None, ms=ms,
         encoding="binary" if is_pdf else ("base64" if b64 else "unknown"),
         note=f"HTTP {status}, {ctype}, {'PDF ok' if is_pdf else 'base64 PDF' if b64 else 'not a PDF'} in {ms} ms")


def address_book(http, syntax, prop_case, eq_op, show):
    email = env("PROBE_EMAIL")
    if not email:
        return step("address book linkage", None, note="skipped - set PROBE_EMAIL")
    build = FILTER_SYNTAXES[syntax]
    pname = (lambda s: s) if prop_case[0].isupper() else (lambda s: s[0].lower() + s[1:])
    found = {}
    for res_name, prop in (("Person", "Email"), ("Company", "Email"), ("Connection", "SpojeniCislo")):
        status, _, res, _ = http.get(f"{API}/{res_name}/0/20", build(pname(prop), eq_op, email))
        rows = as_list(res)
        found[res_name] = {"status": status, "count": len(rows)}
        if rows:
            found[res_name]["first_shape"] = shape(rows[0], show)
            if res_name == "Person":
                parent = get_ci(rows[0], "parent_ID")
                st2, _, comp, _ = http.get(f"{API}/Company/{parent}") if parent else (0, "", None, 0)
                found["person_parent_is_company"] = st2 == 200 and isinstance(comp, dict) and bool(get_ci(comp, "id"))
            if res_name == "Connection":
                found["connection_has_firma_ID"] = bool(get_ci(rows[0], "firma_ID"))
    report["address_book"] = found
    step("address book linkage (Person/Company/Connection by e-mail)", any(v.get("count") for v in found.values()
                                                                          if isinstance(v, dict)),
         note=", ".join(f"{k}: {v['count'] if isinstance(v, dict) else v}" for k, v in found.items()))


def articles(http):
    q = env("PROBE_ARTICLE")
    if not q:
        return step("article search", None, note="skipped - set PROBE_ARTICLE")
    out = {}
    for prop in ("Kod", "Katalog", "Nazev"):
        status, _, res, ms = http.get(f"{API}/Article/0/20", {"text": q, "propertyName": prop})
        out[prop] = {"status": status, "count": len(as_list(res)), "ms": ms}
    report["article_search"] = out
    step("article search (text on Kod/Katalog/Nazev)", any(v["count"] for v in out.values()),
         note=", ".join(f"{k}: {v['count']}" for k, v in out.items()))


def received_invoices(http, show):
    status, _, res, _ = http.get(f"{API}/ReceivedInvoice/0/5")
    rows = as_list(res)
    filled = {}
    for f in ("puvodniDoklad", "variabilniSymbol", "bankovniSpojeniIBAN", "firma_ID", "ciselnaRada_ID",
              "druhDokladu_ID", "predkontace_ID", "cleneniDPH_ID", "mena_ID", "stredisko_ID", "zakazka_ID",
              "cinnost_ID", "zpusobPlatby_ID"):
        filled[f] = sum(1 for r in rows if get_ci(r, f))
    report["received_invoice_template_fields_filled"] = filled
    step("received invoices: template fields present", status == 200 and bool(rows), status=status,
         sample=len(rows), filled=filled,
         note=f"{len(rows)} sample rows; filled counts {filled}")


def codebooks(http):
    out = {}
    for r in ("Centre", "JobOrder", "Operation", "TypeOfActivity", "Staff", "Article", "Company", "Person",
              "ReceivedOrder", "IssuedOrder", "PrepaymentIssuedInvoice", "PrepaymentInvoice", "Activity",
              "BankStatement"):
        status, _, res, ms = http.get(f"{API}/{r}/0/5")
        out[r] = {"status": status, "sample": len(as_list(res)), "ms": ms}
    report["resources"] = out
    denied = [k for k, v in out.items() if v["status"] in (401, 403)]
    step("resource access (rights of the API role)", not denied, resources=out,
         note=("all readable" if not denied else f"no access: {', '.join(denied)}"))


# ----------------------------------------------------------------------------- GraphQL
def gql(http, query, variables=None):
    body = json.dumps({"query": query, "variables": variables or {}}).encode()
    status, ctype, res, ms = http.request("POST", "/graphql", data=body, headers={"Content-Type": "application/json"})
    if isinstance(res, dict) and "Status" in res and "data" not in res:
        # Money S4 envelope with an error status (OK envelopes are unwrapped in HttpClient.request)
        return status, None, [{"status": res.get("Status")}], ms
    if isinstance(res, dict) and status == 200 and "data" not in res and "errors" not in res:
        return status, res, None, ms  # unwrapped Money envelope: the root object itself
    data = res.get("data") if isinstance(res, dict) else None
    errors = res.get("errors") if isinstance(res, dict) else None
    return status, data, errors, ms


def gql_schema(http):
    saved = http.token
    http.token = None  # documented as available without authorization
    status, ctype, body, ms = http.request("GET", "/graphql/schema", raw=True)
    http.token = saved
    ok = status == 200 and isinstance(body, (bytes, bytearray)) and len(body) > 1000
    types, has_offer = None, None
    if ok:
        os.makedirs(OUT_DIR, exist_ok=True)
        with open(os.path.join(OUT_DIR, "graphql_schema_raw.txt"), "wb") as fh:
            fh.write(body)
        txt = body.decode("utf-8", "ignore")
        types = txt.count('"kind":"OBJECT"') + txt.count('"kind":"INPUT_OBJECT"')
        has_offer = "IssuedOffer" in txt
    step("GraphQL schema GET /graphql/schema", ok, status=status, bytes=len(body) if isinstance(body, (bytes, bytearray)) else None,
         issued_offer_available=has_offer,
         note=f"HTTP {status}; IssuedOffer (ponuky) in schema: {has_offer}")


def gql_basic(http):
    status, data, errors, ms = gql(http, "{ Version }")
    ok = status == 200 and bool(data) and not errors
    step("GraphQL { Version }", ok, status=status, version=(data or {}).get("Version"), ms=ms,
         note=f"API version {(data or {}).get('Version')}" if ok else f"HTTP {status} {str(errors)[:200]}")
    return ok


def gql_filters(http, number):
    out = {}
    def count(flt):
        st, data, err, _ = gql(http, 'query($f:String){ IssuedInvoices(Filter:$f, Count:50){ ID CisloDokladu DatumVystaveni } }', {"f": flt})
        rows = (data or {}).get("IssuedInvoices") or []
        return st, rows, err
    st, rows, err = count(f"CisloDokladu~eq~{number}")
    out["eq"] = {"count": len(rows), "error": bool(err)}
    inv = rows[0] if rows else None
    if inv:
        n = str(number)
        for op, val in (("ct", n[1:-1]), ("sw", n[:-2]), ("ew", n[2:])):
            st, r, err = count(f"CisloDokladu~{op}~{val}")
            out[op] = {"count": len(r), "error": bool(err), "probe_found": any(x.get("CisloDokladu") == n for x in r)}
        d = parse_date(inv.get("DatumVystaveni"))
        if d:
            for label, val in (("iso", d.isoformat()), ("sk", d.strftime("%d.%m.%Y")), ("iso_time", d.isoformat() + "T00:00:00")):
                st, r, err = count(f"DatumVystaveni~gte~{val}#DatumVystaveni~lte~{val}")
                out["date_" + label] = {"count": len(r), "error": bool(err), "probe_found": any(x.get("CisloDokladu") == n for x in r)}
        st, r, err = count(f"(CisloDokladu~eq~{n})|(CisloDokladu~eq~NEEXISTUJE-123)")
        out["or"] = {"count": len(r), "error": bool(err)}
    report["graphql_filters"] = out
    step("GraphQL filters (eq/ct/sw/ew, date formats, OR)", bool(inv), results=out,
         note=", ".join(f"{k}:{v.get('count')}{'!' if v.get('error') else ''}" for k, v in out.items()))


def gql_suppliers(http):
    st, data, err, _ = gql(http, "{ ArticleSuppliers(Count:50){ Parent_ID Firma_ID DodavatelskyKod Jednotka_ID PosledniCena } }")
    rows = (data or {}).get("ArticleSuppliers") or []
    with_code = [r for r in rows if r.get("DodavatelskyKod")]
    parent_is_article = None
    if rows and rows[0].get("Parent_ID"):
        st2, d2, e2, _ = gql(http, 'query($id:ID!){ Article(ID:$id){ ID Kod } }', {"id": rows[0]["Parent_ID"]})
        parent_is_article = bool((d2 or {}).get("Article"))
    step("ArticleSuppliers (kódy dodávateľov)", bool(rows) and not err, sample=len(rows), with_code=len(with_code),
         parent_is_article=parent_is_article,
         note=f"{len(rows)} rows, {len(with_code)} with DodavatelskyKod, Parent_ID = article: {parent_is_article}")


def gql_stock_prices(http):
    st, data, err, _ = gql(http, "{ WarehouseStocks(Count:5){ Artikl_ID Sklad_ID DostupneMnozstvi Rezervovano } }")
    rows = (data or {}).get("WarehouseStocks") or []
    step("WarehouseStocks (zásoby)", bool(rows) and not err, sample=len(rows), note=f"{len(rows)} rows, errors: {bool(err)}")
    ico = env("PROBE_COMPANY_ICO")
    if not ico:
        return step("ProdejniCeny (ceny zákazníka)", None, note="skipped - set PROBE_COMPANY_ICO")
    st, data, err, _ = gql(http, 'query($f:String){ Companies(Filter:$f, Count:1){ ID } }', {"f": f"ICO~eq~{ico}"})
    comp = ((data or {}).get("Companies") or [None])[0]
    if not comp:
        return step("ProdejniCeny (ceny zákazníka)", False, note="company with PROBE_COMPANY_ICO not found")
    st, data, err, ms = gql(http, 'query($id:Guid!){ ProdejniCeny(FirmaID:$id, Count:5){ ArtiklKod CenaBezDanePoSleve Sleva HladinaNazev ZustatekMnozstvi } }', {"id": comp["ID"]})
    rows = (data or {}).get("ProdejniCeny") or []
    step("ProdejniCeny (ceny zákazníka)", bool(rows) and not err, sample=len(rows), ms=ms,
         note=f"{len(rows)} prices in {ms} ms, errors: {str(err)[:120] if err else 'none'}")
    # #176: 0 rows without SkladID on the TEST agenda. Every branch price list has a default warehouse
    # (VychoziSklad_ID), so try once per warehouse (read-only, counts only).
    per_wh = {}
    whs = (gql(http, "{ Warehouses(Count:50){ ID Kod } }")[1] or {}).get("Warehouses") or []
    for wh in whs:
        _, d, e, _ = gql(http, 'query($id:Guid!,$s:Guid){ ProdejniCeny(FirmaID:$id, SkladID:$s, Count:5){ Artikl_ID } }',
                         {"id": comp["ID"], "s": wh["ID"]})
        per_wh[str(wh.get("Kod"))] = "error" if e else len((d or {}).get("ProdejniCeny") or [])
    step("ProdejniCeny with SkladID (per warehouse)", any(isinstance(v, int) and v for v in per_wh.values()),
         per_warehouse=per_wh, note=f"rows per warehouse code (max 5): {per_wh}")


def gql_documents(http):
    st, data, err, _ = gql(http, "{ ReceivedDeliveryNotes(Count:5){ ID Polozky{ ID Zbyva ObsahPolozky{ Artikl_ID Sklad_ID } } } }")
    rows = (data or {}).get("ReceivedDeliveryNotes") or []
    items = [i for r in rows for i in (r.get("Polozky") or [])]
    with_art = sum(1 for i in items if (i.get("ObsahPolozky") or {}).get("Artikl_ID"))
    step("ReceivedDeliveryNotes (dodacie listy prijaté)", not err, notes=len(rows), items=len(items), items_with_article=with_art,
         note=f"{len(rows)} notes, {with_art}/{len(items)} items with article")
    st, data, err, _ = gql(http, "{ ReceivedInvoices(Count:30){ ID Polozky{ ZdrojovaPolozkaKopirovani_ID ObsahPolozky{ Artikl_ID Sklad_ID } } } }")
    rows = (data or {}).get("ReceivedInvoices") or []
    items = [i for r in rows for i in (r.get("Polozky") or [])]
    linked = sum(1 for i in items if i.get("ZdrojovaPolozkaKopirovani_ID"))
    with_art = sum(1 for i in items if (i.get("ObsahPolozky") or {}).get("Artikl_ID"))
    step("ReceivedInvoices items (link to delivery note / stock)", not err, invoices=len(rows), items=len(items),
         linked_to_source=linked, items_with_article=with_art,
         note=f"{linked}/{len(items)} items linked to a source item, {with_art} with article (evidence for Mode A/B)")


# ----------------------------------------------------------------------------- customer orders (ORDERS_SPEC §19)
orders_report = {"generated_at": None, "read": {}, "write_test": None}


def mask(v):
    """Hide business values: digits -> 9, letters -> x/X (keeps the shape of strings like quantity discounts)."""
    if v is None:
        return None
    return re.sub(r"[a-záäčďéíĺľňóôŕšťúýž]", "x", re.sub(r"[A-ZÁÄČĎÉÍĹĽŇÓÔŔŠŤÚÝŽ]", "X", re.sub(r"\d", "9", str(v))))


def distinct(values):
    out = {}
    for v in values:
        out[str(v)] = out.get(str(v), 0) + 1
    return out


ORDER_FIELDS = """ID CisloDokladu Odkaz DatumVystaveni DatumVyrizeni Stav Vyrizeno PriznakVyrizeno Storno Faze
  ZpusobDopravy_ID ZpusobPlatby_ID CiselnaRada_ID Obchodnik_ID Osoba_ID DodaciAdresaNazev Firma_ID Mena_ID
  SumaZaklad SumaCelkem Poznamka
  Polozky { ID Nazev Mnozstvi MnozstviVyrizeno MnozstviZbyva JednCena Sleva TypCeny SazbaDPH_ID
            ObsahPolozky { Artikl_ID Sklad_ID PartnerskyKod Rezervovano Cenik_ID CenovaHladina_ID } }"""


def orders_read(http, show):
    r = orders_report["read"]
    st, data, err, ms = gql(http, "{ ReceivedOrders(Count:200){ %s } }" % ORDER_FIELDS)
    rows = (data or {}).get("ReceivedOrders") or []
    if err or not rows:
        step("ReceivedOrders (objednávky prijaté)", False if err else None, note=f"{len(rows)} rows, errors: {str(err)[:200] if err else 'none'}")
        r["orders"] = 0
        return []
    items = [i for o in rows for i in (o.get("Polozky") or [])]
    odkaz = [o.get("Odkaz") for o in rows if o.get("Odkaz")]
    r.update({
        "orders": len(rows), "items": len(items),
        "Stav": distinct(o.get("Stav") for o in rows), "Vyrizeno": distinct(o.get("Vyrizeno") for o in rows),
        "PriznakVyrizeno": distinct(o.get("PriznakVyrizeno") for o in rows), "Storno": distinct(o.get("Storno") for o in rows),
        "Faze": distinct(o.get("Faze") for o in rows), "TypCeny_items": distinct(i.get("TypCeny") for i in items),
        "orders_with_Odkaz": len(odkaz), "Odkaz_max_len": max((len(x) for x in odkaz), default=0),
        "orders_with_DatumVyrizeni": sum(1 for o in rows if o.get("DatumVyrizeni")),
        "orders_with_Obchodnik": sum(1 for o in rows if o.get("Obchodnik_ID")),
        "orders_with_Osoba": sum(1 for o in rows if o.get("Osoba_ID")),
        "orders_with_DodaciAdresa": sum(1 for o in rows if o.get("DodaciAdresaNazev")),
        "items_without_article": sum(1 for i in items if not (i.get("ObsahPolozky") or {}).get("Artikl_ID")),
        "items_with_PartnerskyKod": sum(1 for i in items if (i.get("ObsahPolozky") or {}).get("PartnerskyKod")),
        "items_with_Rezervovano": sum(1 for i in items if ((i.get("ObsahPolozky") or {}).get("Rezervovano") or 0) > 0),
        "items_with_Sleva": sum(1 for i in items if (i.get("Sleva") or 0) != 0),
        "items_with_price_list": sum(1 for i in items if (i.get("ObsahPolozky") or {}).get("Cenik_ID")),
        "items_partially_fulfilled": sum(1 for i in items if (i.get("MnozstviVyrizeno") or 0) > 0 and (i.get("MnozstviZbyva") or 0) > 0),
    })
    if show:
        r["odkaz_samples"] = odkaz[:5]
    step("ReceivedOrders (objednávky prijaté)", True, ms=ms,
         note=f"{len(rows)} orders, {len(items)} items; Stav {r['Stav']}; Vyrizeno {r['Vyrizeno']}; Odkaz max {r['Odkaz_max_len']} chars")
    # filter by Odkaz (customer PO) and by SMID marker
    if odkaz:
        st, d2, e2, _ = gql(http, 'query($f:String){ ReceivedOrders(Filter:$f, Count:5){ ID Odkaz } }', {"f": f"Odkaz~eq~{odkaz[0]}"})
        found = [x for x in (d2 or {}).get("ReceivedOrders") or [] if x.get("Odkaz") == odkaz[0]]
        r["filter_Odkaz_eq_works"] = bool(found) and not e2
        step("Filter ReceivedOrders Odkaz~eq~<PO>", bool(found) and not e2, note=f"found {len(found)}, errors: {bool(e2)}")
    st, d3, e3, _ = gql(http, 'query($f:String){ ReceivedOrders(Filter:$f, Count:5){ ID } }', {"f": "Poznamka~sw~SMID:"})
    r["filter_Poznamka_sw_works"] = not e3
    step("Filter ReceivedOrders Poznamka~sw~SMID:", not e3, note=f"{len((d3 or {}).get('ReceivedOrders') or [])} rows (expected 0 before go-live), errors: {bool(e3)}")
    return rows


def orders_links(http, orders):
    order_item_ids = {i.get("ID") for o in orders for i in (o.get("Polozky") or []) if i.get("ID")}
    st, data, err, _ = gql(http, "{ IssuedDeliveryNotes(Count:100){ ID Polozky { ZdrojovaPolozkaKopirovani_ID } } }")
    notes = (data or {}).get("IssuedDeliveryNotes") or []
    src = [i.get("ZdrojovaPolozkaKopirovani_ID") for n in notes for i in (n.get("Polozky") or []) if i.get("ZdrojovaPolozkaKopirovani_ID")]
    hits = sum(1 for x in src if x in order_item_ids)
    orders_report["read"]["delivery_note_items_linked_to_order_items"] = {"notes": len(notes), "items_with_source": len(src), "matching_order_items": hits}
    step("IssuedDeliveryNotes items -> ReceivedOrder items (ZdrojovaPolozkaKopirovani_ID)", not err,
         note=f"{len(src)} items with source id, {hits} point to items of the sampled orders")


def orders_codebooks_prices(http, show):
    r = orders_report["read"]
    for q in ("TransportTypes", "PaymentTypes"):
        st, data, err, _ = gql(http, "{ %s(Count:100){ ID Kod Nazev } }" % q)
        rows = (data or {}).get(q) or []
        r[q] = [{"Kod": x.get("Kod"), "Nazev": x.get("Nazev")} for x in rows]  # codebooks, not business data
        step(f"{q} (číselník)", not err, note=f"{len(rows)} values")
    st, data, err, _ = gql(http, "{ ArticleUnits(Count:300){ Kod Jednotka { Kod } DesetinnaMista NedelitelneMnozstvi Mnozstvi } }")
    rows = (data or {}).get("ArticleUnits") or []
    r["ArticleUnits_DesetinnaMista"] = distinct(((x.get("Jednotka") or {}).get("Kod") or x.get("Kod"), x.get("DesetinnaMista")) for x in rows)
    r["ArticleUnits_with_NedelitelneMnozstvi"] = sum(1 for x in rows if x.get("NedelitelneMnozstvi"))
    step("ArticleUnits (desatinné miesta, nedeliteľné množstvo)", not err, note=f"{len(rows)} units")
    ico = env("PROBE_ORDER_COMPANY_ICO") or env("PROBE_COMPANY_ICO")
    if not ico:
        return step("ProdejniCeny MnozstevniSleva / TypCeny", None, note="skipped - set PROBE_COMPANY_ICO")
    st, data, err, _ = gql(http, 'query($f:String){ Companies(Filter:$f, Count:1){ ID HodnotaSlevy VlastniSleva PouzivatKredit HodnotaKreditu } }', {"f": f"ICO~eq~{ico}"})
    comp = ((data or {}).get("Companies") or [None])[0]
    if not comp:
        return step("ProdejniCeny MnozstevniSleva / TypCeny", False, note="company not found")
    r["test_company_has_discount"] = bool(comp.get("HodnotaSlevy"))
    st, data, err, _ = gql(http, 'query($id:Guid!){ ProdejniCeny(FirmaID:$id, Count:200){ Artikl_ID CenaBezDane Sleva CenaBezDanePoSleve TypCeny MnozstevniSleva Zaokrouhleni Neaktivni MinimalniObjednavka } }', {"id": comp["ID"]})
    rows = (data or {}).get("ProdejniCeny") or []
    qd = [x.get("MnozstevniSleva") for x in rows if x.get("MnozstevniSleva")]
    r["ProdejniCeny"] = {"rows": len(rows), "TypCeny": distinct(x.get("TypCeny") for x in rows),
                         "with_MnozstevniSleva": len(qd),
                         "MnozstevniSleva_shapes": (qd[:5] if show else sorted({mask(x) for x in qd})[:10]),
                         "with_Sleva": sum(1 for x in rows if x.get("Sleva")),
                         "inactive": sum(1 for x in rows if x.get("Neaktivni"))}
    step("ProdejniCeny MnozstevniSleva / TypCeny", not err, note=f"{len(rows)} rows, {len(qd)} with quantity discount text")


def orders_write_test(http):
    """Creates test orders on the TEST agenda, reads them back and deletes them. Answers ORDERS_SPEC §19 write items."""
    w = orders_report["write_test"] = {"steps": []}
    if env("MONEY_AGENDA_LABEL") != "TEST":
        return step("Orders write test", None, note="refused - MONEY_AGENDA_LABEL must be TEST")
    try:
        typed = input("This creates and deletes test orders in Money. Type TEST to continue: ")
    except EOFError:
        typed = ""
    if typed.strip() != "TEST":
        return step("Orders write test", None, note="cancelled by user")
    ico, code = env("PROBE_ORDER_COMPANY_ICO"), env("PROBE_ORDER_ARTICLE_CODE")
    if not ico or not code:
        return step("Orders write test", None, note="set PROBE_ORDER_COMPANY_ICO and PROBE_ORDER_ARTICLE_CODE")
    st, d, e, _ = gql(http, 'query($f:String){ Companies(Filter:$f, Count:1){ ID HodnotaSlevy } }', {"f": f"ICO~eq~{ico}"})
    comp = ((d or {}).get("Companies") or [None])[0]
    st, d, e, _ = gql(http, 'query($f:String){ Articles(Filter:$f, Count:1){ ID Kod Nazev } }', {"f": f"Kod~eq~{code}"})
    art = ((d or {}).get("Articles") or [None])[0]
    if not comp or not art:
        return step("Orders write test", False, note="test company or article not found")
    st, d, e, _ = gql(http, 'query($f:String){ WarehouseStocks(Filter:$f, Count:10){ Sklad_ID Rezervovano DostupneMnozstvi } }', {"f": f"Artikl_ID~eq~{art['ID']}"})
    stocks = (d or {}).get("WarehouseStocks") or []
    if not stocks:
        return step("Orders write test", False, note="article has no stock record")
    wh = stocks[0]["Sklad_ID"]
    reserved_before = stocks[0].get("Rezervovano") or 0
    st, d, e, _ = gql(http, 'query($id:Guid!,$w:Guid,$f:String){ ProdejniCeny(FirmaID:$id, SkladID:$w, Filter:$f, Count:1){ CenaBezDane Sleva CenaBezDanePoSleve TypCeny Cenik_ID Hladina_ID } }',
                      {"id": comp["ID"], "w": wh, "f": f"Artikl_ID~eq~{art['ID']}"})
    price = ((d or {}).get("ProdejniCeny") or [None])[0]
    if not price:
        return step("Orders write test", False, note="no customer price for the article")
    smid = "SMID:PROBE-" + dt.datetime.now().strftime("%Y%m%d%H%M%S")
    sent_price = price.get("CenaBezDanePoSleve")

    def create(odkaz, with_text_line):
        items = [{"Nazev": art["Nazev"], "Mnozstvi": 1, "JednCena": sent_price, "Sleva": 0,
                  "ObsahPolozky": {"Artikl_ID": art["ID"], "Sklad_ID": wh, "Mnozstvi": 1,
                                   "Cenik_ID": price.get("Cenik_ID"), "CenovaHladina_ID": price.get("Hladina_ID"),
                                   "PartnerskyKod": "PROBE-CODE"}}]
        if with_text_line:
            items.append({"Nazev": "Smart Mail probe – textová položka", "Mnozstvi": 1, "JednCena": 0})
        order = {"Firma_ID": comp["ID"], "Odkaz": odkaz, "Poznamka": smid + " · Smart Mail probe – delete me",
                 "DatumVystaveni": dt.date.today().isoformat(), "Polozky": items}
        if env("PROBE_ORDER_SERIES_ID"):
            order["CiselnaRada_ID"] = env("PROBE_ORDER_SERIES_ID")
        return gql(http, "mutation($o: ReceivedOrderInput!){ CreateReceivedOrder(ReceivedOrder:$o){ ID CisloDokladu } }", {"o": order})

    def by_smid():
        st, d, e, _ = gql(http, 'query($f:String){ ReceivedOrders(Filter:$f, Count:10){ ID Odkaz } }', {"f": f"Poznamka~sw~{smid}"})
        return (d or {}).get("ReceivedOrders") or []

    created = []
    st, d, e, _ = create("SMPROBE-1", True)
    res = (d or {}).get("CreateReceivedOrder")
    w["text_line_supported"] = bool(res) and not e
    w["create_error_with_text_line"] = str(e)[:300] if e else None
    if not res:
        if by_smid():  # safety: never create twice
            res = {"ID": by_smid()[0]["ID"]}
        else:
            st, d, e, _ = create("SMPROBE-1", False)
            res = (d or {}).get("CreateReceivedOrder")
            w["create_error_without_text_line"] = str(e)[:300] if e else None
    if not res:
        step("Orders write test – create", False, note=f"create failed: {w.get('create_error_without_text_line') or w.get('create_error_with_text_line')}")
        return
    created.append(res["ID"])
    st, d, e, _ = gql(http, 'query($id:ID!){ ReceivedOrder(ID:$id){ %s } }' % ORDER_FIELDS, {"id": res["ID"]})
    back = (d or {}).get("ReceivedOrder") or {}
    it = next((i for i in back.get("Polozky") or [] if (i.get("ObsahPolozky") or {}).get("Artikl_ID")), {})
    w["sent_JednCena"] = "same as CenaBezDanePoSleve"
    w["readback_JednCena_equals_sent"] = (it.get("JednCena") == sent_price)
    w["readback_item_Sleva"] = it.get("Sleva")
    w["readback_TypCeny"] = it.get("TypCeny")
    w["customer_has_discount"] = bool(comp.get("HodnotaSlevy"))
    w["PartnerskyKod_stored"] = (it.get("ObsahPolozky") or {}).get("PartnerskyKod") == "PROBE-CODE"
    w["ORDER_PRICE_MODE_recommendation"] = "explicit_net" if w["readback_JednCena_equals_sent"] and not it.get("Sleva") else "base_plus_discount (check!)"
    st, d, e, _ = gql(http, 'query($f:String){ WarehouseStocks(Filter:$f, Count:10){ Sklad_ID Rezervovano } }', {"f": f"Artikl_ID~eq~{art['ID']}"})
    after = next((x for x in (d or {}).get("WarehouseStocks") or [] if x.get("Sklad_ID") == wh), {})
    w["reservation_delta"] = (after.get("Rezervovano") or 0) - reserved_before
    w["item_Rezervovano"] = (it.get("ObsahPolozky") or {}).get("Rezervovano")
    step("Orders write test – create + read-back", True,
         note=f"price kept: {w['readback_JednCena_equals_sent']}, item Sleva {w['readback_item_Sleva']}, reservation delta {w['reservation_delta']}, text line: {w['text_line_supported']}")
    # long Odkaz
    long_odkaz = "SMPROBE-LONG-" + "X" * 87
    st, d, e, _ = create(long_odkaz, False)
    res2 = (d or {}).get("CreateReceivedOrder")
    if res2:
        created.append(res2["ID"])
        st, d, e2, _ = gql(http, 'query($id:ID!){ ReceivedOrder(ID:$id){ Odkaz } }', {"id": res2["ID"]})
        stored = ((d or {}).get("ReceivedOrder") or {}).get("Odkaz") or ""
        w["Odkaz_100_chars"] = f"accepted, stored length {len(stored)}"
    else:
        w["Odkaz_100_chars"] = f"rejected: {str(e)[:200]}"
    # cleanup
    for oid in created:
        st, d, e, _ = gql(http, "mutation($id:ID!){ DeleteReceivedOrder(ID:$id) }", {"id": oid})
        w["steps"].append({"delete": oid, "ok": not e, "error": str(e)[:200] if e else None})
    left = by_smid()
    w["left_after_cleanup"] = len(left)
    step("Orders write test – cleanup (DeleteReceivedOrder)", not left, note=f"{len(created)} created, {len(left)} left (delete them manually if > 0)")


def write_orders_report():
    orders_report["generated_at"] = report["generated_at"]
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, "orders.json"), "w", encoding="utf-8") as fh:
        json.dump(orders_report, fh, ensure_ascii=False, indent=2, default=str)
    lines = ["# Money S4 probe – customer orders (ORDERS_SPEC §19)", "", f"Generated: {report['generated_at']}", "",
             "## Read-only findings", ""]
    for k, v in orders_report["read"].items():
        lines.append(f"- **{k}**: {json.dumps(v, ensure_ascii=False, default=str)}")
    lines += ["", "## Write test", ""]
    wt = orders_report.get("write_test")
    if wt:
        for k, v in wt.items():
            lines.append(f"- **{k}**: {json.dumps(v, ensure_ascii=False, default=str)}")
    else:
        lines.append("- not run (use --orders --allow-write-test on the TEST agenda)")
    lines += ["", "Give this file to Claude Code / Cursor before implementing customer orders (Phase 4).", ""]
    with open(os.path.join(OUT_DIR, "orders.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    print(f"Written {OUT_DIR}/orders.md and {OUT_DIR}/orders.json")


# ----------------------------------------------------------------------------- branches + received delivery notes
# Read-only. Answers DOCUMENTS_SPEC §8 / MONEY_API §9 questions 8-12 from existing documents:
# own numerical series per branch?  stredisko code == warehouse code?  Cenik_ID on received items?  time of stock
# movement?  vratky / vedlajsie naklady used?  which field holds "Doklad prijaty"?  Business values never leave the
# script: codebooks (Kod/Nazev of centres, warehouses, series, price lists) are listed, document values are counted.
branches_report = {"generated_at": None, "codebooks": {}, "delivery_notes": {}, "template_check": None}

DL_FIELDS = """ID CisloDokladu Odkaz Nazev ParovaciSymbol DatumVystaveni DatumUcetnihoPripadu DatumSkladovehoPohybu
  CasSkladovehoPohybu CiselnaRada_ID Stredisko_ID DruhPohybu_ID DruhSkladovehoPohybu_ID Predkontace_ID RegistraceDPH_ID
  ZapornyPohyb DodatecnePorizovaciNaklady IRozpousteniNakladu Sleva Poznamka Firma_ID
  Polozky { Nazev Katalog Mnozstvi TypCeny Vratka Stredisko_ID DruhPolozky_ID JednotkoveVedlejsiNaklady
            ObsahPolozky { Artikl_ID Sklad_ID Cenik_ID PartnerskyKod VazbaTypVazby } }"""


def branches_probe(http):
    cb = branches_report["codebooks"]
    names = {}
    for q, fields in (("Centres", "ID Kod Nazev"), ("Warehouses", "ID Kod Nazev"),
                      ("PriceLists", "ID Kod Nazev VychoziSklad_ID Neaktivni"), ("NumericalSeries", "ID Kod Nazev Prefix"),
                      ("AccountAssignments", "ID Kod Nazev")):
        st, data, err, _ = gql(http, "{ %s(Count:500){ %s } }" % (q, fields))
        rows = (data or {}).get(q) or []
        names.update({x["ID"]: f"{x.get('Kod')} {x.get('Nazev') or ''}".strip() for x in rows if x.get("ID")})
        cb[q] = [{k: v for k, v in x.items() if k != "ID"} for x in rows]   # codebooks, not business data
        step(f"{q} (číselník pre Nastavenia 11e)", not err, note=f"{len(rows)} values")
    wh_name = {x["ID"]: x.get("Kod") for x in ((gql(http, "{ Warehouses(Count:500){ ID Kod } }")[1] or {}).get("Warehouses") or [])}
    cb["PriceList_default_warehouse"] = {f"{p.get('Kod')}": wh_name.get(p.get("VychoziSklad_ID")) for p in
                                         ((gql(http, "{ PriceLists(Count:500){ Kod VychoziSklad_ID } }")[1] or {}).get("PriceLists") or [])}

    st, data, err, ms = gql(http, "{ ReceivedDeliveryNotes(Count:300){ %s } }" % DL_FIELDS)
    rows = (data or {}).get("ReceivedDeliveryNotes") or []
    r = branches_report["delivery_notes"]
    if err or not rows:
        return step("ReceivedDeliveryNotes (dodacie listy prijaté)", False if err else None, note=f"{len(rows)} rows, errors: {str(err)[:200] if err else 'none'}")
    items = [i for n in rows for i in (n.get("Polozky") or [])]
    series_by_centre, wh_by_centre = {}, {}
    for n in rows:
        c = names.get(n.get("Stredisko_ID"), "(bez strediska)")
        series_by_centre.setdefault(c, {}).setdefault(names.get(n.get("CiselnaRada_ID"), "?"), 0)
        series_by_centre[c][names.get(n.get("CiselnaRada_ID"), "?")] += 1
        for i in n.get("Polozky") or []:
            w = names.get((i.get("ObsahPolozky") or {}).get("Sklad_ID"), "?")
            wh_by_centre.setdefault(c, {}).setdefault(w, 0)
            wh_by_centre[c][w] += 1
    times = [str(n.get("CasSkladovehoPohybu") or "")[11:16] for n in rows if n.get("CasSkladovehoPohybu")]
    same_day = sum(1 for n in rows if str(n.get("DatumVystaveni"))[:10] == str(n.get("DatumSkladovehoPohybu"))[:10])
    first_item_name = sum(1 for n in rows if n.get("Polozky") and n.get("Nazev") == (n["Polozky"][0] or {}).get("Nazev"))
    r.update({
        "notes": len(rows), "items": len(items),
        "series_by_centre": series_by_centre,                       # answers: own series per branch?
        "warehouse_by_centre": wh_by_centre,                        # answers: stredisko == sklad?
        "items_Stredisko_equals_header": sum(1 for n in rows for i in (n.get("Polozky") or []) if i.get("Stredisko_ID") == n.get("Stredisko_ID")),
        "items_with_Cenik_ID": sum(1 for i in items if (i.get("ObsahPolozky") or {}).get("Cenik_ID")),
        "items_with_PartnerskyKod": sum(1 for i in items if (i.get("ObsahPolozky") or {}).get("PartnerskyKod")),
        "items_without_article": sum(1 for i in items if not (i.get("ObsahPolozky") or {}).get("Artikl_ID")),
        "TypCeny_items": distinct(i.get("TypCeny") for i in items),
        "VazbaTypVazby_items": distinct((i.get("ObsahPolozky") or {}).get("VazbaTypVazby") for i in items),
        "DruhPohybu_ID_distinct": len({n.get("DruhPohybu_ID") for n in rows}),
        "DruhSkladovehoPohybu_ID_distinct": len({n.get("DruhSkladovehoPohybu_ID") for n in rows}),
        "Predkontace": distinct(names.get(n.get("Predkontace_ID"), "?") for n in rows),
        "notes_with_Odkaz": sum(1 for n in rows if n.get("Odkaz")),
        "Odkaz_max_len": max((len(n["Odkaz"]) for n in rows if n.get("Odkaz")), default=0),
        "notes_with_ParovaciSymbol": sum(1 for n in rows if n.get("ParovaciSymbol")),
        "header_Nazev_equals_first_item": first_item_name,
        "stock_movement_same_day_as_issue": same_day,
        "stock_movement_times": distinct(times),                     # answers: real receipt time or fixed time?
        "notes_ZapornyPohyb": sum(1 for n in rows if n.get("ZapornyPohyb")),
        "items_Vratka": sum(1 for i in items if i.get("Vratka")),
        "items_negative_qty": sum(1 for i in items if (i.get("Mnozstvi") or 0) < 0),
        "notes_with_DodatecnePorizovaciNaklady": sum(1 for n in rows if (n.get("DodatecnePorizovaciNaklady") or 0) != 0),
        "items_with_vedlajsie_naklady": sum(1 for i in items if (i.get("JednotkoveVedlejsiNaklady") or 0) != 0),
        "notes_with_document_discount": sum(1 for n in rows if (n.get("Sleva") or 0) != 0),
    })
    step("ReceivedDeliveryNotes (dodacie listy prijaté)", True, ms=ms,
         note=f"{len(rows)} notes, {len(items)} items; series per centre: {len(series_by_centre)} centres; items with Cenik_ID {r['items_with_Cenik_ID']}")
    # optional: which field holds "Doklad prijatý"? (values compared here, never written to the report)
    number, expected = env("PROBE_DL_NUMBER"), env("PROBE_DL_DOKLAD_PRIJATY")
    if number and expected:
        st, d, e, _ = gql(http, 'query($f:String){ ReceivedDeliveryNotes(Filter:$f, Count:1){ Odkaz ParovaciSymbol Nazev } }', {"f": f"CisloDokladu~eq~{number}"})
        n = ((d or {}).get("ReceivedDeliveryNotes") or [None])[0] or {}
        branches_report["template_check"] = {"found": bool(n), "Odkaz_equals_Doklad_prijaty": n.get("Odkaz") == expected,
                                             "ParovaciSymbol_equals_Doklad_prijaty": n.get("ParovaciSymbol") == expected}
        step("Doklad prijatý -> Odkaz?", bool(n) and n.get("Odkaz") == expected, note=json.dumps(branches_report["template_check"]))


def write_branches_report():
    branches_report["generated_at"] = report["generated_at"]
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, "branches.json"), "w", encoding="utf-8") as fh:
        json.dump(branches_report, fh, ensure_ascii=False, indent=2, default=str)
    lines = ["# Money S4 probe – branches and received delivery notes (DOCUMENTS_SPEC §8)", "",
             f"Generated: {report['generated_at']}", "", "## Codebooks (Settings 11e dropdowns)", ""]
    for k, v in branches_report["codebooks"].items():
        lines.append(f"- **{k}**: {json.dumps(v, ensure_ascii=False, default=str)}")
    lines += ["", "## Received delivery notes (counts only)", ""]
    for k, v in branches_report["delivery_notes"].items():
        lines.append(f"- **{k}**: {json.dumps(v, ensure_ascii=False, default=str)}")
    lines += ["", f"- **template_check**: {json.dumps(branches_report['template_check'])}", "",
              "Give this file to Claude Code / Cursor before implementing branch values and received delivery notes.", ""]
    with open(os.path.join(OUT_DIR, "branches.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    print(f"Written {OUT_DIR}/branches.md and {OUT_DIR}/branches.json")


# ----------------------------------------------------------------------------- main
def write_report():
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, "report.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2, default=str)
    lines = ["# Money S4 API probe report", "", f"Generated: {report['generated_at']}", "",
             "| Step | Result | Note |", "|---|---|---|"]
    for s in report["steps"]:
        res = "OK" if s["ok"] else ("skipped" if s["ok"] is None else "FAILED")
        lines.append(f"| {s['step']} | {res} | {str(s.get('note', '')).replace('|', '/')} |")
    for key in ("operations",):
        if key in report:
            lines += ["", "## ExpressionOperation codes (heuristic guess)", ""]
            lines += [f"- {k}: {v['guess']}" for k, v in report[key].items()]
    lines += ["", "Full details: report.json (field names and types only, unless --show-values was used).", ""]
    with open(os.path.join(OUT_DIR, "report.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    print(f"\nWritten {OUT_DIR}/report.md and {OUT_DIR}/report.json")


def main():
    ap = argparse.ArgumentParser(description="Read-only probe of the Money S4 REST API")
    ap.add_argument("--env", help="path to probe.env")
    ap.add_argument("--save-pdf", action="store_true", help="save the generated PDF to probe_output/")
    ap.add_argument("--show-values", action="store_true", help="include data values in the report (do not share!)")
    ap.add_argument("--orders", action="store_true", help="probe customer orders (ORDERS_SPEC §19) -> probe_output/orders.md")
    ap.add_argument("--allow-write-test", action="store_true",
                    help="with --orders: create, read back and delete test orders (TEST agenda only, asks for confirmation)")
    ap.add_argument("--branches", action="store_true",
                    help="read-only: centres, warehouses, price lists, series and received delivery notes -> probe_output/branches.md")
    args = ap.parse_args()
    load_env(args.env)

    global API
    API = "/" + env("MONEY_REST_VERSION", "v2.0").strip("/")
    base = env("MONEY_BASE_URL")
    if not base:
        sys.exit("MONEY_BASE_URL is not set (see the header of this script)")
    http = Http(base, insecure=env("MONEY_INSECURE") == "1")
    report["base_url"] = base

    tok = get_token(http)
    if not tok["ok"]:
        write_report()
        sys.exit(1)

    gql_schema(http)
    if args.branches:
        if gql_basic(http):
            branches_probe(http)
        write_branches_report()  # report.md of the base run is kept (pilot 2026-10-31: it was overwritten)
        return
    if args.orders:
        if gql_basic(http):
            orders = orders_read(http, args.show_values)
            orders_links(http, orders)
            orders_codebooks_prices(http, args.show_values)
            if args.allow_write_test:
                orders_write_test(http)
        write_orders_report()  # report.md of the base run is kept
        return
    if gql_basic(http):
        if env("PROBE_INVOICE_NUMBER"):
            gql_filters(http, env("PROBE_INVOICE_NUMBER"))
        gql_suppliers(http)
        gql_stock_prices(http)
        gql_documents(http)

    sample = smoke(http, args.show_values)
    if sample is None:
        write_report()
        sys.exit(1)
    report["issued_invoice_list_shape"] = shape(sample, args.show_values)
    page_limit(http)
    codebooks(http)

    number = env("PROBE_INVOICE_NUMBER")
    inv = find_probe_invoice(http, number) if number else None
    step("probe invoice found by paging", bool(inv), note=(f"{number}" if inv else f"{number} not found in first pages"))
    if inv:
        status, _, res, _ = http.get(f"{API}/IssuedInvoice/0/50")
        baseline = len(as_list(res))
        win = detect_filter_syntax(http, number, baseline)
        if win:
            detect_ops(http, win["syntax"], win["property_case"], number, inv)
            address_book(http, win["syntax"], win["property_case"], win["eq_op_guess"], args.show_values)
        text_search(http, number)
        projection(http)
        ordering(http)
        invoice_detail(http, inv, args.show_values)
        pdf_report(http, inv, args.save_pdf)
    articles(http)
    received_invoices(http, args.show_values)
    write_report()


if __name__ == "__main__":
    main()
