// Copyright 2026 The plico Authors
// SPDX-License-Identifier: GPL-3.0-only
#include "plico/native/navigator_view.h"

#include <algorithm>
#include "base/functional/bind.h"
#include "base/strings/string_number_conversions.h"
#include "ui/accessibility/ax_enums.mojom.h"
#include "ui/gfx/geometry/insets.h"
#include "ui/gfx/geometry/point_f.h"
#include "ui/views/accessibility/view_accessibility.h"
#include "ui/views/background.h"
#include "ui/views/border.h"
#include "ui/views/controls/button/label_button.h"
#include "ui/views/controls/label.h"
#include "ui/views/controls/scroll_view.h"

namespace plico {
namespace {
constexpr int kRow = 40;
constexpr int kGap = 6;
constexpr int kExpanded = 268;
constexpr SkColor kSurface = SkColorSetARGB(248, 30, 30, 32);
constexpr SkColor kItem = SkColorSetRGB(49, 49, 52);
constexpr SkColor kSelected = SkColorSetRGB(70, 73, 80);
constexpr SkColor kText = SkColorSetRGB(239, 239, 241);

std::unique_ptr<views::LabelButton> MakeButton(
    base::RepeatingClosure callback, std::u16string_view text, bool selected) {
  auto button = std::make_unique<views::LabelButton>(std::move(callback), text);
  button->SetHorizontalAlignment(gfx::ALIGN_LEFT);
  button->SetBorder(views::CreateEmptyBorder(gfx::Insets::VH(0, 10)));
  button->SetBackground(views::CreateRoundedRectBackground(
      selected ? kSelected : kItem, 10));
  button->SetEnabledTextColors(kText);
  button->SetFocusBehavior(views::View::FocusBehavior::ACCESSIBLE_ONLY);
  button->SetElideBehavior(gfx::ELIDE_TAIL);
  button->SetTextSubpixelRenderingEnabled(false);
  button->GetViewAccessibility().SetIsSelected(selected);
  return button;
}
}  // namespace

NavigatorView::NavigatorView(base::RepeatingCallback<void(TabId)> select,
                             base::RepeatingCallback<void(int)> stack,
                             base::RepeatingClosure cancel)
    : select_(std::move(select)), stack_(std::move(stack)),
      cancel_(std::move(cancel)) {
  GetViewAccessibility().SetRole(ax::mojom::Role::kDialog);
  GetViewAccessibility().SetName(u"Tab navigator");
  bar_ = AddChildView(std::make_unique<views::ScrollView>());
  bar_->SetHorizontalScrollBarMode(views::ScrollView::ScrollBarMode::kHiddenButEnabled);
  bar_->SetVerticalScrollBarMode(views::ScrollView::ScrollBarMode::kDisabled);
  bar_->SetTreatAllScrollEventsAsHorizontal(true);
  bar_->SetBackgroundColor(kSurface);
  bar_->SetDrawOverflowIndicator(false);
  stack_list_ = AddChildView(std::make_unique<views::ScrollView>());
  stack_list_->SetHorizontalScrollBarMode(views::ScrollView::ScrollBarMode::kDisabled);
  stack_list_->SetVerticalScrollBarMode(views::ScrollView::ScrollBarMode::kHiddenButEnabled);
  stack_list_->SetBackgroundColor(kSurface);
  stack_list_->SetDrawOverflowIndicator(false);
}
NavigatorView::~NavigatorView() = default;

void NavigatorView::Update(const plico::Layout& layout, std::optional<TabId> candidate,
                           const std::map<TabId, TabPresentation>& tabs) {
  const int viewport = std::max(1, width() - 48);
  const int center = height() / 2;
  const auto old_offset = bar_->CurrentOffset();
  bar_->SetBounds(24, center - kRow / 2 - kGap, viewport, kRow + 2 * kGap);
  auto contents = std::make_unique<views::View>();
  int selected_slot = -1;
  int selected_row = -1;
  for (int slot = 0; slot < kStackCount; ++slot) {
    const auto it = std::find(layout.stacks[slot].begin(), layout.stacks[slot].end(),
                              candidate.value_or(-1));
    if (it != layout.stacks[slot].end()) {
      selected_slot = slot;
      selected_row = static_cast<int>(it - layout.stacks[slot].begin());
    }
  }
  int total = 2 * kGap;
  for (TabId id : layout.loose) total += (candidate == id ? kExpanded : kRow) + kGap;
  for (int slot = 0; slot < kStackCount; ++slot)
    if (!layout.stacks[slot].empty())
      total += (slot == selected_slot ? kExpanded + 36 : 120) + kGap;
  if (initial_center_padding_ < 0)
    initial_center_padding_ = std::max(0, (viewport - total) / 2);
  int x = kGap + initial_center_padding_;
  gfx::Rect candidate_bounds;
  auto make_tab = [&](views::View* parent, TabId id, bool selected, bool full,
                      int slot, gfx::Rect bounds) {
    auto it = tabs.find(id);
    if (it == tabs.end()) return;
    const auto& tab = it->second;
    auto text = full ? tab.title : std::u16string();
    if (full && tab.debugger_attached) text = u"\u25cf " + text;
    auto button = MakeButton(base::BindRepeating(select_, id), text, selected);
    button->SetImageModel(views::Button::STATE_NORMAL, tab.icon);
    const auto location = slot < 0 ? u"Loose" : u"Stack " + base::NumberToString16(slot + 1);
    auto name = tab.title + u", " + location + u", " + tab.origin;
    if (tab.debugger_attached) name += u", debugger attached";
    button->GetViewAccessibility().SetName(name);
    button->SetTooltipText(name);
    if (!full && tab.debugger_attached) {
      auto marker = std::make_unique<views::Label>(u"•");
      marker->SetEnabledColor(SkColorSetRGB(114, 178, 255));
      marker->GetViewAccessibility().SetIsIgnored(true);
      button->AddChildView(std::move(marker))->SetBounds(bounds.width() - 10, 0, 10, 14);
    }
    parent->AddChildView(std::move(button))->SetBoundsRect(bounds);
  };
  for (TabId id : layout.loose) {
    const bool selected = candidate == id;
    const int item_width = selected ? kExpanded : kRow;
    const gfx::Rect bounds(x, kGap, item_width, kRow);
    make_tab(contents.get(), id, selected, selected, -1, bounds);
    if (selected) candidate_bounds = bounds;
    x += item_width + kGap;
  }
  int stack_x = 0;
  for (int slot = 0; slot < kStackCount; ++slot) {
    if (layout.stacks[slot].empty()) continue;
    const bool selected = slot == selected_slot;
    const int item_width = selected ? kExpanded + 36 : 120;
    auto label = base::NumberToString16(slot == 9 ? 0 : slot + 1);
    auto button = MakeButton(base::BindRepeating(stack_, slot), label, selected);
    button->SetHorizontalAlignment(selected ? gfx::ALIGN_LEFT : gfx::ALIGN_CENTER);
    button->GetViewAccessibility().SetName(u"Stack " + base::NumberToString16(slot + 1));
    const gfx::Rect bounds(x, kGap, item_width, kRow);
    contents->AddChildView(std::move(button))->SetBoundsRect(bounds);
    if (selected) { candidate_bounds = bounds; stack_x = x; }
    x += item_width + kGap;
  }
  contents->SetSize(gfx::Size(std::max(x, viewport), kRow + 2 * kGap));
  auto* row = bar_->SetContents(std::move(contents));
  bar_->DeprecatedLayoutImmediately();
  bar_->ScrollToOffset(old_offset);
  if (!candidate_bounds.IsEmpty()) row->ScrollRectToVisible(candidate_bounds);

  stack_list_->SetVisible(selected_slot >= 0);
  if (selected_slot >= 0) {
    const int count = static_cast<int>(layout.stacks[selected_slot].size());
    const int top = std::max(40, center - kRow / 2 - selected_row * (kRow + kGap));
    const int bottom = std::min(height() - 40,
        center + kRow / 2 + (count - selected_row - 1) * (kRow + kGap));
    const int stack_height = std::max(kRow, bottom - top);
    const int stack_left = 24 + stack_x + 36 - static_cast<int>(bar_->CurrentOffset().x());
    stack_list_->SetBounds(std::clamp(stack_left, 24, std::max(24, width() - kExpanded - 24)),
                           top, kExpanded, stack_height);
    auto column = std::make_unique<views::View>();
    int y = 0;
    for (TabId id : layout.stacks[selected_slot]) {
      make_tab(column.get(), id, candidate == id, true, selected_slot,
               gfx::Rect(0, y, kExpanded, kRow));
      y += kRow + kGap;
    }
    column->SetSize(gfx::Size(kExpanded, y - kGap));
    stack_list_->SetContents(std::move(column));
    stack_list_->DeprecatedLayoutImmediately();
    stack_list_->ScrollToOffset(gfx::PointF(0,
        selected_row * (kRow + kGap) - (center - top - kRow / 2)));
  }
}

bool NavigatorView::OnMousePressed(const ui::MouseEvent& event) {
  cancel_.Run();
  return true;
}
}  // namespace plico
