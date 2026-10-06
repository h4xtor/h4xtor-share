---
name: publish-homepage
description: Publish a static homepage (HTML/CSS/JS or a framework site) to a public Vercel URL, then check it in a real Chrome via Chrome DevTools. Use when the user wants to put a homepage online, deploy to Vercel, or check a live site.
---

# Publish a homepage

1. **Find the site.** Locate the folder with `index.html` (or the framework project). If none exists, build a simple one first.
2. **Deploy.** Run `npx vercel deploy --prod --yes` in that folder.
   - Not logged in? Ask the user to run `npx vercel login` once (or set `VERCEL_TOKEN` and add `--token "$VERCEL_TOKEN"`).
   - The `vercel` MCP tools can list projects, deployments and build logs — use them when a deploy fails.
3. **Check it live.** With the `chrome-devtools` MCP tools: open the public URL, take a screenshot, and read console errors and failed network requests. Also check a phone-sized viewport (375px wide).
4. **Fix and repeat** until the page has no console errors and looks right.
5. **Report** the public URL and the screenshot to the user.
