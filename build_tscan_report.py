#!/usr/bin/env python3
"""Generate TScan Therapeutics TCR-T report PDF."""
import markdown, os
from weasyprint import HTML

INPUT = "/home/j/drug-pipeline/tscan-report-v1.md"
OUTPUT = "/home/j/drug-pipeline/tscan-tcr-t-positioning-2026.pdf"

with open(INPUT) as f:
    md_text = f.read()

# Remove YAML frontmatter (between --- lines)
lines = md_text.split('\n')
if lines[0].strip() == '---':
    end = 1
    while end < len(lines) and lines[end].strip() != '---':
        end += 1
    md_text = '\n'.join(lines[end+1:])

html_body = markdown.markdown(md_text, extensions=["tables", "fenced_code", "sane_lists"])

COVER = '''
<div style="page-break-after: always; text-align: center; padding-top: 80px;">
  <div style="font-size: 9pt; color: #1a56db; letter-spacing: 3px; text-transform: uppercase; margin-bottom: 20px;">Competitive Intelligence Report</div>
  <h1 style="font-size: 22pt; color: #111827; border: none; margin: 0 0 10px 0;">TScan Therapeutics</h1>
  <h2 style="font-size: 14pt; color: #6b7280; font-weight: 400; margin: 0 0 40px 0;">TCR-T Competitive Positioning 2026</h2>
  <hr style="width: 40%; border: none; border-top: 2px solid #1a56db; margin: 30px auto;">
  <table style="width: 50%; margin: 30px auto; border: none; font-size: 9pt;">
    <tr><td style="border: none; text-align: right; padding: 3px 10px; color: #6b7280;">Prepared for:</td><td style="border: none; text-align: left; padding: 3px 10px;"><strong>Dr. Gavin MacBeath, Ph.D.</strong> — CEO, TScan Therapeutics</td></tr>
    <tr><td style="border: none; text-align: right; padding: 3px 10px; color: #6b7280;">Date:</td><td style="border: none; text-align: left; padding: 3px 10px;">May 26, 2026</td></tr>
    <tr><td style="border: none; text-align: right; padding: 3px 10px; color: #6b7280;">Data Sources:</td><td style="border: none; text-align: left; padding: 3px 10px;">6 (ClinicalTrials · openFDA · FAERS · PubMed · Yahoo Finance · SEC)</td></tr>
    <tr><td style="border: none; text-align: right; padding: 3px 10px; color: #6b7280;">Tool Calls:</td><td style="border: none; text-align: left; padding: 3px 10px;">47 MCP · 6 APIs</td></tr>
    <tr><td style="border: none; text-align: right; padding: 3px 10px; color: #6b7280;">Company MCap:</td><td style="border: none; text-align: left; padding: 3px 10px;">$69.3M (NASDAQ: TCRX)</td></tr>
  </table>
  <div style="position: fixed; bottom: 40px; left: 0; right: 0; font-size: 8pt; color: #9ca3af;">
    Powered by <strong>drug-pipeline-mcp</strong> — Pharmaceutical R&amp;D Intelligence for AI Agents
  </div>
</div>
'''

TOC = '''
<div style="page-break-after: always;">
  <h1 style="font-size: 16pt;">Table of Contents</h1>
  <ul style="list-style: none; padding: 0; font-size: 9.5pt; line-height: 2;">
    <li>1. Executive Summary</li>
    <li>2. Company Overview</li>
    <li>3. TScan Platform &amp; Pipeline</li>
    <li>4. Lead Candidate Deep Dive: TSC-100 / TSC-101</li>
    <li>5. Lead Candidate Deep Dive: TSC-200 Series (T-Plex)</li>
    <li>6. Disease Treatment Landscape: TCR-T in Oncology</li>
    <li>7. Competitive Landscape</li>
    <li>8. Cross-Modality Comparison</li>
    <li>9. Financial Health &amp; Valuation</li>
    <li>10. Near-Term Catalysts</li>
    <li>11. Strategic Positioning</li>
    <li>12. Key Takeaways</li>
    <li>13. Appendix: Methodology &amp; Data Sources</li>
  </ul>
  <hr style="width: 40%; border: none; border-top: 1px solid #e5e7eb; margin: 30px 0;">
  <p style="color: #6b7280; font-size: 8.5pt;">Data current as of May 26, 2026. All financial data from Yahoo Finance. Clinical data from ClinicalTrials.gov, openFDA, and PubMed.</p>
</div>
'''

full_html = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<style>
  @page {{ size: A4; margin: 2cm 2cm 2.5cm 2cm;
    @bottom-center {{ content: "drug-pipeline-mcp — TScan TCR-T Competitive Positioning | " counter(page); font-size: 7.5pt; color: #bbb; font-family: "Helvetica Neue", Helvetica, Arial, sans-serif; }}
    @top-right {{ content: "May 26, 2026"; font-size: 7pt; color: #ccc; font-family: "Helvetica Neue", Helvetica, Arial, sans-serif; }}
  }}
  @page :first {{ @bottom-center {{ content: none; }} @top-right {{ content: none; }} }}
  @page toc {{ @bottom-center {{ content: none; }} @top-right {{ content: none; }} }}
  body {{ font-family: "Helvetica Neue", Helvetica, Arial, sans-serif; font-size: 9.5pt; line-height: 1.55; color: #1a1a1a; }}
  h1 {{ font-size: 16pt; color: #1a56db; border-bottom: 2px solid #1a56db; padding-bottom: 6px; margin: 28px 0 14px 0; page-break-after: avoid; }}
  h2 {{ font-size: 12pt; color: #374151; margin: 22px 0 10px 0; page-break-after: avoid; }}
  h3 {{ font-size: 10.5pt; color: #4b5563; margin: 16px 0 8px 0; }}
  p {{ margin: 6px 0; }}
  ul, ol {{ margin: 4px 0 8px 0; padding-left: 20px; }}
  li {{ margin: 2px 0; }}
  table {{ width: 100%; border-collapse: collapse; margin: 10px 0; font-size: 8.5pt; page-break-inside: avoid; }}
  th {{ background: #1a56db; color: white; padding: 5px 6px; text-align: left; font-weight: 600; font-size: 8pt; }}
  td {{ padding: 4px 6px; border-bottom: 1px solid #e5e7eb; vertical-align: top; }}
  tr:nth-child(even) td {{ background: #f9fafb; }}
  strong {{ color: #111827; }}
  em {{ color: #4b5563; }}
  blockquote {{ background: #eff6ff; border-left: 3px solid #1a56db; padding: 8px 12px; margin: 12px 0; font-size: 9pt; }}
  hr {{ border: none; border-top: 1px solid #e5e7eb; margin: 20px 0; }}
</style>
</head>
<body>
{COVER}
{TOC}
{html_body}
</body>
</html>'''

HTML(string=full_html).write_pdf(OUTPUT)
size_kb = os.path.getsize(OUTPUT) // 1024
print(f"✅ PDF: {OUTPUT} ({size_kb} KB)")
