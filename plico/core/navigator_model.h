// Copyright 2026 The plico Authors
// SPDX-License-Identifier: GPL-3.0-only
#ifndef PLICO_CORE_NAVIGATOR_MODEL_H_
#define PLICO_CORE_NAVIGATOR_MODEL_H_

#include <array>
#include <cstdint>
#include <optional>
#include <vector>

namespace plico {

using TabId = std::int64_t;
inline constexpr int kStackCount = 10;

// Organization only. WebContents, URLs, titles and tab lifetimes belong to the
// browser. Slots are stable; an empty vector means an invisible stack.
struct Layout {
  std::vector<TabId> loose;
  std::array<std::vector<TabId>, kStackCount> stacks;
  std::array<std::optional<TabId>, kStackCount> last_active{};
  bool operator==(const Layout&) const = default;
};

enum class Mode { kHidden, kCommandHold, kLatched, kRecentHold };

struct Commit {
  Layout layout;
  TabId activate;
};

// Pure selection/organization state. Commit returns one browser operation;
// candidate movement never activates a page. TabActivated acknowledges actual
// browser activation and is the only operation that records recency.
class NavigatorModel {
 public:
  bool Reset(Layout layout, std::optional<TabId> active,
             std::vector<TabId> recent = {});
  bool Begin(Mode mode);
  bool Latch();
  void Cancel();
  std::optional<Commit> CommitSelection();

  bool Select(TabId tab);
  bool SelectHorizontal(int direction);
  bool SelectVertical(int direction);
  bool SelectStack(int slot);
  bool MoveHorizontal(int direction);
  bool MoveVertical(int direction);
  bool MoveToStack(int slot);
  bool StepRecent(int direction);

  bool TabAdded(TabId tab);
  void TabClosed(TabId tab);
  void TabActivated(TabId tab);

  Mode mode() const { return mode_; }
  std::optional<TabId> active() const { return active_; }
  std::optional<TabId> candidate() const { return candidate_; }
  const Layout& committed() const { return committed_; }
  const Layout& visible() const {
    return mode_ == Mode::kHidden ? committed_ : working_;
  }
  const std::vector<TabId>& recent() const { return recent_; }
  static bool Valid(const Layout& layout);

 private:
  struct Position { int slot; int row; };  // slot -1 denotes loose tabs.
  static std::optional<Position> Locate(const Layout&, TabId);
  static std::vector<TabId> AllTabs(const Layout&);
  static void Remove(Layout&, TabId);
  static void RepairMemory(Layout&);
  bool CanOrganize() const;
  bool Choose(TabId);

  Layout committed_;
  Layout working_;
  std::optional<TabId> active_;
  std::optional<TabId> candidate_;
  Mode mode_ = Mode::kHidden;
  std::array<std::optional<TabId>, kStackCount> tentative_last_{};
  std::vector<TabId> recent_;
  std::vector<TabId> recent_snapshot_;
};

}  // namespace plico
#endif
