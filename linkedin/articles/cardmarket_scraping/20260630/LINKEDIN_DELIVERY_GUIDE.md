# How to publish this article on LinkedIn

Files in this folder:

| File | When to use it |
|------|----------------|
| `article_linkedin_paste.txt` | Copy into the **Write article** body |
| `linkedin_post_hook.txt` | Copy into a **feed post** after publishing (or into the publish commentary field) |
| `images/01_hero_cover.png` | Article cover image |
| `images/02` … `05_*.png` | Inline images in the article body |
| `article.md` | Source draft (do not paste directly — markdown won't render) |
| `article_linkedin_post_only.txt` | Fallback if you don't have **Write article** |

Suggested article title:

**I Stopped Scraping Cardmarket. Here's What I Built Instead.**

---

## Before you start

1. Open `article_linkedin_paste.txt` and skim the `[IMAGE: …]` markers — there are four inline images plus one cover.
2. Put all five PNGs from `images/` somewhere easy to reach (Desktop, etc.).
3. On linkedin.com, confirm you see **Write article** at the top of your homepage feed. If not, skip to [Fallback: no Article editor](#fallback-no-write-article-button) at the end.

---

## Path A — LinkedIn Article (recommended)

### Step 1: Open the editor

1. Go to [linkedin.com](https://www.linkedin.com).
2. Click **Write article** in the share box at the top of your feed.
3. Choose to publish as yourself (personal profile).

### Step 2: Title and cover

1. Click the **Title** field.
2. Paste: `I Stopped Scraping Cardmarket. Here's What I Built Instead.`
3. Click to add a **cover image**.
4. Upload `images/01_hero_cover.png` (1200×627 recommended).

### Step 3: Paste the body

1. Click in the **Write here** area.
2. Select all of `article_linkedin_paste.txt` (Ctrl+A in the file) and paste (Ctrl+V).

### Step 4: Format with the toolbar

LinkedIn will not auto-format pasted text. Select and style manually:

| What to select | Toolbar action |
|----------------|----------------|
| Section titles (e.g. "What went wrong", "The pivot: official catalog JSON on S3") | **H2** |
| Key phrases: "HTTP 429", "mapping debt", "infrastructure problem" | **Bold** |
| Lines starting with • under a section | Select the group → **Unordered list** |
| Between major sections (after "What went wrong", after "The pivot", etc.) | **Divider** |

Keep paragraphs short (2–3 lines). Mobile readers skim.

### Step 5: Insert images

Find each line like:

```
[IMAGE: 02_legacy_vs_catalog.png — Legacy web scrape vs official S3 catalog pipeline]
```

For each one:

1. Delete the entire `[IMAGE: …]` line.
2. Place cursor where the image should go.
3. Click the **Media** icon in the toolbar.
4. Upload the matching file from `images/`.
5. Optionally add the caption from the placeholder (after the em dash).

Image order in the article:

1. `02_legacy_vs_catalog.png` — after the legacy approach section
2. `03_cloudflare_wall.png` — start of "What went wrong"
3. `04_catalog_matching_flow.png` — after "What improved" bullets
4. `05_naming_mismatch_examples.png` — start of "Drawbacks" section

### Step 6: Code snippets

Two blocks are marked `[CODE SNIPPET — …]`. For each:

1. Delete the marker line.
2. Select the snippet text (3–4 lines).
3. Click the **Code** button in the toolbar.

Do not leave triple-backtick formatting — LinkedIn doesn't support it.

### Step 7: Preview and publish

1. Click **Preview** (upper right). Check mobile layout.
2. Fix any walls of text — add line breaks.
3. Optional: **Settings** → custom URL slug, SEO title/description (helps Google index the article).
4. Click **Next** → **Publish**.
5. Optional: paste `linkedin_post_hook.txt` into "Tell your network what your article is about."

### Step 8: Promo post (recommended)

Within 24 hours:

1. Click **Start a post** (separate from the article).
2. Paste all of `linkedin_post_hook.txt`.
3. Paste your published article URL — LinkedIn should embed a preview card.
4. Post. Reply to early comments — the first hour matters for reach.

---

## Path B — Google Docs first (optional)

Some people get cleaner formatting this way:

1. Paste `article_linkedin_paste.txt` into a new Google Doc.
2. Apply Heading 2 to section titles, bold to key terms, bullets to lists.
3. Copy from Google Docs into LinkedIn's article editor.
4. Re-check images and code blocks — Docs→LinkedIn doesn't always preserve everything.
5. Continue from Step 5 above (insert images).

---

## Fallback: no "Write article" button

Not every profile has the article editor. Alternatives:

### Option 1: Long feed post

Use `article_linkedin_post_only.txt` (~2,500 characters). Attach `02_legacy_vs_catalog.png` and `04_catalog_matching_flow.png` as post images. Link to a GitHub gist or blog if you need the full version.

### Option 2: Document carousel

Create a PDF or PowerPoint with one section per slide:

1. Title slide + `01_hero_cover.png`
2. Problem (no API)
3. Legacy scrape + `02_legacy_vs_catalog.png`
4. What went wrong + `03_cloudflare_wall.png`
5. S3 pivot + `04_catalog_matching_flow.png`
6. Matching rules + `05_naming_mismatch_examples.png`
7. Lessons learned

On LinkedIn: **Start a post** → **Add a document** → upload PDF.

---

## Checklist

- [ ] Title pasted in title field (not body)
- [ ] Cover image uploaded (`01_hero_cover.png`)
- [ ] Body pasted from `article_linkedin_paste.txt`
- [ ] Section titles set to H2
- [ ] Four inline images uploaded at markers
- [ ] Two code snippets formatted with Code button
- [ ] Preview checked on mobile
- [ ] Published
- [ ] Promo post with `linkedin_post_hook.txt` + article link

---

## What NOT to paste

- `article.md` — contains `#` headers, mermaid blocks, and `![image](path)` syntax that won't render
- Mermaid diagram files from `diagrams/` — use the PNG images instead
- Repository paths or `.env` secrets
