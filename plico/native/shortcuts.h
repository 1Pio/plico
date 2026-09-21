// Copyright 2026 The plico Authors
// SPDX-License-Identifier: GPL-3.0-only
#ifndef PLICO_NATIVE_SHORTCUTS_H_
#define PLICO_NATIVE_SHORTCUTS_H_

#include <optional>
#include <string>
#include <utility>
#include <vector>
#include "base/command_line.h"
#include "build/build_config.h"
#include "chrome/app/chrome_command_ids.h"
#include "plico/core/gesture_router.h"
#include "ui/base/accelerators/accelerator.h"
#include "ui/events/event_constants.h"
#include "ui/events/keycodes/keyboard_codes.h"

namespace plico::shortcuts {
inline constexpr int kLeft = 79000, kRight = 79001, kUp = 79002, kDown = 79003;
inline constexpr int kMoveLeft = 79004, kMoveRight = 79005, kMoveUp = 79006, kMoveDown = 79007;
inline constexpr int kToggle = 79008, kRecent = 79009, kRecentReverse = 79010;
inline constexpr int kStack = 79020, kMoveStack = 79040;

inline bool Enabled() {
#if BUILDFLAG(IS_MAC)
  return base::CommandLine::ForCurrentProcess()->HasSwitch("plico-native-navigation");
#else
  return false;
#endif
}

inline std::optional<std::u16string> Label(int command) {
  if (!Enabled()) return std::nullopt;
  switch (command) {
    case kLeft: return u"Navigator: select left";
    case kRight: return u"Navigator: select right";
    case kUp: return u"Navigator: select up in stack";
    case kDown: return u"Navigator: select down in stack";
    case kMoveLeft: return u"Navigator: move tab left";
    case kMoveRight: return u"Navigator: move tab right";
    case kMoveUp: return u"Navigator: move tab up in stack";
    case kMoveDown: return u"Navigator: move tab down in stack";
    case kToggle: return u"Toggle tab navigator";
    case kRecent: return u"Select next recently viewed tab";
    case kRecentReverse: return u"Select previous recently viewed tab";
    case IDC_HIDE_APP: return u"Hide browser";
    default: break;
  }
  for (const int first : {kStack, kMoveStack}) {
    if (command >= first && command < first + 10) {
      const auto number = command - first;
      const auto name = number == 9 ? std::u16string(u"10 (0)")
          : std::u16string(1, static_cast<char16_t>(u'1' + number));
      return (first == kStack ? u"Focus stack " : u"Move tab to stack ") + name;
    }
  }
  return std::nullopt;
}

inline std::vector<std::pair<ui::Accelerator, int>> Defaults() {
  std::vector<std::pair<ui::Accelerator, int>> result;
  auto add = [&](int command, ui::KeyboardCode key, int modifiers) {
    result.emplace_back(ui::Accelerator(key, modifiers), command);
  };
  constexpr int cmd = ui::EF_COMMAND_DOWN, shift = ui::EF_SHIFT_DOWN;
  const ui::KeyboardCode motions[] = {ui::VKEY_H, ui::VKEY_L, ui::VKEY_K, ui::VKEY_J};
  const ui::KeyboardCode arrows[] = {ui::VKEY_LEFT, ui::VKEY_RIGHT, ui::VKEY_UP, ui::VKEY_DOWN};
  for (int i = 0; i < 4; ++i) {
    add(kLeft + i, motions[i], cmd);
    add(kLeft + i, arrows[i], cmd);
    add(kMoveLeft + i, motions[i], cmd | shift);
    add(kMoveLeft + i, arrows[i], cmd | shift);
  }
  for (int i = 0; i < 10; ++i) {
    const auto key = static_cast<ui::KeyboardCode>(i == 9 ? ui::VKEY_0 : ui::VKEY_1 + i);
    add(kStack + i, key, cmd);
    add(kMoveStack + i, key, cmd | shift);
  }
  add(kToggle, ui::VKEY_B, cmd);
  add(kRecent, ui::VKEY_TAB, ui::EF_CONTROL_DOWN);
  add(kRecentReverse, ui::VKEY_TAB, ui::EF_CONTROL_DOWN | shift);
  add(IDC_NEW_TAB, ui::VKEY_T, cmd);
  add(IDC_FOCUS_LOCATION, ui::VKEY_OEM_1, cmd);
  add(IDC_COPY_URL, ui::VKEY_C, cmd | shift);
  return result;
}

struct Route { Action action; bool move = false; bool reverse = false; int slot = -1; };
inline std::optional<Route> Decode(int command) {
  if (command >= kLeft && command <= kMoveDown) {
    constexpr Action actions[] = {Action::kLeft, Action::kRight, Action::kUp, Action::kDown};
    return Route{actions[(command - kLeft) % 4], command >= kMoveLeft};
  }
  if (command >= kStack && command < kStack + 10)
    return Route{Action::kStack, false, false, command - kStack};
  if (command >= kMoveStack && command < kMoveStack + 10)
    return Route{Action::kStack, true, false, command - kMoveStack};
  switch (command) {
    case kToggle: return Route{Action::kToggle};
    case kRecent: return Route{Action::kRecent};
    case kRecentReverse: return Route{Action::kRecent, false, true};
    case IDC_NEW_TAB: return Route{Action::kNewDestination};
    case IDC_FOCUS_LOCATION: return Route{Action::kEditURL};
    case IDC_COPY_URL: return Route{Action::kCopyURL};
    default: return std::nullopt;
  }
}
}  // namespace plico::shortcuts
#endif
