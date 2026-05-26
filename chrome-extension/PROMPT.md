# The one prompt to paste into Claude for Chrome

Save this as a text shortcut on your phone / computer. At the start of every BatchLeads scraping session:

1. Open BatchLeads in Chrome and navigate to the property you want to start from (make sure you're already logged in).
2. Open the Claude for Chrome extension.
3. Paste the prompt below.
4. Reply with the URL when Claude asks how many properties to scrape (e.g. "20" or "all of them").

---

## Copy everything between the lines and paste into Claude for Chrome:

---

Fetch this URL and follow every instruction in it exactly:

https://raw.githubusercontent.com/swiftcloseoffers832-debug/scrape/main/chrome-extension/PLAYBOOK.md

I'm on a BatchLeads property page right now. Once you've read the playbook, ask me how many properties to process this session, then run the full scrape end-to-end. Download the final CSV to my PC when done, and print the memory-update markdown block in chat so I can copy it.

---

## After the session ends

Claude will print a markdown block under "Session Log". You have two options:

**Option A — Lazy (recommended).** Open Claude Code on the web on this repo and say:

> Append this Session Log entry to `skills/memory/session-memory.md`, commit, and push:
>
> *(paste the markdown block Claude for Chrome gave you)*

Claude Code will do the git work.

**Option B — Manual.** Open `skills/memory/session-memory.md` on GitHub, click the pencil icon, paste the block under `## Session Log`, commit.

Either way, the next session's playbook will include the updated memory automatically.
