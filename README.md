# Marketplace Listing Quality Reviewer

A review workbench that checks product/service listings against a marketplace policy, explains every problem with a cited policy section, suggests better wording, and lets a human reviewer approve, edit or reject each change, with a full audit trail.

It mirrors how trust & safety / catalog-quality teams work at real marketplaces: **automated checks first, human decision last, everything logged.**

---

## 1. The problem it solves

Sellers write messy listings: ALL CAPS titles, "100% authentic!!!", health miracles, missing attributes, duplicates, bad prices. Reviewing these by hand is slow and inconsistent. This tool:

1. Catches hard errors automatically (deterministic validation).
2. Finds softer content problems (AI-style analysis) and ties each one to the exact policy rule it breaks.
3. Proposes a fix, but never applies it without a human decision.
4. Records who decided what, when, and what changed.

## 2. Features

| Area | What it does |
|---|---|
| Listing fields | Title, description, category, price, attributes, seller, optional tags |
| Policy retrieval | Finds the most relevant policy section for each finding and cites it (ID, title, text) |
| Content analysis | Flags **prohibited, misleading, unclear, incomplete, unverifiable** content with **critical / high / medium / low** severity |
| Suggested wording | Proposes a replacement for the flagged text |
| Assumptions | Authenticity/"brand new"/superlative claims are flagged as unverifiable assumptions |
| Deterministic validation | Required fields, price format, supported categories, title/description length, duplicate and near-duplicate detection |
| Review actions | Approve, Edit or Reject each finding, field by field |
| Compare | Original vs revised title/description side by side |
| Batch | Paste JSON or upload CSV with many listings |
| Score and decision | Quality score (0-100) and a decision: Blocked / Needs review / Ready to publish |
| History | Every action stored with timestamp, field, old value, new value |
| Export | Download reviewed listings as CSV |
| Optional AI | Claude reviews listings too, with guardrails |

Not included on purpose: publishing to a real marketplace, image moderation, payments, seller verification, unrestricted categories.

## 3. Architecture

```
 Browser (HTML + JavaScript)
      |  fetch() JSON / CSV
      v
 Flask web server (app.py)
      |
      |-- 1. Ingest: parse JSON or CSV
      |-- 2. Deterministic validation  -> errors
      |-- 3. Policy retrieval          -> policy.md sections
      |-- 4. Analysis
      |        |- rule engine (regex)        -> findings
      |        '- optional Claude API call   -> findings (guard-railed)
      |-- 5. Save to SQLite (reviews.db)
      '-- 6. Review actions -> update revised text + write history
```

### Request flow for one listing

1. The listing arrives (batch JSON or CSV row).
2. **Validation** runs and produces errors (missing field, bad price, duplicate...).
3. **Analysis** scans title and description. For each match, **retrieval** picks the best policy section by keyword overlap, and that section becomes the citation.
4. If `ANTHROPIC_API_KEY` is set, Claude also reviews the listing using only the top 4 matching policy sections. Its findings are discarded unless they cite a real policy ID and quote text that exists in the listing.
5. The original, an editable "revised" copy, the errors and the findings are saved.
6. The reviewer works through the findings; each decision updates the revised text and appends a history row.

## 4. Technology and tools

| Tool | Used for | Why |
|---|---|---|
| Python 3.11 | Whole backend | Simple, readable, great for text processing |
| Flask | Web server and JSON API | Small and easy to learn; no heavy setup |
| SQLite (`sqlite3`, built in) | Storage for listings and history | Zero install, a single file, perfect for local projects |
| HTML + vanilla JavaScript | User interface | No build step, so it runs anywhere |
| `re` (regex) | Rule-based content detection | Transparent and testable |
| `difflib` | Near-duplicate detection | Standard library, string-similarity score |
| `csv`, `io` | CSV import/export | Standard library |
| Claude API (optional) | Deeper language review | Catches nuance regex cannot |
| pytest | Automated tests | Proves validation logic works |
| VS Code + PowerShell | Development on Windows | Free, common tools |

Only one third-party package is required: **Flask**.

## 5. Project structure

```
listing-reviewer/
|-- app.py                  # backend: validation, retrieval, analysis, API
|-- policy.md               # marketplace policy (P1-P7), the knowledge source
|-- requirements.txt        # Python dependencies
|-- templates/
|   '-- index.html          # the whole UI
|-- tests/
|   '-- test_validation.py  # pytest tests
|-- README.md
'-- reviews.db              # created on first run (SQLite)
```

## 6. How each part works

### Policy retrieval
`policy.md` is split into sections (`## P1 Prohibited items`, ...). A finding's description is turned into words and compared with each section; the section with the highest word overlap wins and is cited. This is a simple, explainable retrieval step (a real system would use embeddings and a vector database, see Roadmap).

### Deterministic validation (always the same result for the same input)
- Required: title, description, category, price, seller
- Price: positive number, at most 2 decimals (`12.99` ok, `abc` or `0` rejected)
- Category: Electronics, Clothing, Home, Books, Services
- Title at most 80 characters; description 40-1000 characters
- Duplicates: same seller and title similarity of 90% or more (in the batch or already stored)

### Content analysis categories
| Kind | Example | Policy |
|---|---|---|
| prohibited | "replica", "counterfeit" | P1 |
| misleading | "miracle", "cures", "guaranteed results" | P2 |
| unverifiable | "100% authentic", "best in the world", "genuine" | P3 |
| unclear | ALL CAPS, "!!!", "nice", "amazing" | P4, P5 |
| incomplete | missing category-required attribute | P6 |

### Score and decision
- Score = 100 minus 15 per validation error minus severity penalties (critical 40, high 25, medium 10, low 3). Rejected findings do not count.
- **Blocked**: has validation errors, or has a critical/high finding that is neither approved nor edited.
- **Needs review**: findings still open.
- **Ready to publish**: no errors, nothing unresolved.

### AI guardrails (optional Claude step)
- Only the most relevant policy sections are sent, not the whole policy.
- Response must be strict JSON.
- Finding is dropped if the policy ID does not exist or the quoted text is not really in the listing, which prevents invented rules and hallucinated quotes.
- Any API failure is ignored and the rule engine still works.

## 7. Data model (SQLite)

```
listings(id, original, revised, validation, findings)   -- JSON text columns
history(id, listing_id, ts, field, action, old, new)
```

## 8. API

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/batch` | Submit `{"listings":[...]}` |
| POST | `/api/import-csv` | Submit CSV text |
| GET | `/api/listings` | All listings with findings, score, decision |
| POST | `/api/listings/<id>/decide` | `{finding, action: approve/edit/reject, value}` |
| GET | `/api/history` | Latest 100 history entries |
| GET | `/api/export.csv` | Download reviewed listings |

## 9. Run it on Windows

```powershell
cd listing-reviewer
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python app.py
```
Open http://127.0.0.1:5000 and click **Review batch**. Stop with `Ctrl + C`.

Tests: `pip install pytest` then `pytest`.

Optional Claude analysis (same PowerShell window, before `python app.py`):
```powershell
$env:ANTHROPIC_API_KEY="your-key"
```
Optional model override: `$env:CLAUDE_MODEL="model-name"`.

CSV format: `title,description,category,price,seller,tags,attributes` with attributes written as `brand=Acme;condition=new` and tags separated by `;`.

## 10. Sample walkthrough

Input: *"BEST iPhone case!!!"* / *"Nice case, 100% authentic and amazing quality"*, category Electronics, attributes `{brand: Acme}`.

Findings: ALL CAPS (P4, low) -> "Best"; "!!!" (P4, low) -> "!"; "100% authentic" (P3, medium, unverifiable); "Nice"/"amazing" (P5, low, unclear); missing attribute `condition` (P6, medium, incomplete).
The reviewer approves the title fixes, edits the description, and rejects one suggestion. The history logs each action, and the decision moves from Needs review to Ready to publish.

## 11. Limitations (honest)

- No user accounts: history does not record *who* decided.
- Retrieval is keyword-based, not semantic.
- Rules are English-only and regex-driven; they miss creative wording.
- SQLite and the Flask dev server are fine for a demo, not high traffic.
- Edits apply to title and description; attributes are flagged but not editable in the UI.

## 12. Roadmap to production

1. Login and reviewer roles; store reviewer name in history.
2. Embeddings plus a vector store for true semantic policy retrieval.
3. PostgreSQL, background job queue for large batches.
4. Per-category policy files and policy versioning.
5. Reviewer analytics: approval rate, top violation types, time to review.
6. Evaluation set: labelled listings to measure precision/recall of the analyzer.
7. Docker packaging and CI running pytest on every commit.

## Update: form-based studio UI
- **Review tab:** a real input form (title with live counter, description, category, price in rupees, category-specific required attribute fields, seller, tags) with Load sample / Clear. Submitting stores the listing, findings and score in the SQLite backend.
- **Results panel:** score ring, decision badge, validation errors, an "Assumptions & unverifiable claims" box, original vs revised, and finding cards with Approve / Edit / Reject.
- **Batch tab:** paste JSON or upload CSV, see all scores and decisions, export a CSV.
- **History tab:** every past listing and every approval action.
- **Brand-content guide:** `policy.md` now also holds P8 (no off-platform contact) and B1-B3 (brand voice, price claims, title pattern), enforced by new rules and cited in findings.
- **API:** `GET /api/config` supplies categories and limits to the form.
