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
| Pure navigation model and input routing | 18 host scenarios pass with ASan and UBSan |
| Native build and UI | Patched upstream and native objects compile; integrated Plico build in progress; no running plico UI yet |
| Modifier input, latch and MRU integration | Native source drafted and compiler-checked; runtime qualification pending |
| Native stack view and persistence | Native source and session hooks drafted; runtime qualification pending |
| Floating composer | Native source drafted and compiler-checked; runtime qualification pending |
| Native Glance and promotion | Native WebContents preview, same-instance promotion and trusted link routing drafted and compiler-checked; runtime qualification pending |
| Per-tab debugger status and stop | Native status/stop source compiler-checked; attachment policy patch drafted; runtime qualification pending |
| Shortcut editing and back-to-opener behavior | Editable bindings and capture suppression drafted; upstream back-to-opener found; runtime qualification pending |
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

All subsequent builds use `scripts/build.sh`: conservative local parallelism,
`PYTHON_CPU_COUNT=1`, a 2048 MiB Node heap cap, and a native macOS physical-footprint
monitor over the build's process group and descendants. The guard stops at
6 GiB build footprint, 14 GiB total ChatGPT/Codex process-family footprint,
below 35% free system memory, or over 512 MiB new swap. A lock prevents two guarded
operations from compiling concurrently in the same build directory. If the host
app exits, its guarded build stops.
It requires at least 45% free memory before starting. It signals only identified build processes and their owned process groups, and
preserves incremental output. Retained process start identities cover observed
workers that create separate groups. Sampling runs once per second; this is a
stop mechanism, not a kernel-enforced allocation cap or a sandbox for daemonizing
programs.

A subsequent guarded resource-generation run stopped at 6,561 MiB of build
footprint, before system free memory fell below 64%. All owned workers exited
and incremental output was retained. Siso's log confirmed one local job. The
GRIT implementation still forks a copy of its parsed resource tree with one
Python worker, so builds now set its supported
`GRIT_DISABLE_MULTIPROCESSING=1`. Go's soft GC target is 1,536 MiB and Siso state
compression uses one thread. The original limits remain unchanged. Stop records
now include per-process executable paths and footprints, without command
arguments. The nine guard tests and a real Siso environment probe pass. The
interrupted components resource target then completed in 6.7 seconds under the
same thresholds, with approximately 1.4 GiB maximum sampled build footprint.
This does not establish a bound for every remaining build action.
Siso reports separate compiler and action pools; they can overlap. The aggregate
guard covers both and their child processes. In the two-job trial, Siso confirms
local concurrency two while action, link and bundle pools retain capacity one.

Nine low-memory process tests pass, covering normal exit, low-threshold stop,
SIGINT/SIGTERM/SIGHUP cleanup, surviving detached workers, discovery failure, and
PID reuse, the app-family threshold, and exclusive build locking. The Python CPU
limit also reached an actual Siso action. Independent
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

### Current integration evidence

The generated downstream patch touches 46 upstream files. Applying and reversing
it on isolated snapshots passes. Three patch-runner regression scenarios verify
idempotence, replacing a patch that drops old changes, and preserving local edits.
This is patch validation, not the upstream-update rehearsal.

Seven native translation units pass serial syntax checks with the pinned Chromium
compiler and generated headers. The downstream patch is applied to the isolated
source and GN has generated 32,360 targets. Regenerating the patch after applying
it produces identical bytes. The nine selected native/renderer objects compiled
with 347 prerequisite actions in 3 minutes 30 seconds, including generated Mojo
interfaces and Blink's Option-click route. The other 14 patched upstream objects
then compiled with their prerequisites in 49 seconds. This covers BrowserView,
AppKit dispatch, session and tab restoration, shortcuts, navigation delegation,
debugger attachment policy, profile path and keychain code. Sparkle is excluded
by this development configuration's disabled updater. The full application,
linking, packaging and settings TypeScript qualification remain incomplete.
The staging UI remains behind `--plico-native-navigation`; Glance link routing
also needs `--enable-blink-features=PlicoGlance`. Existing browser profiles are
untouched. A complete unmodified baseline build remains an open comparison gate.

The native Glance draft retains normal popup checks and navigation parameters.
A marked trusted Option-click travels explicitly from Blink to the browser;
browser-owned frame sandbox flags are retained when creating the preview.
Independent review caught an initiator-frame mismatch and a replacement path
that lost asynchronous beforeunload completion. Both were corrected and
re-reviewed. Promotion transfers the existing WebContents into the parent tab
strip. This is source evidence; beforeunload, sandbox behavior, state-preserving
promotion, native window focus and renderer integration still need real runtime
tests.

Plico's normal staging window uses Helium's hidden chrome layout without changing
profile preferences. Security and permission surfaces can still reveal native
chrome, while Glance retains an origin toolbar. Session metadata writes are
deferred only in a window receiving explicitly marked restored tabs, until its
synchronous insertion loop finishes. A profile-wide suppression was rejected
because it could discard live edits in an unrelated window. Both paths require
runtime proof.

Independent review found and fixed stack-click commit bookkeeping, stale closed
tab selection in the composer, and URL editing losing its original tab identity.
The closed-target state now has no implicit replacement selection. The stack-click
fix and remapped gesture modifier ownership have host regression coverage.
Native composer behavior still requires execution in the actual browser.

A second review caught profile-wide restore suppression, stale modifier state
after composer dismissal, and Command+T retaining URL-edit mode. The fixes use
window-local restore reconciliation, synchronize modifier changes received by
child/other windows, and explicitly transition from URL editing to new search.
The affected native units pass serial compiler checks and the follow-up source
review found no new concrete defect. Native acceptance is still unexecuted.

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

## Parallelism calibration, 2026-09-21

The user authorized safely increasing compilation parallelism, retaining all
memory safeguards. The wrapper accepts
explicit values 1 through 3. It now passes Siso's `-local_jobs` directly: the
upstream autoninja conversion can ignore `-j 2` when `PYTHON_CPU_COUNT=1`. The
generator CPU limit, GRIT serial mode, heap limits, one-second footprint guard,
exclusive lock and stop thresholds are unchanged. Trial results are recorded
below before choosing unattended concurrency.

The two-job trial completed 171 actions in 4m12s before a deliberate graceful
stop for the next trial (zero failed actions). Across 250 seconds of guard
samples, build footprint peaked at 4,073 MiB; host-family footprint peaked at
11,343 MiB; system free percentage stayed at 71% or higher; swap stayed at
7,867.25 MiB. Siso confirmed local capacity two and action/link/bundle capacity
one. Four new wrapper regression scenarios pass, covering supported job counts,
rejection of unsafe values, rejection of flag overrides in target arguments, and
preservation of the memory guard for narrow targets. These are short calibration
results, not a guaranteed memory bound for later Chromium units.

The three-job trial started at 2026-09-21 17:50:44 UTC; its log is
`build/logs/plico-full-build-jobs3.log`. Aggregate telemetry stays in
`build/logs/build-memory.jsonl`. Siso confirms local capacity three and
action/link/bundle capacity one. Neither the guard nor its thresholds changed.
Source overlays must not be applied while compilation runs.

Upstream remains at `0.17.2.1` on 2026-09-21. After native acceptance, rehearse
a real older-to-current release transition if no newer release exists; do not
confuse a same-revision patch roundtrip with an upgrade. The previous release
is `0.17.1.1`. Keep separate source/build/profile state and account for disk
capacity before preparing that comparison.

The three-job trial completed 181 actions in 3m55s with zero failed actions
before a deliberate stop. Sampled build footprint reached 5,706 MiB and the
host family reached 12,915 MiB. Free memory stayed at or above 66% and swap
remained unchanged. That leaves little headroom below the 6,144 MiB build limit,
so two local jobs are now the wrapper default and the selected unattended setting.
Three remains available only for attended calibration. These trials covered
different engine units, so their action rates do not measure a speedup ratio.

The active build resumed at approximately 2026-09-21 17:55 UTC in
`build/logs/plico-full-build-balanced.log` (tool session 60127). This is the log
to inspect next. All incremental outputs were retained across the controlled
restarts. Inspect memory telemetry and owned processes before any intervention;
a guard stop must be investigated, not blindly retried. Siso's action counter
changes as cached actions are resolved and does not give a reliable percent of
wall-clock work remaining. There is still no launched Plico browser.

On completion, stop compilation before starting the guarded, isolated runtime
qualification described in `docs/NATIVE-ACCEPTANCE.md`. Prioritize the visible
navigation interaction and measure one small edit/rebuild/relaunch cycle before
expanding implementation. The user authorized scheduled continuations of this
task, but paid cloud provisioning still needs approval.


## Resource stop and checkpoint reuse investigation, 2026-09-21 20:00 UTC

The earlier active-build paragraph is superseded. The two-job balanced build
stopped at 19:22 UTC after about 1h27m, with 6,866 actions completed in that run.
The guard recorded 34% free memory against its 35% floor. Build physical
footprint was 5,291 MiB, the app family was 13,535 MiB, and swap was 7,795 MiB
without recent growth. This was a resource stop, not an established compiler
failure. Existing incremental output is retained. No compiler has been restarted.

With the build stopped, the kernel still reports memorystatus level 2, which
Apple's XNU definition calls Urgent (equivalent to Warning), and the desktop
app family accounts for roughly 9.5 GiB of physical footprint. Current samples
are in ignored `build/logs/checkpoint-latest.json`. Fan noise and observed build
usage do not establish available RAM or a safe compiler-job maximum. The 6 GiB
build ceiling and 14 GiB app-family ceiling are stop thresholds, not reserved
allocations. None of the existing thresholds were raised.

A public upstream ARM64 checkpoint exists for the exact pinned platform commit:
[successful run 35283975532](https://github.com/imputnet/helium-macos/actions/runs/35283975532),
artifact 10534986217, 6,867,963,157 bytes. Its ZIP directory contains a
`build_src.tar.zst` of 6,876,100,218 bytes. The expected ZIP SHA256 is
`d777ec2fafb4be162babbdf7c7b1b01210fb559940e763cca00fca7fba999ce2`.
The packaging script archives `build/src`; the actual object inventory and
successful reuse are still unverified until inspection completes.

The production checkpoint uses official/noncomponent output, PGO phase 2,
symbol level 1, sccache, and Xcode 26.0.1. Our component development build uses
PGO 0, symbols 0, disabled PCH and Xcode 26.5. Do not copy these outputs over our
current build. Reuse would need a separately qualified compatible production
configuration, including SDK/toolchain paths and the eventual link footprint.
The upstream run used Depot macOS runners; its throughput is not evidence for
the free standard GitHub macOS runner or this Mac's safe concurrency.

`scripts/inspect-upstream-checkpoint.py` streams and inventories the pinned
archive, retains only allowlisted build metadata, and never restores its source
or executes archive content. A fixture verified file/object counts, selected
metadata and ignored symlinks. A manual free Ubuntu workflow is committed, but
Actions remains disabled: automatic approval review rejected enabling an
unrestricted action policy, and restricted enablement is awaiting user approval.
Local inspection continues independently using four bounded network streams;
tool session 77908 and `build/reuse-qualification/fetch-inspection.log` are the
current inspection handles. Check this job before starting a duplicate fetch.

After inspection, choose between a compatible checkpoint and the preserved local
component build. To qualify more compiler jobs, first prepare build supervision
that survives a desktop-app restart while retaining process ownership, global
pressure/swap checks, serial generators and an aggregate build/app budget.
Do not merely detach the current wrapper: its interactive guard deliberately
stops when its supervising app exits. Do not kill the desktop app or unrelated
processes. No cache speedup, increased compiler concurrency or running Plico UI
has been demonstrated by this investigation.


At 20:31 UTC, the local checkpoint fetch had exited after a network connection
reset. Its journal records 1,425,620,992 completed bytes; the larger partial-file
size does not prove other ranges completed. Keep that file and journal for a
possible range-based retry. No source outputs were replaced. Kernel pressure
remains level 2 and free-memory percentage 40, so no compiler was restarted.

The user explicitly approved app-independent guarded compilation before the next
build and permits a restricted free GitHub Actions inspection attempt. Standard
public-repository runners are exempt from the private-repository minutes quota
according to current GitHub billing documentation. The inspection workflow now
retains its report in job logs rather than uploading artifacts, avoiding storage
quota usage. Keep inherited workflows disabled, permit only its required
checkout action, and do not provision paid runners. Actual runner acceptance
must be checked; the billing documentation alone does not prove this account
will execute the job.


At 20:34 UTC, restricted Actions enablement was verified following explicit user
approval. Only `actions/checkout@v4` is allowed, with GitHub-owned/verified blanket
permissions disabled and all inherited workflows disabled manually. The free
standard Ubuntu inspection [run 35651919829](https://github.com/1Pio/plico/actions/runs/35651919829)
started successfully despite the reported exhausted personal minutes allowance.
This proves runner acceptance, not successful inspection or cache reuse. Check
its job logs next; the workflow uploads no artifacts and writes no Actions cache.
The user also explicitly confirmed that the next local compilation must run
independently of ChatGPT and qualify more workstation capacity within physical
memory limits. Compilation remains stopped; no resource thresholds changed.
