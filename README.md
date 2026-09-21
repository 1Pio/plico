# plico

plico ("PLEE-koh") is an experimental macOS browser fork of
[Helium](https://github.com/imputnet/helium-macos). The name refers to folding
pages into lightweight tab stacks.

This repository is a registered GitHub fork. Helium's history, licenses and
pinned shared-core submodule are retained. The original project README is
preserved in [docs/UPSTREAM-README.md](docs/UPSTREAM-README.md).

**Development status:** build qualification and native interaction development.
There is no qualified plico browser release yet. Standalone model tests are not
evidence that the browser UI works. See [implementation status](docs/IMPLEMENTATION.md).

## Intended interaction

- Page-first window with an on-demand central native navigator.
- Command hold (150 ms) or an immediate navigation chord previews a candidate;
  Command release activates it once.
- H/J/K/L and arrows navigate. Adding Shift previews tab rearrangements as one
  transaction; commit on release, cancel with Escape.
- Loose tabs precede fixed stacks 1-9 and 0 (stack 10). Empty stacks disappear
  without renumbering; singleton stacks are valid.
- Command+B latches navigation. A later bare Command tap or the second toggle
  commits; ordinary copy/paste continues to target the real active page.
- Control+Tab previews a frozen MRU sequence in the same navigator; Control
  release commits. Shift reverses direction.
- Command+T opens a floating search/URL/tab/history/bookmark input. No tab is
  created until submission; switching to a match preserves the existing tab.
- Native Option+click Glance with state-preserving promotion.
- Per-tab debugger attribution and explicit stop controls.

macOS is the current target. Stagehand integration is deferred. Existing Chromium
DevTools/CDP and official browser extensions are the initial automation paths.

## Development

Helium's [build instructions](docs/building.md) describe the upstream toolchain.
The macOS/core revisions are pinned together. Build output, local profiles and
dependency environments stay under the ignored `build/` directory. Do not point
a development build at an installed browser's profile.

Run the platform-independent navigation scenarios on macOS:

```sh
bash scripts/test-model.sh
```

Upstream release/update workflows are disabled on this fork while the build and
distribution path is being qualified. Upstream remotes should be fetch-only.

## License and attribution

Helium-specific and plico-specific code is GPL-3.0-only; imported upstream content
retains its own license. See [LICENSE](LICENSE) and the original source notices.
This project does not claim affiliation with or endorsement by Helium's authors.
