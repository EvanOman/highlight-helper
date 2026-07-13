# Attribution — real-photo holdout images

Every committed image here is public-domain. Sources and licenses below, per the
repo's eval-data licensing policy (see
`docs/decisions/2026-07-12-eval-data-sourcing.md`, D3).

Ground-truth labels in `labels.json` are **vision transcriptions drafted by a
vision model and cross-checked against each source's Internet Archive OCR**
(`*_djvu.txt`). They are human-verifiable, not gospel — verify before trusting a
single case's exact offsets.

## Images

| File | Source work | Page | Author | Publisher / year | Status | IA identifier |
|---|---|---|---|---|---|---|
| `0001.jpg` | *Vegetable Gardening* | 57 | Samuel B. Green (1859–1910) | Webb Pub. Co., St. Paul, 1896 | Public domain (not in copyright) | `vegetablegardeni00gree` |
| `0002.jpg` | *Vegetable Gardening* | 97 | Samuel B. Green | Webb Pub. Co., 1896 | Public domain | `vegetablegardeni00gree` |
| `0003.jpg` | *Manual of Gardening* | 85 | L. H. Bailey (1858–1954) | Macmillan, New York, 1910 | Public domain (no known copyright restrictions) | `manualofgardenin01bail` |
| `0004.jpg` | *Manual of Gardening* | 161 | L. H. Bailey | Macmillan, 1910 | Public domain | `manualofgardenin01bail` |
| `0005.jpg` | *Pride and Prejudice* — illustration plate ("Mr. Collins proposes") | Chap. 19 plate | Jane Austen (text); illustrated ed. | J. M. Dent, London, 1892 | Public domain (not in copyright) | `novelsjaneauste11austgoog` |
| `0006.jpg` | *Vegetable Gardening* | 37 | Samuel B. Green | Webb Pub. Co., 1896 | Public domain | `vegetablegardeni00gree` |
| `0007.jpg` | *Manual of Gardening* | 257 | L. H. Bailey | Macmillan, 1910 | Public domain | `manualofgardenin01bail` |
| `0008.jpg` | *Vegetable Gardening* | 77 | Samuel B. Green | Webb Pub. Co., 1896 | Public domain | `vegetablegardeni00gree` |
| `0009.jpg` | *Manual of Gardening* — full-page photo plate IV ("Subtropical bedding against a building") | plate IV | L. H. Bailey | Macmillan, 1910 | Public domain | `manualofgardenin01bail` |

Each image is a single page fetched from
`https://archive.org/download/<identifier>/page/n<N>_w1200.jpg`. All source works
were published in the United States before 1929 (or are marked NOT_IN_COPYRIGHT
by the holding library) and are therefore in the public domain.

## Why no marker / underline modalities here

The holdout is entirely **instruction-based** (find the passage the user
describes on an unmarked page) and **negative** (no highlight present) cases,
because freely-licensable pages with a *genuine* highlight essentially do not
exist: pages that carry a real highlight are from in-copyright books (e.g. a
Kindle screenshot of a 2008 title, a modern Bible translation), while
public-domain page scans are never pre-marked. Committing an image of an
in-copyright page to a public repo would violate the D3 policy regardless of how
the photographer licensed their photo. See the decision log for the full
reasoning. Add your **own** phone photos of highlighted pages (which you own) to
build out the marker/underline modalities over time — see `README.md`.
