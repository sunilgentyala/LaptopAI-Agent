# Skill: IEEE-EDAS Paper Format (python-docx)

Reusable procedure for building an IEEE conference/workshop paper as a
two-column DOCX suitable for EDAS submission. Confirmed against multiple
accepted/camera-ready manuscripts for Sunil Gentyala's IEEE publication
workflow (LeaseGuard, QuantumShieldEdge, TRACE-MAS, CRISP, FedQSense, and
others). Apply this whenever asked to build, fix, or reformat an
"IEEE-EDAS" style paper.

## Document structure

- Times New Roman throughout. US Letter (8.5in x 11in).
- Page margins: left/right 0.625in, top 0.75in, bottom 1.0in.
- Title: 22-24pt bold, centered.
- Author block: name bold centered, affiliation/email lines below, also
  centered. For multiple authors, use a borderless table (rows x 3 cols),
  NOT sequential paragraphs -- paragraphs in multi-column text flow get
  extracted in column-reading order, which scrambles author order when the
  document is parsed linearly later.
- **Single-column header section**: title, author block, abstract, keywords.
- **Two-column body section** (720-twip / 0.5in gutter): everything from
  "I. INTRODUCTION" through references.
- Section (Roman numeral) headings: 10pt bold, centered, e.g. "I. INTRODUCTION".
- Subsection headings: 10pt italic, left-aligned, e.g. "A. Task and Dataset".
- Body text: 10pt justified, 0.2in first-line indent.
- References: numbered "[1]", "[2]", ... hanging indent, 9pt.

## Abstract / Keywords -- exact label and formatting (NOT "Index Terms")

This user's house style uses "Keywords", not "Index Terms". Both labels use
a real em dash (the character "--" typed by hand must be converted to "--" /
U+2014 in the rendered docx) directly after the word, e.g. "Abstract--" and
"Keywords--". This is a fixed IEEE typographic convention, distinct from
prose writing style rules about avoiding em dashes in written analysis --
apply it exactly as documented, not as a stylistic choice.

Confirmed bold/italic formula (inspected from a hand-corrected accepted
camera-ready file):

- `Abstract--` label run: bold=True, italic=True (bold-italic).
- Abstract body text (rest of the paragraph): bold=True, italic=False --
  bold only, NOT italic.
- `Keywords--` label AND the entire keyword/term list: bold=True,
  italic=True for the WHOLE line (label through the last keyword) -- unlike
  the abstract, keywords does not drop italic for the body text.
- Font for both: Times New Roman, 9pt.

```python
# Abstract paragraph
label_run = p.add_run("Abstract\u2014"); label_run.bold = True; label_run.italic = True
body_run = p.add_run(abstract_text); body_run.bold = True; body_run.italic = False
body_run.font.name = "Times New Roman"; body_run.font.size = Pt(9)

# Keywords paragraph -- bold+italic applies to the ENTIRE line
kw_run = p.add_run("Keywords\u2014" + keywords_text)
kw_run.bold = True; kw_run.italic = True
kw_run.font.name = "Times New Roman"; kw_run.font.size = Pt(9)
```

## Two-sided document (mirrored margins)

This user wants IEEE manuscripts saved as two-sided documents (for
facing-page printing/binding). python-docx has no high-level property for
this -- it is a document-wide toggle stored in `word/settings.xml`:

```python
def enable_mirror_margins(doc):
    settings = doc.settings.element
    mirror_el = OxmlElement("w:mirrorMargins")
    settings.insert(0, mirror_el)

# call once, right before doc.save(path)
enable_mirror_margins(doc)
doc.save(dst)
```

Verify it landed by unzipping the saved docx and checking
`"mirrorMargins" in z.read("word/settings.xml").decode()`.

## Critical python-docx gotchas (each cost real debugging time -- apply proactively, don't rediscover)

1. **Continuous section break changing column count MUST use the high-level
   API**, never hand-built `OxmlElement("w:sectPr")` paragraph insertion:
   ```python
   from docx.enum.section import WD_SECTION
   section = doc.add_section(WD_SECTION.CONTINUOUS)
   section.left_margin = Inches(0.625)  # set full page geometry explicitly
   # ... remaining margins ...
   cols_el = section._sectPr.find(qn("w:cols"))
   cols_el.set(qn("w:num"), "2")
   cols_el.set(qn("w:space"), "720")
   ```
   A manually constructed `<w:sectPr>` with correct CT_SectPr child order
   (`<w:type>` before `<w:pgSz>`) is still schema-valid XML, but Word still
   forces a spurious page break between the header and the two-column body,
   leaving a large blank area on page 1. The official `add_section()` API
   sets some undocumented default that raw XML construction drops. This was
   confirmed with a minimal isolated test doc, not just theory -- when in
   doubt, build a 20-line test doc and check with Word COM before debugging
   the real file further.

2. **Exactly 2 sections for the whole document** (1-col header, 2-col
   everything else). A stray 3rd section -- e.g. wrapping only the abstract
   and keywords in their own short 2-column section -- makes Word
   auto-balance that section's columns to roughly equal height instead of
   greedily filling column 1 first, so the abstract visually splits mid-
   sentence across both columns even though a text-only dump looks correct.
   Check `len(doc.sections)` after building; it must be exactly 2.

3. **Keep figures inline at column width (~3.3in), do not give each figure
   its own full-width single-column section.** Multiple extra sections
   trigger the same auto-balance bug as #2.

4. **Any paragraph containing an inline image needs
   `paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE` set
   explicitly.** If the paragraph inherits a body style with EXACT line
   spacing (e.g. 12pt fixed, matching 10pt body text leading), Word clips
   the image to that fixed line height -- symptom is only a thin sliver of
   the image (e.g. just an axis label) rendering, with the rest silently
   cut off. Easy to miss because the docx XML and the embedded image bytes
   are both completely correct; only the rendered layout is broken.

5. **Table rows should get `<w:cantSplit/>` on `trPr`** to stop a row's
   content splitting mid-cell across a page/column break:
   ```python
   for row in table.rows:
       trPr = row._tr.get_or_add_trPr()
       trPr.append(OxmlElement("w:cantSplit"))
   ```

6. **Verify pagination for real, never estimate from word count.** This
   environment has MS Word available via COM:
   ```powershell
   $word = New-Object -ComObject Word.Application; $word.Visible = $false
   $doc = $word.Documents.Open($path)
   $doc.Repaginate()
   $pages = $doc.ComputeStatistics(2)   # 2 = wdStatisticPages
   $doc.SaveAs([ref]$pdfPath, [ref]17)  # 17 = wdFormatPDF
   $doc.Close($false); $word.Quit()
   ```
   Then rasterize the PDF with PyMuPDF (`fitz`, already available) and
   actually read the page images -- don't trust the page-count number alone
   for layout correctness; visually confirm columns, figures, and tables
   render as intended.

## Content-integrity practices (non-negotiable, apply before calling any paper "done")

- Every quantitative claim in Results must trace to a real, reproducible
  experiment that was actually run -- never state a specific number (e.g.
  "1,000 trials", "22 microseconds") unless the code that produced it exists
  and was executed. If a draft claims a test that wasn't actually run,
  implement and run it for real before finalizing, don't just reword the claim.
- Cross-check every formula-derived number in the paper against the paper's
  own stated formula (recompute and diff against what's printed in tables).
- Verify every reference has a real, checkable DOI, and that the cited
  source's actual abstract/content supports the specific claim attached to
  it -- topical adjacency is not enough.
- Cap reference count (this user's default ceiling: 15).
- Run AEGIS (plagiarism / AI-detection / citation-integrity check) before
  finalizing; target LOW overall risk, ~0.00 plagiarism score, low AI-
  detection score, 0% citation issues.

## File and repo conventions for this user

- Canonical manuscript location:
  `C:\Users\Sunil\Documents\EB1A_local\Academic\IEEE\<ProjectName>\` containing
  `<ProjectName>_IEEE_Paper.docx`, `.pdf`, `.md` (source), `build_docx.py`,
  and a local `figures/` folder -- self-contained, not dependent on any
  other repo's paths.
- Never push manuscript files (`.docx`/`.md`/`.pdf` of the paper itself) to
  a public GitHub repository -- only source code, tests, experiment
  scripts, and result artifacts (CSV/JSON/figures) belong in the repo.
