# Knowledge base — documents & sources

The files in this folder are the RAG knowledge base for **OutdoorGPT**. `scripts/rag_ingest.py` cuts them into chunks and embeds them into the search index (see the main [README](../README.md), Step 3).

## Conventions

- **One subfolder per source.** Each document lives in a subfolder named after the place it was downloaded from, so the folder name doubles as a provenance / source tag.
- **License.** Everything here is **public domain or free to redistribute** — nothing under active copyright. The *SAS Survival Handbook* is deliberately **not** included (still copyrighted); the U.S. Army Survival Manual FM 21-76 is the public-domain equivalent.
- **Language.** English documents work best — the embedding and speech pipeline are tuned for English.
- **OCR.** Four manuals were originally scanned image-only PDFs. They have already been **OCR'd** into searchable text (and the largest scans rebuilt as compact text PDFs), so every file here ingests directly — no extra OCR step.
- **Git.** The per-source subfolders are kept out of the repo via `.gitignore`, so the PDFs themselves are not committed — this file is the record of what the knowledge base contains and where it came from. Only files directly in `docs/` (this `README.md` and `test_document.md`) are tracked.

## `github.com-mr-dgidgi-RecoveryENPDF/`

Downloaded from the GitHub collection [mr-dgidgi/RecoveryENPDF](https://github.com/mr-dgidgi/RecoveryENPDF) — a community-curated set of public-domain survival, first-aid and preparedness PDFs. Original issuers and licensing:

| Document | Origin / author | License |
| -------- | --------------- | ------- |
| `FM-21-76-US-Army-Survival-Manual.pdf` *(OCR'd)* | U.S. Army — FM 21-76 | Public domain (US Gov work) |
| `FM-21-76-1-Survival-Evasion-and-Recovery-Multiservice-Procedures.pdf` | U.S. Armed Forces — FM 21-76-1 | Public domain |
| `ST-31-91B-US-Army-Special-Forces-Medical-Handbook.pdf` *(OCR'd)* | U.S. Army — ST 31-91B | Public domain |
| `FM-4-25-11-First_Aid.pdf` | U.S. Army — FM 4-25.11 | Public domain |
| `FM-21-10-Field-Hygiene-and-Sanitation.pdf` | U.S. Army — FM 21-10 | Public domain |
| `FM-3-25-26-Map-Reading-and-Land-Navigation.pdf` | U.S. Army — FM 3-25.26 | Public domain |
| `USMC-Summer-Survival-Course-Handbook.pdf` | U.S. Marine Corps | Public domain |
| `USMC-Winter-Survival-Course-Handbook.pdf` | U.S. Marine Corps | Public domain |
| `Down-But-Not-Out-Canadian-Survival-Manual.pdf` *(OCR'd)* | Canadian Forces / DND | Crown copyright, freely distributed |
| `Where-There-is-no-Doctor-a-Village-Health-Care-Handbook.pdf` | Hesperian Health Guides | Free to copy/distribute for non-profit use |
| `Where-There-is-No-Dentist.pdf` | Hesperian Health Guides | Free to copy/distribute for non-profit use |
| `Boy-Scout-Handbook-1911.pdf` | Boy Scouts of America (1911) | Public domain (pre-1929) |
| `Shelters-Shacks-and-Shanties.pdf` | D. C. Beard (1914) | Public domain (pre-1929) |
| `Deadfalls-and-Snares.pdf` | A. R. Harding (1907) | Public domain (pre-1929) |
| `Printable-PDF-of-the-Universal-Edibility-Test-for-Survival.pdf` *(OCR'd)* | Infographic via TruePrepper; based on the U.S. military Universal Edibility Test | Freely distributed graphic; underlying method public domain |

## `github.com-GITenberg-Camp-Cookery-How-to-Live-in-Camp_54138/`

| Document | Origin / author | License |
| -------- | --------------- | ------- |
| `Camp-Cookery-How-to-Live-in-Camp-Parloa.pdf` | Maria Parloa, *Camp Cookery: How to Live in Camp* (1878) — [Project Gutenberg #54138](https://www.gutenberg.org/ebooks/54138) via [GITenberg](https://github.com/GITenberg/Camp-Cookery-How-to-Live-in-Camp_54138) | Public domain |

## `github.com-GITenberg-Camping-and-camp-cooking_73671/`

| Document | Origin / author | License |
| -------- | --------------- | ------- |
| `Camping-and-Camp-Cooking-Bates.pdf` | Frank A. Bates, *Camping and Camp Cooking* (1914) — [Project Gutenberg #73671](https://www.gutenberg.org/ebooks/73671) via [GITenberg](https://github.com/GITenberg/Camping-and-camp-cooking_73671) | Public domain |

> The two cookery books were rebuilt from the Project Gutenberg plain text into clean, searchable PDFs.

## Adding or changing documents

Drop new files into a source-named subfolder here (PDF, `.txt` or `.md`), then rebuild the index from the repo root:

```
python scripts/rag_ingest.py --docs_dir docs
```

Rebuilding is required whenever you add or remove documents — the index is regenerated from scratch each time.
