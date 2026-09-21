// Copyright 2026 The plico Authors
// SPDX-License-Identifier: GPL-3.0-only
#include "plico/core/navigator_model.h"

#include <cstdio>
#include <cstdlib>
#include <utility>

#define CHECK(condition) do { if (!(condition)) { \
  std::fprintf(stderr, "%s:%d: %s\n", __FILE__, __LINE__, #condition); \
  std::abort(); } } while (false)

using plico::Layout;
using plico::Mode;
using plico::NavigatorModel;

Layout Example() {
  Layout l;
  l.loose = {1, 2, 3, 4};
  l.stacks[0] = {11, 12, 13, 14, 15, 16};
  l.last_active[0] = 15;
  l.stacks[1] = {21};
  l.last_active[1] = 21;
  return l;
}

void SpatialCommit() {
  NavigatorModel m;
  CHECK(m.Reset(Example(), 3));
  CHECK(m.Begin(Mode::kCommandHold));
  CHECK(m.SelectHorizontal(-1));
  CHECK(m.candidate() == 2 && m.active() == 3);
  CHECK(m.SelectHorizontal(-1));
  CHECK(m.candidate() == 1 && m.active() == 3);
  auto c = m.CommitSelection();
  CHECK(c && c->activate == 1 && m.active() == 3);
  CHECK(m.mode() == Mode::kHidden && !m.CommitSelection());
  m.TabActivated(c->activate);
  CHECK(m.active() == 1 && m.recent().front() == 1);
}

void StackMemory() {
  NavigatorModel m;
  CHECK(m.Reset(Example(), 3));
  CHECK(m.Begin(Mode::kCommandHold));
  CHECK(m.SelectHorizontal(1) && m.SelectHorizontal(1));
  CHECK(m.candidate() == 15);
  CHECK(m.SelectVertical(-1) && m.SelectVertical(-1));
  CHECK(m.candidate() == 13 && m.committed().last_active[0] == 15);
  CHECK(m.SelectStack(1) && m.SelectStack(0));
  CHECK(m.candidate() == 13);
  m.Cancel();
  CHECK(m.committed().last_active[0] == 15);
  CHECK(m.Begin(Mode::kCommandHold) && m.SelectStack(0));
  CHECK(m.candidate() == 15);
  CHECK(m.SelectVertical(-1));
  auto c = m.CommitSelection();
  CHECK(c && c->activate == 14);
  m.TabActivated(c->activate);
  CHECK(m.committed().last_active[0] == 14);
}

void TransactionAndSlots() {
  NavigatorModel m;
  auto original = Example();
  CHECK(m.Reset(original, 3) && m.Begin(Mode::kCommandHold));
  CHECK(m.MoveHorizontal(1) && m.MoveHorizontal(1));
  CHECK(m.visible().stacks[0].front() == 3);
  CHECK(m.committed() == original);
  CHECK(m.MoveVertical(-1));
  CHECK(m.visible().stacks[0].back() == 3);
  CHECK(m.MoveVertical(1));
  CHECK(m.visible().stacks[0].front() == 3);
  CHECK(m.Latch() && m.mode() == Mode::kLatched);
  CHECK(m.MoveHorizontal(1) && m.MoveHorizontal(1));
  CHECK(m.visible().stacks[2] == std::vector<plico::TabId>{3});
  m.Cancel();
  CHECK(m.committed() == original && m.active() == 3);
  CHECK(m.Begin(Mode::kLatched) && m.MoveToStack(9));
  CHECK(!m.MoveHorizontal(1));
  auto c = m.CommitSelection();
  CHECK(c && c->layout.stacks[9] == std::vector<plico::TabId>{3});
  m.TabActivated(3);
  CHECK(m.committed().last_active[9] == 3);
  CHECK(m.Begin(Mode::kCommandHold) && m.MoveToStack(0));
  CHECK(m.MoveHorizontal(-1));
  CHECK(m.visible().loose.back() == 3);
  CHECK(m.visible().stacks[9].empty());
  CHECK(m.visible().stacks[1] == original.stacks[1]);
}

void EmptySlotsAndSingleton() {
  NavigatorModel m;
  auto l = Example();
  l.stacks[4] = {41};
  CHECK(m.Reset(l, 21) && m.Begin(Mode::kCommandHold));
  CHECK(!m.SelectStack(2));
  CHECK(m.SelectHorizontal(1) && m.candidate() == 41);
  CHECK(m.MoveVertical(1) && m.visible().stacks[4].size() == 1);
  CHECK(m.MoveHorizontal(-1));
  CHECK(m.visible().stacks[3] == std::vector<plico::TabId>{41});
  CHECK(m.visible().stacks[4].empty());
  CHECK(!m.MoveToStack(10) && !m.MoveToStack(-1));
}

void RecentSnapshot() {
  NavigatorModel m;
  CHECK(m.Reset(Example(), 3, {3, 15, 1, 21}));
  auto before = m.recent();
  CHECK(m.Begin(Mode::kRecentHold));
  CHECK(m.StepRecent(1) && m.candidate() == 15);
  CHECK(m.StepRecent(1) && m.candidate() == 1);
  CHECK(m.StepRecent(-1) && m.candidate() == 15);
  CHECK(m.active() == 3 && m.recent() == before);
  CHECK(!m.MoveHorizontal(1) && !m.SelectHorizontal(1));
  auto c = m.CommitSelection();
  CHECK(c && c->activate == 15);
  m.TabActivated(c->activate);
  CHECK(m.Begin(Mode::kRecentHold) && m.StepRecent(1));
  CHECK(m.candidate() == 3);
  m.Cancel();
  CHECK(m.active() == 15);
}

void ConcurrentBrowserChanges() {
  NavigatorModel m;
  CHECK(m.Reset(Example(), 3) && m.Begin(Mode::kCommandHold));
  CHECK(m.MoveToStack(2) && m.TabAdded(99));
  CHECK(m.visible().loose.back() == 4);
  m.TabClosed(11);
  auto c = m.CommitSelection();
  CHECK(c && c->layout.loose.back() == 99);
  CHECK(c->layout.stacks[0].front() == 12);
  CHECK(NavigatorModel::Valid(c->layout));
  m.TabActivated(3);
  CHECK(m.Begin(Mode::kCommandHold) && m.Select(12));
  m.TabClosed(12);
  CHECK(m.mode() == Mode::kHidden && !m.CommitSelection());
  CHECK(m.Begin(Mode::kRecentHold) && m.StepRecent(1));
  m.TabActivated(4);
  CHECK(m.mode() == Mode::kHidden && m.active() == 4);
}

void InvalidAndEmpty() {
  NavigatorModel m;
  CHECK(m.Reset({}, std::nullopt));
  CHECK(!m.Begin(Mode::kCommandHold));
  CHECK(m.TabAdded(1) && !m.TabAdded(1));
  m.TabActivated(1);
  CHECK(!m.Begin(Mode::kRecentHold));
  CHECK(m.Begin(Mode::kCommandHold) && !m.Select(99));
  CHECK(!m.SelectHorizontal(0) && !m.MoveVertical(12));
  Layout invalid = Example();
  invalid.loose.push_back(15);
  CHECK(!m.Reset(invalid, 3));
  CHECK(m.active() == 1);
  m.TabClosed(1);
  CHECK(m.mode() == Mode::kHidden && !m.active());
}

void ActualStackMemory() {
  NavigatorModel m;
  Layout layout;
  layout.loose = {1, 2};
  layout.stacks[0] = {11, 12, 13};
  layout.stacks[1] = {21};
  CHECK(m.Reset(layout, 12));
  CHECK(m.committed().last_active[0] == 12);
  CHECK(m.Begin(Mode::kCommandHold));
  CHECK(m.SelectHorizontal(1) && m.SelectHorizontal(-1));
  CHECK(m.candidate() == 12);
  m.Cancel();

  layout.last_active[0] = 13;
  CHECK(m.Reset(layout, 1) && m.Begin(Mode::kCommandHold));
  CHECK(m.Select(13) && m.MoveToStack(1) && m.MoveToStack(0));
  CHECK(m.Select(1) && m.CommitSelection());
  m.TabActivated(1);
  CHECK(m.committed().last_active[0] == 13);
  CHECK(m.Begin(Mode::kCommandHold) && m.SelectStack(0));
  CHECK(m.candidate() == 13);
  CHECK(m.MoveToStack(1) && m.Select(1) && m.CommitSelection());
  CHECK(!m.committed().last_active[0]);
  CHECK(m.committed().last_active[1] == std::nullopt);
}

void DelayedActivationAcknowledgement() {
  NavigatorModel m;
  Layout layout;
  layout.loose = {1, 2};
  CHECK(m.Reset(layout, 1) && m.Begin(Mode::kCommandHold));
  CHECK(m.MoveToStack(0) && m.CommitSelection());
  CHECK(m.Begin(Mode::kCommandHold));
  m.TabActivated(1);
  CHECK(m.Select(2) && m.CommitSelection());
  CHECK(m.committed().last_active[0] == 1);
}

void RecentWrapAndMutation() {
  NavigatorModel m;
  Layout layout;
  layout.loose = {1, 2, 3, 4};
  CHECK(m.Reset(layout, 1, {1, 4, 2, 3}));
  CHECK(m.Begin(Mode::kRecentHold));
  CHECK(m.StepRecent(-1) && m.candidate() == 3);
  CHECK(m.StepRecent(1) && m.candidate() == 1);
  CHECK(m.TabAdded(5));
  m.TabClosed(2);
  CHECK(m.StepRecent(1) && m.candidate() == 4);
  CHECK(m.StepRecent(1) && m.candidate() == 3);
  CHECK(m.StepRecent(1) && m.candidate() == 1);
  CHECK(m.StepRecent(-1) && m.candidate() == 3);
  auto commit = m.CommitSelection();
  CHECK(commit && commit->layout.loose == std::vector<plico::TabId>({1, 3, 4, 5}));
  m.TabActivated(3);
  CHECK(m.Begin(Mode::kRecentHold) && m.StepRecent(-1));
  CHECK(m.candidate() == 5);
}

int main() {
  SpatialCommit();
  StackMemory();
  TransactionAndSlots();
  EmptySlotsAndSingleton();
  RecentSnapshot();
  ConcurrentBrowserChanges();
  InvalidAndEmpty();
  ActualStackMemory();
  DelayedActivationAcknowledgement();
  RecentWrapAndMutation();
  std::puts("10 navigation scenarios passed");
}
