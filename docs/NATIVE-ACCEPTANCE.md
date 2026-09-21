# Native browser acceptance

These are unexecuted acceptance scenarios until evidence is recorded against a
compiled browser. Use only `scripts/run-isolated.sh` profiles. A source check or
renderer-only synthetic key event cannot qualify AppKit input behavior.

Serve the controlled fixtures on loopback from the repository:

```sh
python3 -m http.server 8765 --bind 127.0.0.1 --directory plico/tests/fixtures
PLICO_CDP=1 bash scripts/run-isolated.sh native-acceptance --plico-native-navigation --enable-blink-features=PlicoGlance http://127.0.0.1:8765/
```

Run the browser and server under the resource guard once compilation is stopped.
Use the generated profile's DevToolsActivePort to reach this browser alone.
Before exercising downloads, set CDP Browser.setDownloadBehavior to a directory
under `build/qualification/`. Do not use the installed browser or real profile.
Keep screenshots and probe captures there too. Record the commit and binary
build identity for each run.

## Native input and arrangement

1. Open five distinct fixtures. Hold Command for 149 ms, then past 150 ms. Verify
   hidden before the threshold, visible afterward, no page activation on release.
   A navigation chord at 15 ms must reveal and move immediately.
2. While holding Command, move across two candidates. Capture each page's
   `plicoSnapshot()` and native navigator. Only release may activate the final
   candidate; intermediate pages must receive no new visibility event.
3. Stage several Shift+motions into fixed slots, reorder vertically across a
   boundary, and cancel with Escape. Verify the whole arrangement rolls back.
   Repeat and release to commit; verify empty slots stay hidden, singleton slots
   remain stacks, numbers never change, and remembered stack selection changes
   only after actual activation. Test slot 0 and empty-slot transfers.
4. Latch with Command+B. Opening key release must leave it visible. Test mouse,
   arrows, a later bare Command tap, second toggle, Enter and outside-click
   cancellation. The outside click must not activate a page control underneath.
5. Cycle Control+Tab repeatedly and in reverse while holding Control. Verify a
   frozen MRU order and one activation on release. Add/close a background tab
   during a gesture and verify the documented concurrent-tab behavior.
6. With real page selection and input focus, test ordinary copy/paste/undo while
   the navigator is visible. Confirm the actual page receives each command once.
   Test modifier release in another window, Glance, a sheet and the composer.
   The next bare Command hold must still reveal correctly.
7. Test physical H/J/K/L and arrows on the user's keyboard layout, remapped
   shortcuts, shortcut-capture mode, IME composition, VoiceOver, mouse wheel,
   trackpad, narrow windows, overflow, fullscreen and app deactivation.

## Composer and persistence

1. Command+T must create no tab until submission. Cancel via Escape and outside
   click. Existing-tab matches must select the same stable tab, including duplicate
   URLs in different stacks; close a chosen target before Enter and verify no
   replacement tab appears.
2. Edit tab A's URL with Command+semicolon; activate B through CDP while editing;
   submit and verify the captured target A is navigated. Close A before submitting
   and verify the composer reports the closed target. Command+T from URL editing
   must instead create a new destination; repeated Command+T in new-search mode
   preserves and focuses its draft.
3. Verify default-engine searches, URL input, bookmark/history results, late
   autocomplete updates after arrow selection, clipboard and IME behavior.
4. Restore/reopen windows containing interleaved saved orders, singleton stacks
   and remembered members. Restore another window while making committed edits
   in an existing one; those edits must survive. Repeat after a controlled crash
   of the isolated browser. Check background additions and cross-window moves.

## Glance and agent access

1. Native Option-click the stateful fixture. Increment its counter, type unsaved
   text, add history and scroll. Record `plicoSnapshot()` plus CDP target ID.
   Promote and verify the same values and target ID, with no document reload.
2. Exercise nested previews, Escape, close controls, resize and parent-window
   closure. With beforeunload enabled and real user activation, cancel and accept
   both close and replacement navigation. No unsaved preview may silently vanish.
3. Verify a sandboxed frame with popups denied cannot open Glance. Test inherited
   sandbox restrictions through both preview and promotion. An untrusted synthetic
   Option-click and a link with an explicit download attribute must not take the
   Glance route. Test normal permission prompts and a visible, trustworthy origin.
4. In a linked new tab with no back history, Back must return to its live opener.
   Once history exists, normal Back wins. Verify closed openers and beforeunload.
5. Attach a debugger to one tab while working in another. Verify generic debugger
   attribution, visible Stop, detach/reconnect blocking scoped to that tab, and
   explicit Allow. Test both direct CDP and the official extension when available;
   do not label ordinary DevTools as AI. Stagehand remains deferred.

## Isolation and upstream rehearsal

Verify bundle, process, user-data and keychain identities before any profile
cutover. The Helium updater must not overwrite Plico. The upstream-update gate
requires a newer pinned core/platform pair, successful reapplication, a real
build, and rerunning this acceptance set. Patch-only checks do not pass it.
