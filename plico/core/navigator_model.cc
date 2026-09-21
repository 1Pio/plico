// Copyright 2026 The plico Authors
// SPDX-License-Identifier: GPL-3.0-only
#include "plico/core/navigator_model.h"

#include <algorithm>
#include <utility>

namespace plico {
namespace {
bool Has(const std::vector<TabId>& tabs, TabId tab) {
  return std::find(tabs.begin(), tabs.end(), tab) != tabs.end();
}
bool Direction(int value) { return value == -1 || value == 1; }
int Wrapped(int row, int delta, int count) {
  return (row + delta + count) % count;
}
}  // namespace

std::vector<TabId> NavigatorModel::AllTabs(const Layout& layout) {
  auto result = layout.loose;
  for (const auto& stack : layout.stacks)
    result.insert(result.end(), stack.begin(), stack.end());
  return result;
}

bool NavigatorModel::Valid(const Layout& layout) {
  auto all = AllTabs(layout);
  std::sort(all.begin(), all.end());
  if (std::adjacent_find(all.begin(), all.end()) != all.end()) return false;
  for (int slot = 0; slot < kStackCount; ++slot) {
    if (layout.last_active[slot] &&
        !Has(layout.stacks[slot], *layout.last_active[slot])) return false;
  }
  return true;
}

std::optional<NavigatorModel::Position> NavigatorModel::Locate(
    const Layout& layout, TabId tab) {
  for (int slot = -1; slot < kStackCount; ++slot) {
    const auto& list = slot < 0 ? layout.loose : layout.stacks[slot];
    auto it = std::find(list.begin(), list.end(), tab);
    if (it != list.end()) return Position{slot, static_cast<int>(it - list.begin())};
  }
  return std::nullopt;
}

void NavigatorModel::RepairMemory(Layout& layout) {
  for (int slot = 0; slot < kStackCount; ++slot) {
    if (layout.last_active[slot] &&
        !Has(layout.stacks[slot], *layout.last_active[slot])) {
      // A display fallback is not evidence of an actual activation.
      layout.last_active[slot].reset();
    }
  }
}

void NavigatorModel::Remove(Layout& layout, TabId tab) {
  std::erase(layout.loose, tab);
  for (auto& stack : layout.stacks) std::erase(stack, tab);
  RepairMemory(layout);
}

bool NavigatorModel::Reset(Layout layout, std::optional<TabId> active,
                           std::vector<TabId> recent) {
  if (!Valid(layout) || (active && !Locate(layout, *active))) return false;
  committed_ = std::move(layout);
  active_ = active;
  if (active) {
    const auto position = Locate(committed_, *active);
    if (position->slot >= 0) committed_.last_active[position->slot] = *active;
  }
  recent_.clear();
  if (active) recent_.push_back(*active);
  for (TabId tab : recent)
    if (Locate(committed_, tab) && !Has(recent_, tab)) recent_.push_back(tab);
  for (TabId tab : AllTabs(committed_))
    if (!Has(recent_, tab)) recent_.push_back(tab);
  Cancel();
  return true;
}

bool NavigatorModel::Begin(Mode mode) {
  Cancel();
  if (mode == Mode::kHidden || recent_.empty()) return false;
  if (mode == Mode::kRecentHold && recent_.size() < 2) return false;
  mode_ = mode;
  working_ = committed_;
  tentative_last_ = committed_.last_active;
  candidate_ = active_ ? active_ : std::optional<TabId>(recent_.front());
  recent_snapshot_ = recent_;
  return true;
}

bool NavigatorModel::Latch() {
  if (mode_ == Mode::kCommandHold) {
    mode_ = Mode::kLatched;
    return true;
  }
  return Begin(Mode::kLatched);
}

void NavigatorModel::Cancel() {
  mode_ = Mode::kHidden;
  candidate_.reset();
  working_ = {};
  tentative_last_ = {};
  recent_snapshot_.clear();
}

std::optional<Commit> NavigatorModel::CommitSelection() {
  if (!candidate_ || !Locate(committed_, *candidate_)) {
    Cancel();
    return std::nullopt;
  }
  const TabId target = *candidate_;
  // Background additions are not shown mid-gesture, but must survive a commit.
  for (TabId tab : AllTabs(committed_))
    if (!Locate(working_, tab)) working_.loose.push_back(tab);
  // Membership is transactional, activation history is not. Reconcile the
  // latest browser acknowledgements against final membership only, so moving
  // a remembered tab out and back does not erase its activation history.
  working_.last_active = committed_.last_active;
  RepairMemory(working_);
  committed_ = working_;
  Commit result{committed_, target};
  Cancel();
  return result;
}

bool NavigatorModel::Choose(TabId tab) {
  if (mode_ == Mode::kHidden || !Locate(working_, tab)) return false;
  candidate_ = tab;
  auto p = Locate(working_, tab);
  if (p->slot >= 0) tentative_last_[p->slot] = tab;
  return true;
}

bool NavigatorModel::Select(TabId tab) { return Choose(tab); }

bool NavigatorModel::SelectStack(int slot) {
  if (!CanOrganize() || slot < 0 || slot >= kStackCount ||
      working_.stacks[slot].empty()) return false;
  const auto& stack = working_.stacks[slot];
  auto remembered = tentative_last_[slot];
  return Choose(remembered && Has(stack, *remembered) ? *remembered : stack.front());
}

bool NavigatorModel::SelectHorizontal(int direction) {
  if (!CanOrganize() || !Direction(direction)) return false;
  auto p = Locate(working_, *candidate_);
  if (p->slot == -1) {
    const int next = p->row + direction;
    if (next >= 0 && next < static_cast<int>(working_.loose.size()))
      return Choose(working_.loose[next]);
    if (direction < 0) return false;
    for (int slot = 0; slot < kStackCount; ++slot)
      if (!working_.stacks[slot].empty()) return SelectStack(slot);
    return false;
  }
  for (int slot = p->slot + direction; slot >= 0 && slot < kStackCount;
       slot += direction)
    if (!working_.stacks[slot].empty()) return SelectStack(slot);
  return direction < 0 && !working_.loose.empty()
      ? Choose(working_.loose.back()) : false;
}

bool NavigatorModel::SelectVertical(int direction) {
  if (!CanOrganize() || !Direction(direction)) return false;
  auto p = Locate(working_, *candidate_);
  if (p->slot < 0) return false;
  const auto& stack = working_.stacks[p->slot];
  return Choose(stack[Wrapped(p->row, direction, static_cast<int>(stack.size()))]);
}

bool NavigatorModel::CanOrganize() const {
  return candidate_ && (mode_ == Mode::kCommandHold || mode_ == Mode::kLatched);
}

bool NavigatorModel::MoveToStack(int slot) {
  if (!CanOrganize() || slot < 0 || slot >= kStackCount) return false;
  const TabId tab = *candidate_;
  auto p = Locate(working_, tab);
  if (p->slot == slot) return true;
  Remove(working_, tab);
  working_.stacks[slot].insert(working_.stacks[slot].begin(), tab);
  tentative_last_[slot] = tab;
  return true;
}

bool NavigatorModel::MoveHorizontal(int direction) {
  if (!CanOrganize() || !Direction(direction)) return false;
  auto p = Locate(working_, *candidate_);
  if (p->slot == -1) {
    const int next = p->row + direction;
    if (next >= 0 && next < static_cast<int>(working_.loose.size())) {
      std::swap(working_.loose[p->row], working_.loose[next]);
      return true;
    }
    return direction > 0 ? MoveToStack(0) : false;
  }
  const int slot = p->slot + direction;
  if (slot >= kStackCount) return false;
  if (slot >= 0) return MoveToStack(slot);
  const TabId tab = *candidate_;
  Remove(working_, tab);
  working_.loose.push_back(tab);
  return true;
}

bool NavigatorModel::MoveVertical(int direction) {
  if (!CanOrganize() || !Direction(direction)) return false;
  auto p = Locate(working_, *candidate_);
  if (p->slot < 0) return false;
  auto& stack = working_.stacks[p->slot];
  const int next = Wrapped(p->row, direction, static_cast<int>(stack.size()));
  TabId tab = *candidate_;
  stack.erase(stack.begin() + p->row);
  stack.insert(stack.begin() + next, tab);
  return true;
}

bool NavigatorModel::StepRecent(int direction) {
  if (mode_ != Mode::kRecentHold || !candidate_ ||
      recent_snapshot_.empty() || !Direction(direction)) return false;
  auto it = std::find(recent_snapshot_.begin(), recent_snapshot_.end(), *candidate_);
  if (it == recent_snapshot_.end()) return false;
  int next = Wrapped(static_cast<int>(it - recent_snapshot_.begin()), direction,
                     static_cast<int>(recent_snapshot_.size()));
  return Choose(recent_snapshot_[next]);
}

bool NavigatorModel::TabAdded(TabId tab) {
  if (Locate(committed_, tab)) return false;
  committed_.loose.push_back(tab);
  recent_.push_back(tab);
  return true;
}

void NavigatorModel::TabClosed(TabId tab) {
  Remove(committed_, tab);
  std::erase(recent_, tab);
  if (active_ == tab || candidate_ == tab) {
    if (active_ == tab) active_.reset();
    Cancel();
  } else if (mode_ != Mode::kHidden) {
    Remove(working_, tab);
    std::erase(recent_snapshot_, tab);
  }
}

void NavigatorModel::TabActivated(TabId tab) {
  auto p = Locate(committed_, tab);
  if (!p) return;
  if (mode_ != Mode::kHidden && active_ != tab) Cancel();
  active_ = tab;
  std::erase(recent_, tab);
  recent_.insert(recent_.begin(), tab);
  if (p->slot >= 0) committed_.last_active[p->slot] = tab;
}

}  // namespace plico
