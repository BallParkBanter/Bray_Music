# Transition: Bray Music Studio from nextcloud-mcp to Bray_Music

**Date:** 2026-03-05

## What happened

All Bray Music Studio development was previously done from the `~/projects/nextcloud-mcp/` project directory (since that's where the MCP server for Nextcloud lives, and BMS uses Nextcloud APIs for cover art). The code lived on ROG-STRIX without version control, and all session memories, plans, and context were stored under the nextcloud-mcp project.

On 2026-03-05, everything was reorganized into its own project.

## What moved where

| From | To |
|------|-----|
| ROG-STRIX `/home/bobray/ace-step/ui/` (unversioned) | `~/projects/Bray_Music/ui/` (git tracked) |
| ROG-STRIX `/home/bobray/ace-step/docker-compose.yml` | `~/projects/Bray_Music/docker-compose.yml` |
| ROG-STRIX `/home/bobray/ace-step/validate.py` | `~/projects/Bray_Music/validate.py` |
| nextcloud-mcp memory `ace-step-validation.md` | `Bray_Music/docs/ace-step-validation.md` |
| nextcloud-mcp memory `bms-quality-findings.md` | `Bray_Music/docs/quality-findings.md` |
| BMS content in nextcloud-mcp `MEMORY.md` | `Bray_Music` project memory `MEMORY.md` |

## What stays the same

- **Deployment location:** ROG-STRIX `/home/bobray/ace-step/` (unchanged)
- **Live URL:** https://music.apps.bray.house (unchanged)
- **NPM proxy host 37** (unchanged)
- **ACE-Step native install** at `/home/bobray/ACE-Step-1.5/` (unchanged)
- **Cover art** now uses local Juggernaut XL service on ROG-STRIX (replaced Nextcloud/Visionatrix 2026-03-05)

## New project structure

```
~/projects/Bray_Music/          <- Source of truth (git repo)
├── CLAUDE.md                   <- Full project reference
├── docker-compose.yml
├── validate.py
├── whisper_service.py          <- Whisper validation service (NEW)
├── whisper-service.service     <- systemd unit (NEW)
├── AS-BUILT.md
├── plans/
│   ├── 001-initial-deployment.md
│   └── 002-validation-params-remix.md
├── docs/
│   ├── acestep-as-built.md
│   ├── custom-ui-design.md
│   ├── ace-step-validation.md       <- moved from nextcloud-mcp memory
│   ├── quality-findings.md          <- moved from nextcloud-mcp memory
│   ├── nextcloud-mcp-memories-export-2026-03-05.md  <- full memory dump
│   └── transition-from-nextcloud-mcp.md  <- this file
├── mockup/
│   └── (design HTML files)
└── ui/
    ├── (all Python source + static HTML)
    └── tests/
```

## Git remotes

```
origin  ssh://git@192.168.1.145:2222/bobray/Bray_Music.git  (Gitea)
github  git@github.com:BallParkBanter/Bray_Music.git        (GitHub)
```

## How to work on BMS going forward

```bash
cd ~/projects/Bray_Music
claude
```

Claude Code will automatically load `CLAUDE.md` and the project memory from
`~/.claude/projects/-home-bobray-projects-Bray_Music/memory/MEMORY.md`.

## Deploy workflow

```bash
# After making changes locally:
scp ui/changed_file.py bobray@192.168.1.153:/home/bobray/ace-step/ui/
ssh bobray@192.168.1.153 "cd /home/bobray/ace-step && docker compose build --no-cache ui && docker compose up -d ui"

# Push to remotes:
git add -A && git commit -m "description"
GIT_SSH_COMMAND="ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null" git push origin main
git push github main
```

## Gotcha: scp -r sometimes fails silently

During this migration, `scp -r ui/ host:/path/ui/` appeared to succeed but didn't actually overwrite all files. The Docker build used cached layers with stale code. Always either:
- Use explicit per-file `scp` for changed files, OR
- Verify with `grep` on the remote that your changes are present
- Use `docker compose build --no-cache ui` after deploying
