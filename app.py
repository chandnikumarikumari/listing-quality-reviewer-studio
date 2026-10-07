import csv, difflib, io, json, os, re, sqlite3, time, urllib.request
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path
from flask import Flask, Response, jsonify, request, render_template

BASE = Path(__file__).parent
CATEGORIES = {"Electronics": ["brand", "condition"], "Clothing": ["size", "condition"],
              "Home": ["condition", "material"], "Books": ["condition", "author"],
              "Services": ["duration"]}
REQUIRED = ["title", "description", "category", "price", "seller"]
TITLE_MAX, DESC_MIN, DESC_MAX = 80, 40, 1000
app = Flask(__name__)

def db():
    c = sqlite3.connect(BASE / "reviews.db"); c.row_factory = sqlite3.Row; return c

with db() as c:
    c.executescript("""
    CREATE TABLE IF NOT EXISTS listings(id INTEGER PRIMARY KEY, original TEXT, revised TEXT,
        validation TEXT, findings TEXT);
    CREATE TABLE IF NOT EXISTS history(id INTEGER PRIMARY KEY, listing_id INT, ts TEXT,
        field TEXT, action TEXT, old TEXT, new TEXT);""")

# ---------- 1. Policy retrieval (keyword overlap over policy.md sections) ----------
def load_policy():
    out = []
    for block in re.split(r"^## ", (BASE / "policy.md").read_text(encoding="utf-8"), flags=re.M)[1:]:
        head, _, body = block.partition("\n"); pid, _, title = head.partition(" ")
        out.append({"id": pid, "title": title.strip(), "text": body.strip()})
    return out
POLICY = load_policy()
tok = lambda s: re.findall(r"[a-z]+", s.lower())

def retrieve(query):
    q = Counter(tok(query))
    def score(s):
        t = Counter(tok(s["title"] + " " + s["text"])); return sum(min(q[w], t[w]) for w in q)
    return max(POLICY, key=score)

# ---------- 2. AI-style analysis: (regex, kind, severity, retrieval query, explanation, replacement) ----------
RULES = [
 (r"\b\d{10}\b|\+\d[\d\s-]{9,}|\b[\w.]+@[\w.]+\.\w+\b|whatsapp|call me|dm me", "prohibited", "high",
  "off-platform contact details phone email whatsapp", "Phone numbers, emails or off-platform contact are not allowed in listings.", ""),
 (r"\b(cheapest|lowest price|dirt cheap|best price)\b", "misleading", "medium",
  "price comparison claims cheapest lowest price", "Price-superiority claims cannot be verified.", ""),
 (r"\b(buy now|hurry|limited stock|act fast)\b", "unclear", "low",
  "pushy sales language urgency brand voice", "Pushy urgency language breaks the brand voice; keep a calm, factual tone.", ""),
 (r"\b(replica|counterfeit|knock-?off|fake)\b", "prohibited", "critical",
  "prohibited counterfeit replica goods", "Counterfeit-type goods are not allowed.", None),
 (r"\b(cures?|miracle|guaranteed results?)\b", "misleading", "high",
  "misleading health claims miracle guaranteed", "Health/outcome guarantees are misleading.", ""),
 (r"\b(best in the world|#1|number one|100% (?:safe|guaranteed|authentic))\b", "unverifiable", "medium",
  "unverifiable superlative claims need evidence", "Claim cannot be verified from the listing.", ""),
 (r"\b(authentic|genuine|original|brand new)\b", "unverifiable", "low",
  "authenticity genuine original claims need proof", "Assumption: seller must be able to prove this.", None),
 (r"\b(good quality|nice|amazing|great product)\b", "unclear", "low",
  "vague wording replace with specific details", "Vague wording; add measurable details (material, size, performance).", None),
 (r"!{2,}", "unclear", "low", "title repeated exclamation marks", "Repeated punctuation looks spammy.", "!"),
]
CAPS = re.compile(r"\b[A-Z]{5,}\b")

def analyze(l):
    findings = []
    def add(field, m, kind, sev, query, why, to):
        p = retrieve(query)
        findings.append({"field": field, "from": m, "to": to, "kind": kind, "severity": sev,
                         "explanation": why, "policy": f'{p["id"]} {p["title"]}',
                         "policy_text": p["text"], "status": "open"})
    for field in ("title", "description"):
        text = str(l.get(field, ""))
        for rx, kind, sev, q, why, to in RULES:
            for m in re.finditer(rx, text, flags=re.I):
                add(field, m.group(), kind, sev, q, why, to)
        for m in CAPS.finditer(text):
            add(field, m.group(), "unclear", "low", "title ALL CAPS capitalization", "ALL CAPS reads as shouting.", m.group().capitalize())
    attrs = {k.lower(): v for k, v in (l.get("attributes") or {}).items() if str(v).strip()}
    for a in CATEGORIES.get(l.get("category"), []):
        if a not in attrs:
            add("attributes", a, "incomplete", "medium", "required attributes per category missing",
                f'Missing required attribute "{a}" for {l["category"]}.', None)
    return findings + llm_analyze(l)

SEV = {"critical", "high", "medium", "low"}
KINDS = {"prohibited", "misleading", "unclear", "incomplete", "unverifiable"}

def llm_analyze(l):
    """Optional: Claude reviews the listing using only the top policy sections.
    Guardrails: output must cite a real policy id and quote text that exists in the field."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key: return []
    q = Counter(tok(f'{l.get("title","")} {l.get("description","")} {l.get("category","")}'))
    top = sorted(POLICY, key=lambda s: -sum(min(q[w], c) for w, c in Counter(tok(s["text"])).items()))[:4]
    pol = "\n".join(f'{s["id"]} {s["title"]}: {s["text"]}' for s in top)
    prompt = (f"Marketplace policy:\n{pol}\n\nListing JSON:\n{json.dumps(l)}\n\nFind policy problems in title/description. "
              'Reply ONLY with a JSON array of {"field":"title|description","quote":"exact text from the field",'
              '"kind":"prohibited|misleading|unclear|incomplete|unverifiable","severity":"critical|high|medium|low",'
              '"policy_id":"P#","explanation":"...","suggestion":"replacement for quote"}. Use [] if none. Do not invent facts.')
    try:
        req = urllib.request.Request("https://api.anthropic.com/v1/messages", headers={
            "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            data=json.dumps({"model": os.environ.get("CLAUDE_MODEL", "claude-sonnet-5-5"), "max_tokens": 1000,
                             "messages": [{"role": "user", "content": prompt}]}).encode())
        txt = json.load(urllib.request.urlopen(req, timeout=40))["content"][0]["text"]
        items = json.loads(re.search(r"\[.*\]", txt, re.S).group())
    except Exception as e:
        print("AI analysis skipped:", e); return []
    ids, out = {s["id"]: s for s in POLICY}, []
    for it in items:
        p = ids.get(it.get("policy_id")); f = it.get("field"); qt = it.get("quote", "")
        if not p or f not in ("title", "description") or not qt or qt not in str(l.get(f, "")): continue
        out.append({"field": f, "from": qt, "to": it.get("suggestion"), "kind": it.get("kind") if it.get("kind") in KINDS else "unclear",
                    "severity": it.get("severity") if it.get("severity") in SEV else "low", "explanation": it.get("explanation", ""),
                    "policy": f'{p["id"]} {p["title"]}', "policy_text": p["text"], "status": "open", "source": "AI"})
    return out

# ---------- 3. Deterministic validation ----------
def validate(l, seen):
    e = []
    for f in REQUIRED:
        if not str(l.get(f, "")).strip(): e.append(f"Missing required field: {f}")
    p = str(l.get("price", "")).replace("\u20b9", "").replace(",", "").strip()
    if p:
        try:
            if not re.fullmatch(r"\d+(\.\d{1,2})?", p) or Decimal(p) <= 0: raise InvalidOperation
        except InvalidOperation: e.append("Price must be a positive number with max 2 decimals")
    if l.get("category") and l["category"] not in CATEGORIES:
        e.append(f'Unsupported category "{l["category"]}". Use: {", ".join(CATEGORIES)}')
    if len(str(l.get("title", ""))) > TITLE_MAX: e.append(f"Title longer than {TITLE_MAX} chars")
    n = len(str(l.get("description", "")))
    if l.get("description") and not DESC_MIN <= n <= DESC_MAX:
        e.append(f"Description length {n} not in {DESC_MIN}-{DESC_MAX}")
    key = (str(l.get("title", "")).strip().lower(), str(l.get("seller", "")).strip().lower())
    for t, s in seen:
        if s == key[1] and difflib.SequenceMatcher(None, t, key[0]).ratio() >= 0.9:
            e.append("Duplicate or near-duplicate listing (similar title, same seller)"); break
    seen.add(key); return e

# ---------- API ----------
def existing_keys():
    with db() as c:
        return {(o["title"].strip().lower(), o["seller"].strip().lower()) for o in
                (json.loads(r["original"]) for r in c.execute("SELECT original FROM listings"))
                if o.get("title") and o.get("seller")}

@app.get("/api/config")
def config(): return jsonify(categories=CATEGORIES, title_max=TITLE_MAX, desc_min=DESC_MIN, desc_max=DESC_MAX)

@app.get("/")
def home(): return render_template("index.html")

@app.post("/api/batch")
def batch(): return jsonify(ingest(request.json["listings"]))

def ingest(items):
    seen, ids = existing_keys(), []
    with db() as c:
        for l in items:
            errs = validate(l, seen)
            cur = c.execute("INSERT INTO listings(original,revised,validation,findings) VALUES(?,?,?,?)",
                (json.dumps(l), json.dumps(l), json.dumps(errs), json.dumps(analyze(l))))
            ids.append(cur.lastrowid)
    return ids

PEN = {"critical": 40, "high": 25, "medium": 10, "low": 3}

def row(r):
    errs, fs = json.loads(r["validation"]), json.loads(r["findings"])
    score = max(0, 100 - 15 * len(errs) - sum(PEN[f["severity"]] for f in fs if f["status"] != "rejected"))
    openf = [f for f in fs if f["status"] == "open"]
    if errs or any(f["severity"] in ("critical", "high") and f["status"] != "approved" for f in fs if f["status"] != "edited"):
        decision = "Blocked"
    else:
        decision = "Needs review" if openf else "Ready to publish"
    return {"id": r["id"], "original": json.loads(r["original"]), "revised": json.loads(r["revised"]),
            "errors": errs, "findings": fs, "score": score, "decision": decision}

@app.post("/api/import-csv")
def import_csv():
    items = []
    for d in csv.DictReader(io.StringIO(request.get_data(as_text=True))):
        attrs = dict(kv.split("=", 1) for kv in (d.get("attributes") or "").split(";") if "=" in kv)
        items.append({**{k: (d.get(k) or "").strip() for k in ("title", "description", "category", "price", "seller")},
                      "attributes": attrs, "tags": [t for t in (d.get("tags") or "").split(";") if t]})
    return jsonify(ingest(items))

@app.get("/api/export.csv")
def export_csv():
    out = io.StringIO(); w = csv.writer(out)
    w.writerow(["id", "decision", "score", "seller", "category", "price", "original_title", "revised_title", "original_description", "revised_description"])
    with db() as c:
        for r in map(row, c.execute("SELECT * FROM listings ORDER BY id")):
            o, v = r["original"], r["revised"]
            w.writerow([r["id"], r["decision"], r["score"], o.get("seller"), o.get("category"), o.get("price"),
                        o.get("title"), v.get("title"), o.get("description"), v.get("description")])
    return Response(out.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=reviewed_listings.csv"})

@app.get("/api/listings")
def listings():
    with db() as c: return jsonify([row(r) for r in c.execute("SELECT * FROM listings ORDER BY id DESC")])

@app.post("/api/listings/<int:i>/decide")
def decide(i):
    d = request.json
    with db() as c:
        r = row(c.execute("SELECT * FROM listings WHERE id=?", (i,)).fetchone())
        f = r["findings"][d["finding"]]; field = f["field"]; rev = r["revised"]
        old = str(rev.get(field, "")) if field != "attributes" else ""
        if d["action"] == "approve" and f["to"] is not None and field != "attributes":
            rev[field] = old.replace(f["from"], f["to"], 1)
        elif d["action"] == "edit" and field != "attributes":
            rev[field] = d["value"]
        f["status"] = {"approve": "approved", "reject": "rejected", "edit": "edited"}[d["action"]]
        c.execute("UPDATE listings SET revised=?, findings=? WHERE id=?", (json.dumps(rev), json.dumps(r["findings"]), i))
        c.execute("INSERT INTO history(listing_id,ts,field,action,old,new) VALUES(?,?,?,?,?,?)",
                  (i, time.strftime("%Y-%m-%d %H:%M:%S"), field, d["action"], old, str(rev.get(field, ""))))
    return jsonify(ok=True)

@app.get("/api/history")
def history():
    with db() as c: return jsonify([dict(r) for r in c.execute("SELECT * FROM history ORDER BY id DESC LIMIT 100")])

if __name__ == "__main__":
    app.run(debug=True)
