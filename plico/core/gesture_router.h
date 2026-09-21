// Copyright 2026 The plico Authors
// SPDX-License-Identifier: GPL-3.0-only
#ifndef PLICO_CORE_GESTURE_ROUTER_H_
#define PLICO_CORE_GESTURE_ROUTER_H_

#include <cstdint>
#include <optional>

#include "plico/core/navigator_model.h"

namespace plico {

enum Modifier : unsigned { kCommand = 1, kControl = 2, kShift = 4, kOption = 8 };
enum class Action {
  kOther, kLeft, kRight, kUp, kDown, kStack, kToggle, kRecent,
  kEscape, kAccept, kNewDestination, kEditURL, kCopyURL,
};
enum class HostAction { kNone, kNewDestination, kEditURL, kCopyURL };
struct GestureResult {
  bool consumed = false;
  std::optional<Commit> commit;
  HostAction host_action = HostAction::kNone;
};

// Physical modifier lifecycle, independent of AppKit key mapping. Timestamps
// are monotonic milliseconds supplied by the host. The host schedules a single
// timer at reveal_deadline(), and always rechecks it through RevealIfDue().
class GestureRouter {
 public:
  explicit GestureRouter(NavigatorModel& model) : model_(model) {}
  GestureResult ModifiersChanged(unsigned modifiers, std::int64_t now);
  GestureResult KeyDown(Action action, unsigned modifiers, bool repeat = false,
                        int stack = -1);
  void RevealIfDue(std::int64_t now);
  void Cancel();
  void SetEditorOwnsInput(bool owns);
  void SetRevealDelay(int milliseconds);
  GestureResult PointerSelect(TabId tab);
  GestureResult PointerSelectStack(int slot);
  std::optional<std::int64_t> reveal_deadline() const { return deadline_; }
  bool editor_owns_input() const { return editor_; }

 private:
  NavigatorModel& model_;
  unsigned modifiers_ = 0;
  unsigned gesture_owner_ = 0;
  int reveal_delay_ = 150;
  bool command_bare_ = false;
  bool latch_tap_ = false;
  bool selection_action_ = false;
  bool editor_ = false;
  std::optional<std::int64_t> deadline_;
};

}  // namespace plico
#endif
