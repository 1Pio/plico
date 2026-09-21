// Copyright 2026 The plico Authors
// SPDX-License-Identifier: GPL-3.0-only
#include "plico/core/gesture_router.h"

#include <cstdio>
#include <cstdlib>

#define CHECK(condition) do { if (!(condition)) { \
  std::fprintf(stderr, "%s:%d: %s\n", __FILE__, __LINE__, #condition); \
  std::abort(); } } while (false)

using namespace plico;
struct Fixture {
  NavigatorModel model;
  GestureRouter router{model};
  Fixture() {
    Layout layout;
    layout.loose = {1, 2, 3};
    CHECK(model.Reset(layout, 3, {3, 1, 2}));
  }
};

void DelayAndOrdinaryCopy() {
  Fixture f;
  f.router.ModifiersChanged(kCommand, 0);
  f.router.RevealIfDue(149);
  CHECK(f.model.mode() == Mode::kHidden);
  f.router.RevealIfDue(150);
  CHECK(f.model.mode() == Mode::kCommandHold && f.model.active() == 3);
  CHECK(!f.router.ModifiersChanged(0, 160).commit);
  CHECK(f.model.mode() == Mode::kHidden);
  f.router.ModifiersChanged(kCommand, 200);
  CHECK(!f.router.KeyDown(Action::kOther, kCommand).consumed);
  f.router.RevealIfDue(999);
  CHECK(f.model.mode() == Mode::kHidden);
  CHECK(!f.router.ModifiersChanged(0, 1000).commit);
}

void ImmediateAndCancel() {
  Fixture f;
  f.router.ModifiersChanged(kCommand, 0);
  CHECK(f.router.KeyDown(Action::kLeft, kCommand).consumed);
  CHECK(f.model.candidate() == 2 && f.model.active() == 3);
  f.router.KeyDown(Action::kLeft, kCommand);
  auto result = f.router.ModifiersChanged(0, 15);
  CHECK(result.commit && result.commit->activate == 1);
  CHECK(f.model.active() == 3 && !f.router.ModifiersChanged(0, 16).commit);

  f.router.ModifiersChanged(kCommand, 100);
  f.router.KeyDown(Action::kLeft, kCommand);
  CHECK(!f.router.KeyDown(Action::kOther, kCommand).consumed);
  CHECK(f.model.mode() == Mode::kHidden);
  CHECK(!f.router.ModifiersChanged(0, 101).commit && f.model.active() == 3);
}

void LatchAndBareTap() {
  Fixture f;
  f.router.ModifiersChanged(kCommand, 0);
  f.router.KeyDown(Action::kToggle, kCommand);
  f.router.KeyDown(Action::kToggle, kCommand, true);
  CHECK(f.model.mode() == Mode::kLatched);
  CHECK(!f.router.ModifiersChanged(0, 100).commit);
  f.router.ModifiersChanged(kCommand, 200);
  f.router.KeyDown(Action::kLeft, kCommand);
  CHECK(!f.router.ModifiersChanged(0, 210).commit);
  CHECK(f.model.mode() == Mode::kLatched && f.model.candidate() == 2);
  CHECK(!f.router.ModifiersChanged(kCommand, 300).commit);
  auto result = f.router.ModifiersChanged(0, 310);
  CHECK(result.commit && result.commit->activate == 2);

  f.router.ModifiersChanged(kCommand, 400);
  f.router.KeyDown(Action::kToggle, kCommand);
  f.router.ModifiersChanged(0, 410);
  f.router.ModifiersChanged(kCommand, 500);
  CHECK(!f.router.KeyDown(Action::kOther, kCommand).consumed);
  CHECK(!f.router.ModifiersChanged(0, 510).commit);
}

void ModeOwnershipAndMoveRollback() {
  Fixture f;
  f.router.ModifiersChanged(kCommand, 0);
  f.router.ModifiersChanged(kCommand | kShift, 1);
  f.router.RevealIfDue(200);
  CHECK(f.model.mode() == Mode::kHidden);
  f.router.KeyDown(Action::kRight, kCommand | kShift);
  CHECK(f.model.visible().stacks[0] == std::vector<TabId>{3});
  f.router.KeyDown(Action::kToggle, kCommand);
  CHECK(f.model.mode() == Mode::kLatched && f.model.visible().stacks[0].size() == 1);
  f.router.ModifiersChanged(kControl, 300);
  f.router.KeyDown(Action::kRecent, kControl);
  CHECK(f.model.mode() == Mode::kRecentHold && f.model.candidate() == 1);
  CHECK(f.model.visible().stacks[0].empty());
  CHECK(!f.router.ModifiersChanged(kControl | kShift, 310).commit);
  f.router.KeyDown(Action::kRecent, kControl | kShift);
  CHECK(f.model.candidate() == 3);
  auto result = f.router.ModifiersChanged(kShift, 320);
  CHECK(result.commit && result.commit->activate == 3);
}

void ComposerFocusAndCancellation() {
  Fixture f;
  f.router.ModifiersChanged(kCommand, 0);
  f.router.KeyDown(Action::kLeft, kCommand);
  auto result = f.router.KeyDown(Action::kNewDestination, kCommand);
  CHECK(result.host_action == HostAction::kNewDestination && !result.commit);
  CHECK(f.model.mode() == Mode::kHidden);
  f.router.SetEditorOwnsInput(true);
  f.router.ModifiersChanged(0, 100);
  f.router.ModifiersChanged(kCommand, 200);
  f.router.RevealIfDue(400);
  CHECK(f.model.mode() == Mode::kHidden);
  CHECK(!f.router.KeyDown(Action::kLeft, kCommand).consumed);
  f.router.SetEditorOwnsInput(false);
  f.router.ModifiersChanged(0, 500);
  f.router.ModifiersChanged(kCommand, 600);
  f.router.Cancel();
  f.router.RevealIfDue(900);
  CHECK(f.model.mode() == Mode::kHidden);
  CHECK(!f.router.ModifiersChanged(0, 901).commit);
}

void RemappedModifierOwnership() {
  Fixture f;
  f.router.ModifiersChanged(kControl, 0);
  CHECK(!f.router.KeyDown(Action::kLeft, kControl).commit);
  CHECK(f.model.candidate() == 2 && f.model.active() == 3);
  f.router.ModifiersChanged(kControl | kCommand, 0);
  CHECK(!f.router.ModifiersChanged(kControl, 0).commit);
  auto result = f.router.ModifiersChanged(0, 1);
  CHECK(result.commit && result.commit->activate == 2);
  CHECK(!f.router.ModifiersChanged(0, 2).commit);

  f.router.ModifiersChanged(kCommand, 3);
  f.router.KeyDown(Action::kRecent, kCommand);
  CHECK(f.model.candidate() == 1 && f.model.active() == 3);
  result = f.router.ModifiersChanged(0, 4);
  CHECK(result.commit && result.commit->activate == 1);
}

void RemappedUnmodifiedKeysCommitOnce() {
  Fixture f;
  auto result = f.router.KeyDown(Action::kLeft, 0);
  CHECK(result.commit && result.commit->activate == 2);
  CHECK(f.model.mode() == Mode::kHidden && f.model.active() == 3);
  CHECK(!f.router.ModifiersChanged(0, 1).commit);
  result = f.router.KeyDown(Action::kRecent, 0);
  CHECK(result.commit && result.commit->activate == 1);
  CHECK(f.model.mode() == Mode::kHidden);
}

void PointerStackCommitsOnce() {
  Fixture f;
  Layout layout;
  layout.loose = {1};
  layout.stacks[0] = {2, 3};
  layout.last_active[0] = 3;
  CHECK(f.model.Reset(layout, 1, {1, 3, 2}));
  f.router.ModifiersChanged(kCommand, 0);
  f.router.RevealIfDue(150);
  CHECK(!f.router.PointerSelectStack(0).commit);
  CHECK(f.model.candidate() == 3 && f.model.active() == 1);
  auto result = f.router.ModifiersChanged(0, 151);
  CHECK(result.commit && result.commit->activate == 3);
  CHECK(!f.router.ModifiersChanged(0, 152).commit);
  f.router.KeyDown(Action::kToggle, 0);
  result = f.router.PointerSelectStack(0);
  CHECK(result.commit && result.commit->activate == 3);
  CHECK(f.model.mode() == Mode::kHidden);
}

int main() {
  DelayAndOrdinaryCopy();
  ImmediateAndCancel();
  LatchAndBareTap();
  ModeOwnershipAndMoveRollback();
  ComposerFocusAndCancellation();
  RemappedModifierOwnership();
  RemappedUnmodifiedKeysCommitOnce();
  PointerStackCommitsOnce();
  std::puts("8 modifier-routing scenarios passed");
}
