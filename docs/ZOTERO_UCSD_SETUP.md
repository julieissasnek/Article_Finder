# Zotero + UCSD Library Setup Guide

## Overview

This guide sets up Zotero Desktop and the Zotero Connector to download PDFs
using your UCSD library access. Combined with Article Finder's Zotero bridge,
this enables semi-automated PDF acquisition for papers behind paywalls.

Important distinction:

- The Zotero Web API is useful for item and attachment bookkeeping.
- Institutional PDF retrieval is a Zotero Desktop + browser-authenticated
  access problem, not something the Web API itself performs.

## The Workflow

```
┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│  1. Export from Article Finder (papers needing PDFs)            │
│     python cli/main.py zotero export                            │
│                        ↓                                        │
│  2. Import into Zotero                                          │
│     File → Import → papers_needing_pdfs.ris                     │
│                        ↓                                        │
│  3. Get PDFs via UCSD Library                                   │
│     Select all → Right-click → "Find Available PDF"             │
│     (Zotero uses your UCSD credentials)                         │
│                        ↓                                        │
│  4. Import back to Article Finder                               │
│     python cli/main.py zotero import                            │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Step 1: Prefer UCSD SSO or VPN; use manual proxy only if needed

As of May 10, 2026, UCSD's official guidance emphasizes library SSO and VPN
access rather than a generic off-campus web proxy.

Recommended order:

1. Use UCSD-authenticated access from the article landing page in your browser
2. If a publisher site still resists, use UCSD VPN
3. Only then bother with a hand-maintained Zotero proxy rule

### Fast path

1. Open the publisher landing page in your browser
2. Authenticate through UCSD when prompted
3. Save with the Zotero Connector, or in Zotero Desktop run
   **Find Available PDF**

### Manual proxy configuration (optional)

### Mac

1. **Open Zotero**

2. **Open Preferences**: Click **Zotero** menu (top left) → **Settings...**

3. **Go to Advanced tab**: Click **Advanced** in the sidebar

4. **Open Config Editor**: Near the bottom, click **Config Editor**
   - If you get a warning, click "I accept the risk"

5. **Find the proxy setting**: In the search box at top, type: `proxies`

6. **Look for**: `extensions.zotero.proxies.proxies`
   - If it doesn't exist, you may need to add it

7. **Set UCSD proxy**: Double-click to edit, and paste:
```json
[{"id":"ucsd","autoAssociate":true,"scheme":"https://%h.ucsd.idm.oclc.org/%p","hosts":["www.jstor.org","www.sciencedirect.com","onlinelibrary.wiley.com","link.springer.com","journals.sagepub.com","www.tandfonline.com","www.nature.com","ieeexplore.ieee.org","dl.acm.org"]}]
```

8. **Enable auto-associate**: Search for `extensions.zotero.proxies.autoRecognize` and set to `true`

### Alternative: Use Zotero's Built-in Proxy Detection

If the manual method is confusing:

1. **Go to any UCSD library resource** in your browser (e.g., search something on library.ucsd.edu)
2. **Click on a journal article link** — you'll be redirected through the proxy
3. **Save the article to Zotero** using the browser connector
4. Zotero will detect the proxy and offer to save it

---

## Step 2: Set Up Zotero Connector (Browser Extension)

The Zotero Connector helps Zotero recognize when you're accessing resources through the library.

1. **Install Zotero Connector** for your browser:
   - [Chrome](https://chrome.google.com/webstore/detail/zotero-connector/ekhagklcjbdpajgpjgmbionohlpdbjgc)
   - [Firefox](https://www.zotero.org/download/connectors)
   - [Safari](https://www.zotero.org/download/connectors)

2. **Configure proxy in connector** (optional but helpful):
   - Click the Zotero Connector icon
   - Click the gear icon → Preferences
   - Under "Proxies", enable "Automatically detect and configure proxies"

---

## Step 3: Test the Setup

1. **Go to UCSD Library**: https://library.ucsd.edu

2. **Search for any article** that you know is behind a paywall

3. **Click through to the publisher**. You should be prompted to log in via UCSD SSO (Duo).

4. **After logging in**, you should see the full article

5. **In Zotero**, try right-clicking on any paper → **Find Available PDF**

If it works, Zotero will download the PDF through your authenticated session.

---

## Step 4: Use with Article Finder

### Export Papers Needing PDFs

```bash
cd ~/REPOS/article_finder_v3.2
source venv/bin/activate

# Export to RIS format (best for Zotero)
python cli/main.py zotero export --format ris

# Or limit to most important papers
python cli/main.py zotero export --format ris --limit 50
```

This creates `papers_needing_pdfs.ris` in the current directory.

### Import into Zotero

1. Open Zotero
2. **File → Import...**
3. Select `papers_needing_pdfs.ris`
4. Choose which collection to import into (or create a new one like "To Download")

### Batch Download PDFs

1. Select all the newly imported items (Cmd+A or Ctrl+A)
2. **Right-click → Find Available PDF**
3. Wait. Zotero will:
   - Try open-access routes first
   - Use your active UCSD-authenticated access for paywalled content
   - Show progress in the bottom-right

**Tip**: Do this in batches of 50-100 to avoid overwhelming the session.

### Import PDFs Back to Article Finder

```bash
# First, check what's available
python cli/main.py zotero stats

# Dry run to see what would be imported
python cli/main.py zotero import --dry-run

# Actually import the PDFs
python cli/main.py zotero import
```

---

## Troubleshooting

### "Find Available PDF" Does Nothing

- Make sure Zotero is open (not just the browser connector)
- Check that the item has a DOI (right-click → View Online should work)
- Your UCSD session may have expired — visit library.ucsd.edu and log in again

### Proxy Not Working

Test manually:
1. Take any DOI, e.g., `10.1016/j.buildenv.2021.107621`
2. Go to: `https://doi-org.ucsd.idm.oclc.org/10.1016/j.buildenv.2021.107621`
3. You should be prompted for UCSD SSO
4. After login, you should reach the full text

If this doesn't work, try UCSD VPN before assuming the generic proxy route is
still the right one, and then retry.

### Zotero Can't Find PDFs I Know Exist

Some publishers don't work well with Zotero's PDF finder. For these:
1. Open the article in your browser with UCSD-authenticated access
2. Download the PDF manually
3. Drag the PDF onto the Zotero item
4. The PDF will be attached and sync to local storage

### "Zotero data directory not found"

Article Finder looks for Zotero in `~/Zotero`. If yours is elsewhere:
```bash
python cli/main.py zotero stats --zotero-dir /path/to/your/Zotero
```

---

## Command Reference

```bash
# Show Zotero library and Article Finder PDF status
python cli/main.py zotero stats

# Export papers needing PDFs
python cli/main.py zotero export                    # Default: RIS format
python cli/main.py zotero export --format csv      # CSV with DOIs
python cli/main.py zotero export --limit 100       # Limit count

# Import PDFs from Zotero
python cli/main.py zotero import                   # Copy PDFs to Article Finder
python cli/main.py zotero import --dry-run         # Preview only

# Specify non-standard Zotero location
python cli/main.py zotero stats --zotero-dir ~/Documents/Zotero
```

---

## Weekly Workflow Suggestion

**Every Monday (15 minutes):**

1. Export papers needing PDFs:
   ```bash
   python cli/main.py zotero export --limit 30
   ```

2. Import to Zotero, select all, "Find Available PDF"

3. While Zotero downloads, review which papers couldn't be found

4. For critical papers without PDFs: manually download through library

5. Import back to Article Finder:
   ```bash
   python cli/main.py zotero import
   ```

This approach should get you to 60-70% PDF coverage over a few weeks.

---

## UCSD-Specific Resources

- **Library Homepage**: https://library.ucsd.edu
- **Trusted Resources / UCSD access**: https://blink.ucsd.edu/technology/security/secure-connect/required-software/trusted-resources/index.html
- **VPN**: https://blink.ucsd.edu/go/vpn
- **Web Proxy note**: https://blink.ucsd.edu/technology/network/connections/off-campus/proxy/index.html
- **Library IT Support**: lib-helpdesk@ucsd.edu

---

*Last updated: May 10, 2026*
*Article Finder v3.2.3*
