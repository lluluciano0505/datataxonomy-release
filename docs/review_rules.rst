Review rules
============

Scope
-----
This implementation detects missing recorded reading evidence, classification
uncertainty, and conflicts between output fields and existing heuristics. A rule
trigger is not a verified error. It does not validate the factual accuracy of
summaries or the correctness of Layer 3 grades. Evidence-grounded checking of
invented locations, dates and technical requirements is NOT implemented.

Actual data path
----------------
Layer 1 returns final content_sample, extraction_method and extraction_coverage.
Its PDF visual failure can fall back to text; image failures can fall back to OCR.
Its CAD fallback can return filename/binary-header placeholders, not source content.
Layer 2 can additionally return _vlm and _prescreen. Prior versions promoted Low
classification certainty using visual recognition confidence. The original Low
label was not retained in historical CSVs or checkpoints. New Layer 2 stores
_classification_certainty_raw and no longer promotes Low solely on recognition.
Layer 3 returns five optional grades. Layer 4 now actually examines those values.
Absence of Layer 3 grades is not itself a review rule.

Implementation map
------------------
core/review_rules.py capture_evidence records actual sample length, sensitive-term matches and
source excerpts, supplementary visual results, prescreen, raw certainty and status.
core/review_rules.py content_state checks final reading evidence and actual
supplementary output. Confidence alone is not success. An OCR success after a
failed attempt is not counted as no content. A placeholder is not readable content.
core/review_rules.py evaluate_review is the sole rule implementation.
checkpoint_evidence and matching_evidence load and match existing L1/L2 checkpoints to CSV rows.
Matching requires path, domain, asset, certainty, final method and final coverage;
it does not establish that source-file contents are unchanged or facts are true.
core/layer4.py layer4_trust delegates to this implementation and preserves labels.
core/pipeline.py writes the audit; agent regrading also refreshes rule results.
server/dashboard_server.py _review_dataframe recomputes rules for display and exports after
loading evidence and applying saved human edits. Legacy action is never an input.
static/dashboard.html reviewPool uses audit queue membership for pending lists/counts.

Rules
-----
ID                       Queue          Priority  Checked evidence / human action
classification_failed    Priority       Critical  llm_status + final domain/asset;
                                                   classify source if no usable final alternative.
unknown_domain           Priority       High      domain; inspect and select primary domain.
unsupported_grades       Priority       High      final method/coverage/sample length,
                                                   actual visual result, populated 5 grades;
                                                   inspect source before using grades.
confidentiality_conflict Priority       High      original label, extension, email,
                                                   bounded sensitive-term matches and drawing
                                                   heuristic; confirm against access policy.
low_certainty            Priority       Medium    final or saved raw classification certainty;
                                                   check classification against source.
extraction_failed        Verification   Low       failed final read, no successful alternative;
                                                   retry parser/OCR/viewer or record inaccessible.
metadata_only            Verification   Low       metadata final method, no content alternative;
                                                   includes CAD/BIM; open compatible viewer.
asset_conflict           Verification   Low       format or prescreen vs asset_type;
                                                   inspect structure, confirm original label.
unknown_governance       Verification   Low       governance; verify issuer/source.
project_year             Verification   Low       year/confidence/project range and existing
                                                   age thresholds; verify date/relevance.

Rules that overlap all remain in the audit. Queue assignment uses highest priority:
Critical > High > Medium; any priority trigger takes precedence over verification.
Verification-only and priority counts are disjoint; their union is the total.
Reason counts include every trigger, so their sum is not a file count.
Asset/prescreen disagreement, drawing sensitivity and project-year signals are
heuristics requiring confirmation, not proofs of misclassification or invalidity.
Sensitive-term scanning preserves the existing first-3000-character boundary.

CSV compatibility
-----------------
The CSV schema remains at 46 columns, with original names/order unchanged.
review_reasons contains short phrases such as "Confidentiality conflict" or
"Ratings without readable content". Detailed rule findings, checked values,
actions and evidence limits are stored separately in <csv>.audit.json and are
available internally to the Dashboard API. They are not appended to CSV exports
or displayed as paragraphs in review cards. The evaluator still returns the
full audit internally; model classifications/grades remain unchanged. Append
writes normalize prior 47-column headers back to 46 and preserve audit data in
the sidecar. The offline audit never overwrites experimental CSVs.

Historical limits
-----------------
Existing matching .resume.jsonl records recover samples, visual and prescreen
results for all three experiments. Without a match, content-dependent rules are
not guessed when an unrecorded visual fallback could have succeeded. Missing
sensitive-term or prescreen evidence is disclosed. Years missing/unparseable are
not guessed. Historical pre-promotion certainty cannot be recovered even with
these checkpoints, so historical low-certainty counts may be incomplete.

Dashboard and exports
---------------------
Top total and Review badge always report the unique pending union. The breakdown
shows priority and verification-only counts. The scope selects priority,
verification-only or all pending. Each card displays concise reason phrases. Detailed fields, actions and
evidence limits remain in the separate audit file. Export uses that same server evaluator and scope, keyed by
file_path rather than filename. Same-named files are not conflated. Already
reviewed paths are excluded from pending counts; saved edits and state sidecars
remain intact. All files stay discoverable in All files, including reviewed ones.
Files and Review are therefore not disjoint tabs. Batch processing is supported
by scoped CSV export; no unverified batch approval is performed.

Offline reproduction
--------------------
  python scripts/recompute_review.py outputs/archive_a.csv outputs/archive_b.csv outputs/archive_c.csv

This reads the three CSVs, their saved configuration/checkpoint/review sidecars,
and writes only outputs/review. It records hashes, baseline priorities and
legacy action-expanded membership, new unique queue totals, per-rule counts,
pairwise reason overlaps, missing evidence and real examples. It checks original
CSV hashes after computation. No LLM call and no original source-file read is
performed. Project artifacts are private and remain under ignored outputs/.

Tests
-----
  python -m pytest -q

Tests cover severity precedence, failed classification vs actual alternatives,
Low certainty with strong visual confidence, metadata/CAD without content plus
grades, no-grade exemption, successful visual/OCR alternatives, preserved labels,
format/prescreen conflicts, source/year checks, missing evidence, stale action,
checkpoint mismatch, legacy CSV header migration, duplicate names, empty export,
reviewed exclusion, saved edits and API/export membership/audit consistency.

Suggested methods text (rule-based results, not human-validated effectiveness)
----------------------------------------------------------------------------
We implemented a deterministic, versioned review layer over recorded extraction,
classification and grading outputs. Rules identify unavailable reading evidence,
classification uncertainty and conflicts with predefined format, confidentiality,
source and project-time heuristics. Each trigger records the rule identifier,
observed fields and values, rationale, and a recommended human check. Records
meeting any Critical, High or Medium condition enter a priority review queue;
remaining flagged records enter a content-verification queue. All triggered
reasons are retained while records are counted once by file path. We recomputed
these rule triggers offline on three saved project outputs using matched L1/L2
checkpoints, without new model calls or overwriting original experimental CSVs.
Unavailable historical evidence was disclosed rather than imputed. The reported
counts quantify rule-triggered review workload, not confirmed model errors or
human-validated improvements. Summary factuality and grade correctness were not
validated; estimating precision, recall or review effectiveness requires a
separate human annotation protocol and evidence-grounded evaluation.
