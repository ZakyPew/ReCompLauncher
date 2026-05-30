# Contributing to ReComp Launcher

Thanks for helping out! 🎮

## The easiest, most valuable contribution: add a recomp

ReComp Launcher recognizes games by their executable via a fingerprint database.
Adding a new recomp is usually a **single dictionary entry**.

1. Open [`recomplauncher.py`](recomplauncher.py) and find the `KNOWN_RECOMPS` list near the top.
2. Add an entry following this shape:

```python
{
    # exact executable filenames, lowercase
    "names": ["yourgame.exe"],
    # fuzzy substrings matched against the exe name AND its parent folder
    # (catches versioned build dirs like "YourGame-v1.0.0-windows-x64/")
    "patterns": ["yourgamerecomp"],
    "title": "Full Official Game Title",
    "platform": "Project / Port Name",
    "search": "Title used for Wikipedia/SteamGridDB lookup",
    "github_repo": "owner/repo",   # enables update checks + one-click download
    "tags": ["Series", "Console"],
},
```

### Guidelines

- **Verify the repo and exe name** before submitting. The exe name comes from the
  project's actual release/build output — check its GitHub Releases page. A wrong
  exe just won't match (harmless), but a wrong repo breaks update checks.
- **Order matters:** put specific entries *before* generic ones (e.g. a co-op fork
  before the base game), since the first match wins.
- **Keep patterns specific** to avoid false matches with unrelated games that share
  a common word.
- One game per entry. If a project ports multiple games, add one entry each.

## Running from source

```bash
pip install -r requirements.txt
python recomplauncher.py
```

## Code style

- Single-file app by design — keep it approachable.
- Match the surrounding style (standard library + PyQt6 + requests, no heavy deps).
- Test that the app still launches before opening a PR.

## Reporting bugs / requesting games

Open an issue. For a game request, include the GitHub repo and the Windows
executable name if you know them.
