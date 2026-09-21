// Copyright 2026 The plico Authors
// SPDX-License-Identifier: GPL-3.0-only
#include "plico/core/gesture_router.h"

#include <algorithm>

namespace plico {

void GestureRouter::Cancel() {
  deadline_.reset();
  command_bare_ = false;
  latch_tap_ = false;
  selection_action_ = false;
  gesture_owner_ = 0;
  model_.Cancel();
}

void GestureRouter::SetEditorOwnsInput(bool owns) {
  if (owns) Cancel();
  editor_ = owns;
}

void GestureRouter::SetRevealDelay(int milliseconds) {
  reveal_delay_ = std::clamp(milliseconds, 0, 2000);
}

GestureResult GestureRouter::PointerSelect(TabId tab) {
  GestureResult result;
  if (!model_.Select(tab)) return result;
  result.consumed = true;
  selection_action_ = true;
  if (model_.mode() == Mode::kLatched) result.commit = model_.CommitSelection();
  return result;
}

GestureResult GestureRouter::PointerSelectStack(int slot) {
  if (!model_.SelectStack(slot) || !model_.candidate()) return {};
  return PointerSelect(*model_.candidate());
}

GestureResult GestureRouter::ModifiersChanged(unsigned modifiers,
                                               std::int64_t now) {
  GestureResult result;
  const unsigned previous = modifiers_;
  modifiers_ = modifiers;
  if (gesture_owner_ && (previous & gesture_owner_) && !(modifiers & gesture_owner_) &&
      (model_.mode() == Mode::kCommandHold || model_.mode() == Mode::kRecentHold)) {
    if (selection_action_ || model_.mode() == Mode::kRecentHold)
      result.commit = model_.CommitSelection();
    else model_.Cancel();
    gesture_owner_ = 0;
    selection_action_ = false;
  }
  if ((previous & kCommand) && !(modifiers & kCommand)) {
    deadline_.reset();
    if (model_.mode() == Mode::kLatched && latch_tap_ && command_bare_) {
      result.commit = model_.CommitSelection();
    }
    command_bare_ = false;
    latch_tap_ = false;
    if (model_.mode() == Mode::kHidden) selection_action_ = false;
  }
  if (!(previous & kCommand) && (modifiers & kCommand)) {
    command_bare_ = modifiers == kCommand && !editor_;
    latch_tap_ = command_bare_ && model_.mode() == Mode::kLatched;
    if (command_bare_ && model_.mode() == Mode::kHidden)
      deadline_ = now + reveal_delay_;
  }
  if (modifiers != kCommand) {
    deadline_.reset();
    command_bare_ = false;
  }
  return result;
}

void GestureRouter::RevealIfDue(std::int64_t now) {
  if (!deadline_ || now < *deadline_) return;
  deadline_.reset();
  if (!editor_ && command_bare_ && modifiers_ == kCommand &&
      model_.mode() == Mode::kHidden) {
    model_.Begin(Mode::kCommandHold);
    gesture_owner_ = kCommand;
  }
}

GestureResult GestureRouter::KeyDown(Action action, unsigned modifiers,
                                     bool repeat, int stack) {
  GestureResult result;
  modifiers_ = modifiers;
  deadline_.reset();
  command_bare_ = false;
  latch_tap_ = false;
  if (editor_) return result;

  if (action == Action::kNewDestination || action == Action::kEditURL ||
      action == Action::kCopyURL) {
    Cancel();
    result.consumed = true;
    if (!repeat) {
      result.host_action = action == Action::kNewDestination
          ? HostAction::kNewDestination : action == Action::kEditURL
          ? HostAction::kEditURL : HostAction::kCopyURL;
    }
    return result;
  }
  if (action == Action::kOther) {
    Cancel();
    return result;  // Original event reaches the real page exactly once.
  }
  if (action == Action::kEscape) {
    result.consumed = model_.mode() != Mode::kHidden;
    Cancel();
    return result;
  }
  if (action == Action::kToggle) {
    result.consumed = true;
    gesture_owner_ = 0;
    if (!repeat) {
      if (model_.mode() == Mode::kLatched)
        result.commit = model_.CommitSelection();
      else model_.Latch();
    }
    return result;
  }
  if (action == Action::kRecent) {
    result.consumed = true;
    if (model_.mode() != Mode::kRecentHold) {
      model_.Begin(Mode::kRecentHold);
      gesture_owner_ = modifiers & kControl ? kControl : modifiers & kCommand ? kCommand
          : modifiers & kOption ? kOption : 0;
    }
    model_.StepRecent(modifiers & kShift ? -1 : 1);
    if (!gesture_owner_) result.commit = model_.CommitSelection();
    return result;
  }
  if (action == Action::kAccept) {
    result.consumed = model_.mode() == Mode::kLatched;
    if (result.consumed && !repeat) result.commit = model_.CommitSelection();
    return result;
  }
  if (model_.mode() != Mode::kLatched && model_.mode() != Mode::kCommandHold) {
    model_.Begin(Mode::kCommandHold);
    gesture_owner_ = modifiers & kCommand ? kCommand : modifiers & kControl ? kControl
        : modifiers & kOption ? kOption : 0;
  }
  result.consumed = true;
  selection_action_ = true;
  const bool move = modifiers & kShift;
  switch (action) {
    case Action::kLeft:
    case Action::kRight: {
      const int direction = action == Action::kLeft ? -1 : 1;
      if (move) model_.MoveHorizontal(direction);
      else model_.SelectHorizontal(direction);
      break;
    }
    case Action::kUp:
    case Action::kDown: {
      const int direction = action == Action::kUp ? -1 : 1;
      if (move) model_.MoveVertical(direction);
      else model_.SelectVertical(direction);
      break;
    }
    case Action::kStack:
      if (move) model_.MoveToStack(stack);
      else model_.SelectStack(stack);
      break;
    default: break;
  }
  if (!gesture_owner_ && model_.mode() == Mode::kCommandHold)
    result.commit = model_.CommitSelection();
  return result;
}

}  // namespace plico
