# Plico development

Preserve installed browsers, their profiles, and unrelated work. This repository
is the authorized public registered fork of Helium. Use the personal GitHub
identity and retain upstream attribution and licenses. Stagehand is deferred.

## Build resource limits

The development Mac has 24 GB RAM. An earlier build exhausted application memory.
Blink's Python binding generator creates a separate multiprocessing pool based
on CPU count, independent of the outer build job count.

- Use `scripts/build.sh` for compilation. It defaults to one local job and wraps
  the entire build tree in `scripts/memory-guard.py`. The user authorized measured
  parallelism increases: `PLICO_BUILD_JOBS=2`, then at most 3 after observing
  stable memory and swap. Do not raise memory thresholds to make a trial fit.
  Use explicit Siso `-local_jobs`, because autoninja may ignore `-j > 1` under
  the required `PYTHON_CPU_COUNT=1` generator safeguard.
- Keep `PYTHON_CPU_COUNT=1`, Node's heap limit at 2048 MiB, and the guard active.
  Verify that Siso propagates the Python limit before resuming Blink generation.
- Keep GRIT's supported serial mode (`GRIT_DISABLE_MULTIPROCESSING=1`), Go's
  soft GC target (`GOMEMLIMIT=1536MiB`) and one Siso state-compression thread.
  A second guarded stop occurred during resource generation despite one outer
  job; GRIT otherwise forks a resource-tree copy even with one Python worker.
- Siso has separate compiler and action pools. The current generated build keeps
  actions, links and bundles at capacity one when compiler concurrency increases.
  Verify those capacities in `out/Default/siso.INFO` after changing build config.
  The aggregate footprint guard covers all pools and nested processes. Do not
  interpret local jobs as a strict total-process limit.
- Stop the owned build if its physical footprint exceeds 6 GiB, the ChatGPT/Codex
  process family exceeds 14 GiB, system free
  memory drops below 35%, or swap grows by more than 512 MiB. Start only above
  45% free memory. Logs stay in ignored `build/logs/`.
- Do not bypass the guard with `dev.sh`, `he`, `autoninja`, or direct Siso builds.
  Narrow compiler checks must be sequential and lightweight or guarded too.
- A memory-limit stop preserves incremental output. Investigate the concrete
  allocation before retrying; do not automatically loop or raise the limit.
- Do not kill or restart ChatGPT or unrelated apps to make room for the build.

## Proof boundaries

Host model tests and source-level checks do not qualify real browser behavior.
Keep the current status in `docs/IMPLEMENTATION.md`. Use isolated profiles through
`scripts/run-isolated.sh`; those profiles use a development mock keychain and are
not intended for personal browsing. Do not publish a browser release until the
native acceptance and upstream-update rehearsal have passed.
