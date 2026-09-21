# Implementation and qualification

## Scope

Native macOS plico on the upstream Helium engine and extension platform. Preserve
the installed browser and its data. Stagehand is explicitly deferred. Do not
publish a release until the real native browser has passed the interaction,
restoration, isolation and upstream-update acceptance scenarios.

## Pinned baseline

- macOS upstream: `imputnet/helium-macos`, tag `0.17.2.1`, commit
  `10373c4c5e6b0323b56aa676be8a96f9e12342c1`.
- Helium core submodule: `8c19f4c6d624e31293bca13e655f2fe542ba6fdb`.
- Chromium source version: `153.0.8010.52`.
- GitHub: public registered fork `1Pio/plico`; public visibility was explicitly
  selected because GitHub does not permit private forks of public repositories.

## Progress

| Area | State |
| --- | --- |
| Registered fork and isolated checkout | Verified |
| Build prerequisites and local Python environment | Installed |
| Source retrieval | Pinned Git fallback completed; official lite archive returns HTTP 404 |
| Pure navigation model and input routing | 15 host scenarios pass with ASan and UBSan |
| Native build and UI | Baseline compilation in progress; no running plico UI yet |
| Modifier input, latch and MRU integration | Pending |
| Native stack view and persistence | Pending |
| Floating composer | Pending |
| Native Glance and promotion | Pending |
| Per-tab debugger status and stop | Pending |
| Shortcut editing and back-to-opener behavior | Pending |
| Upstream update rehearsal | Pending |

### Resource incident and enforced limits

The developer reported application-memory exhaustion during baseline preparation
on the 24 GB Mac. The build was stopped immediately and process inspection found
no remaining Plico compiler executables. Reported system free memory recovered
to 75%, subsequently 78%; swap still retained about 9 GiB initially.

The active Blink binding generation step uses `multiprocessing.cpu_count()` for
its own worker pool, independently of Siso's outer job limit. The default on this
host is 15. This is a concrete source of hidden parallelism; the exact peak
allocation per process was not captured before stopping.

All subsequent builds use `scripts/build.sh`: one outer job,
`PYTHON_CPU_COUNT=1`, a 2048 MiB Node heap cap, and a native macOS physical-footprint
monitor over the build's process group and descendants. The guard stops at
6 GiB build footprint, below 35% free system memory, or over 512 MiB new swap.
It requires at least 45% free memory before starting. It signals only identified build processes and their owned process groups, and
preserves incremental output. Retained process start identities cover observed
workers that create separate groups. Sampling runs once per second; this is a
stop mechanism, not a kernel-enforced allocation cap or a sandbox for daemonizing
programs.

Seven low-memory process tests pass, covering normal exit, low-threshold stop,
SIGINT/SIGTERM/SIGHUP cleanup, surviving detached workers, discovery failure, and
PID reuse. The Python CPU limit also reached an actual Siso action. Independent
review exposed cleanup defects; the shutdown, discovery-failure and PID-identity
regressions are now covered. This is evidence
that the protections operate, not a promise that every Chromium compilation unit
will fit. A resource-limit stop requires investigation before another attempt.

### Baseline build findings

The source and toolchain were prepared using upstream's Git fallback, followed
by the core and macOS patch series, substitutions and resources. GN generated
32,356 targets successfully. The local build is an arm64 component build with
symbols disabled to limit development disk use.

Two build prerequisites/configuration problems have been isolated:

1. Xcode's `metal` launcher existed, but its separate toolchain was absent.
   Installing the matching Metal toolchain made the failed ANGLE shader command
   pass. Merely finding the launcher was insufficient verification.
2. The pinned Clang rejects a PCH input when GN supplies `-fmodule-name`.
   A one-line header reproduces the error with the flag and compiles without it.
   This development configuration uses `enable_precompiled_headers = false`.
   Browser source and runtime behavior have not been changed to bypass it.

An independent model review found and reproduced three stack-memory defects:
initial active-tab reconciliation, tentative moves erasing remembered activation,
and delayed activation acknowledgements overwritten by the next layout commit.
The fixes have regression coverage. Host tests also cover MRU wrap, background
additions and removals, latch release separation, editor ownership and canceled
reveal timers. These results do not qualify native AppKit event delivery.

## Qualification contract

Hold, latch and MRU modes share a candidate and one commit operation. A candidate
is never an actual page activation. Only the browser's activation acknowledgement
updates recency and remembered stack selection. Layout preview is transactional.

Model scenarios must cover direction/stack transitions, hidden slots, singleton
stacks, wrapping, cancellation, frozen MRU order and concurrent tab closure or
creation. Native tests must additionally prove physical modifier timing, real
focus/copy preservation, one foreground activation, keyboard layout behavior,
first-responder precedence, scrolling, VoiceOver semantics and app deactivation.

The composer must create no placeholder tab and preserve exact tab identity when
switching. Glance promotion must preserve its WebContents. Restore/reopen/crash
tests must preserve stack membership and committed ordering. Debugger attribution
must distinguish an attached debugger from known agent activity and permit Stop.

The update rehearsal must advance a pinned macOS/core pair, reapply downstream
changes, compile, and rerun runtime acceptance. A clean patch application by itself
does not pass the rehearsal. Keep a rollback copy and isolate test profiles.

## Routine design defaults

- Ten slots per window; separate private-window state.
- Horizontal navigation stops at boundaries; vertical stack navigation wraps.
- URL editing defaults to Command+semicolon; Command+Shift+C copies the actual
  focused page's full URL.
- MRU order freezes per Control hold. Background additions wait until the next
  gesture; closing its candidate cancels the gesture.
- A navigator latch survives the opening Command+B release. Only a later bare
  Command tap, second toggle, Enter or explicit row activation commits.
- The composer owns its text-editing commands. Outside-click dismissal consumes
  the click rather than activating the website underneath.
- No decorative navigation animation; short interruptible overflow scrolling only.
