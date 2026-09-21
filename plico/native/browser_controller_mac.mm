// Copyright 2026 The plico Authors
// SPDX-License-Identifier: GPL-3.0-only
#include "plico/native/browser_controller.h"

#import <Cocoa/Cocoa.h>
#include <algorithm>
#include "base/auto_reset.h"
#include "base/functional/bind.h"
#include "base/strings/utf_string_conversions.h"
#include "base/strings/string_number_conversions.h"
#include "base/task/sequenced_task_runner.h"
#include "base/time/time.h"
#include "chrome/browser/profiles/profile.h"
#include "chrome/browser/sessions/session_service.h"
#include "chrome/browser/sessions/session_service_factory.h"
#include "chrome/browser/ui/browser.h"
#include "chrome/browser/ui/browser_commands.h"
#include "chrome/browser/ui/browser_shortcuts/browser_shortcut_service.h"
#include "chrome/browser/ui/browser_shortcuts/browser_shortcut_service_factory.h"
#include "chrome/browser/ui/navigator/browser_navigator.h"
#include "chrome/browser/ui/navigator/browser_navigator_params.h"
#include "chrome/browser/ui/tabs/tab_strip_model.h"
#include "chrome/browser/ui/views/frame/browser_view.h"
#include "chrome/common/pref_names.h"
#include "components/favicon/content/content_favicon_driver.h"
#include "components/prefs/pref_service.h"
#include "components/sessions/content/session_tab_helper.h"
#include "content/public/browser/devtools_agent_host.h"
#include "content/public/browser/web_contents.h"
#include "plico/native/event_dispatch_mac.h"
#include "plico/native/composer_view.h"
#include "plico/native/navigator_view.h"
#include "plico/native/tab_metadata.h"
#include "plico/native/shortcuts.h"
#include "ui/events/keycodes/keyboard_code_conversion_mac.h"
#include "ui/gfx/image/image.h"
#include "ui/views/background.h"
#include "ui/views/border.h"
#include "ui/views/controls/button/label_button.h"
#include "ui/views/accessibility/view_accessibility.h"
#include "ui/views/controls/textfield/textfield.h"
#include "ui/views/controls/webview/webview.h"
#include "ui/views/focus/focus_manager.h"
#include "ui/views/view_utils.h"
#include "ui/views/widget/widget.h"

namespace plico {
namespace {
std::int64_t Now() { return base::TimeTicks::Now().since_origin().InMilliseconds(); }
unsigned Modifiers(NSEvent* event) {
  const auto flags = event.modifierFlags;
  return ((flags & NSEventModifierFlagCommand) ? kCommand : 0) |
         ((flags & NSEventModifierFlagControl) ? kControl : 0) |
         ((flags & NSEventModifierFlagShift) ? kShift : 0) |
         ((flags & NSEventModifierFlagOption) ? kOption : 0);
}
}  // namespace

BrowserController::BrowserController(BrowserView* view) : view_(view) {
  RebuildFromTabs();
  view_->browser()->tab_strip_model()->AddObserver(this);
  content::DevToolsAgentHost::AddObserver(this);
  RegisterEventHandler(this, base::BindRepeating(
      &BrowserController::HandleNativeEvent, base::Unretained(this)));
}

BrowserController::~BrowserController() {
  UnregisterEventHandler(this);
  content::DevToolsAgentHost::RemoveObserver(this);
  view_->browser()->tab_strip_model()->RemoveObserver(this);
  reveal_timer_.Stop();
  navigator_widget_.reset();
  CloseComposer(false);
  debugger_widget_.reset();
}

TabId BrowserController::Id(content::WebContents* contents) const {
  return sessions::SessionTabHelper::IdForTab(contents).id();
}

content::WebContents* BrowserController::Contents(TabId id) const {
  auto* tabs = view_->browser()->tab_strip_model();
  for (int i = 0; i < tabs->count(); ++i)
    if (Id(tabs->GetWebContentsAt(i)) == id) return tabs->GetWebContentsAt(i);
  return nullptr;
}

void BrowserController::RebuildFromTabs() {
  Layout layout;
  std::vector<TabId> recent;
  auto* tabs = view_->browser()->tab_strip_model();
  const int window = view_->browser()->GetSessionID().id();
  known_.clear();
  for (int i = 0; i < tabs->count(); ++i) {
    auto* contents = tabs->GetWebContentsAt(i);
    const TabId id = Id(contents);
    auto& metadata = TabMetadata::Get(contents);
    if (metadata.window && metadata.window != window) {
      metadata.slot = -1;
      metadata.last_in_stack = false;
    }
    metadata.window = window;
    auto& list = metadata.slot < 0 ? layout.loose : layout.stacks[metadata.slot];
    list.push_back(id);
    if (metadata.slot >= 0 && metadata.last_in_stack)
      layout.last_active[metadata.slot] = id;
    recent.push_back(id);
    known_.insert(id);
  }
  auto sort_by_order = [&](std::vector<TabId>& list) {
    std::stable_sort(list.begin(), list.end(), [&](TabId a, TabId b) {
      return TabMetadata::Get(Contents(a)).order < TabMetadata::Get(Contents(b)).order;
    });
  };
  sort_by_order(layout.loose);
  for (auto& stack : layout.stacks) sort_by_order(stack);
  std::stable_sort(recent.begin(), recent.end(), [&](TabId a, TabId b) {
    return TabMetadata::Get(Contents(a)).activated_at > TabMetadata::Get(Contents(b)).activated_at;
  });
  auto* active = tabs->GetActiveWebContents();
  router_.Cancel();
  model_.Reset(std::move(layout), active ? std::optional<TabId>(Id(active)) : std::nullopt,
                std::move(recent));
}

void BrowserController::SyncTabs(bool active_changed) {
  if (applying_) return;
  auto* tabs = view_->browser()->tab_strip_model();
  std::set<TabId> present;
  bool restored = false;
  for (int i = 0; i < tabs->count(); ++i) {
    auto* contents = tabs->GetWebContentsAt(i);
    const TabId id = Id(contents);
    present.insert(id);
    if (!known_.contains(id)) {
      auto* metadata = TabMetadata::FromWebContents(contents);
      restored |= metadata && metadata->slot >= 0;
      model_.TabAdded(id);
    }
  }
  for (TabId id : known_) if (!present.contains(id)) model_.TabClosed(id);
  known_ = std::move(present);
  if (restored) RebuildFromTabs();
  if (auto* active = tabs->GetActiveWebContents();
      active && (active_changed || !model_.active())) RecordActivation(Id(active));
  Refresh();
}

void BrowserController::RecordActivation(TabId id) {
  if (auto* contents = Contents(id)) {
    model_.TabActivated(id);
    TabMetadata::Get(contents).activated_at = base::Time::Now().InMillisecondsFSinceUnixEpoch();
    Persist();
  }
}

void BrowserController::Persist() {
  auto* service = SessionServiceFactory::GetForProfile(view_->GetProfile());
  const auto window = view_->browser()->GetSessionID();
  const auto& layout = model_.committed();
  for (int slot = -1; slot < kStackCount; ++slot) {
    const auto& list = slot < 0 ? layout.loose : layout.stacks[slot];
    int order = 0;
    for (TabId id : list) {
      auto* contents = Contents(id);
      if (!contents) continue;
      auto& metadata = TabMetadata::Get(contents);
      metadata.slot = slot;
      metadata.order = order++;
      metadata.window = window.id();
      metadata.last_in_stack = slot >= 0 && layout.last_active[slot] == id;
      if (service) service->AddTabExtraData(window,
          sessions::SessionTabHelper::IdForTab(contents), kTabMetadataKey, metadata.Serialize());
    }
  }
}

void BrowserController::OnTabStripModelChanged(TabStripModel*,
    const TabStripModelChange&, const TabStripSelectionChange& selection) {
  SyncTabs(selection.active_tab_changed());
}
void BrowserController::OnTabChangedAt(tabs::TabInterface*, TabChangeType) { Refresh(); }

void BrowserController::Cancel() {
  router_.Cancel();
  reveal_timer_.Stop();
  navigator_widget_.reset();
  navigator_view_ = nullptr;
}

void BrowserController::Apply(GestureResult result) {
  if (result.commit) {
    auto* tabs = view_->browser()->tab_strip_model();
    auto* target = Contents(result.commit->activate);
    // Resolve again at commit: websites or external tools may have closed tabs.
    if (target) {
      const int index = tabs->GetIndexOfWebContents(target);
      {
        base::AutoReset<bool> applying(&applying_, true);
        if (tabs->GetActiveWebContents() != target) tabs->ActivateTabAt(index);
      }
      RecordActivation(result.commit->activate);
    }
  }
  Refresh();
  if (result.host_action == HostAction::kCopyURL)
    chrome::CopyURL(view_->browser(), view_->browser()->tab_strip_model()->GetActiveWebContents());
  if (result.host_action == HostAction::kEditURL ||
      result.host_action == HostAction::kNewDestination)
    OpenComposer(result.host_action == HostAction::kEditURL);
  ScheduleReveal();
}

void BrowserController::ScheduleReveal() {
  reveal_timer_.Stop();
  if (const auto deadline = router_.reveal_deadline()) {
    reveal_timer_.Start(FROM_HERE, base::Milliseconds(std::max<std::int64_t>(0, *deadline - Now())),
      base::BindOnce([](base::WeakPtr<BrowserController> self) {
        if (!self) return;
        self->router_.RevealIfDue(Now());
        self->Refresh();
      }, weak_.GetWeakPtr()));
  }
}

void BrowserController::Choose(TabId tab) { Apply(router_.PointerSelect(tab)); }
void BrowserController::ChooseStack(int slot) {
  Apply(router_.PointerSelectStack(slot));
}
void BrowserController::ToggleNavigator() { Apply(router_.KeyDown(Action::kToggle, 0)); }

std::vector<ComposerChoice> BrowserController::ComposerTabs() const {
  std::vector<ComposerChoice> choices;
  const auto& layout = model_.committed();
  for (int slot = -1; slot < kStackCount; ++slot) {
    const auto& list = slot < 0 ? layout.loose : layout.stacks[slot];
    for (TabId id : list) {
      auto* contents = Contents(id);
      if (!contents) continue;
      ComposerChoice choice;
      choice.tab = id;
      choice.url = contents->GetVisibleURL();
      choice.title = contents->GetTitle();
      choice.detail = slot < 0 ? u"Switch to loose tab"
          : u"Switch to stack " + base::NumberToString16(slot == 9 ? 0 : slot + 1);
      choices.push_back(std::move(choice));
    }
  }
  return choices;
}

void BrowserController::OpenComposer(bool edit_current) {
  Cancel();
  CloseComposer(false);
  auto* active = view_->browser()->tab_strip_model()->GetActiveWebContents();
  composer_edit_tab_ = edit_current && active ? std::make_optional(Id(active)) : std::nullopt;
  ++composer_generation_;
  composer_widget_ = std::make_unique<views::Widget>();
  views::Widget::InitParams params(views::Widget::InitParams::CLIENT_OWNS_WIDGET,
                                  views::Widget::InitParams::TYPE_WINDOW_FRAMELESS);
  params.name = "plico Search";
  params.parent = view_->GetWidget()->GetNativeView();
  params.opacity = views::Widget::InitParams::WindowOpacity::kTranslucent;
  params.activatable = views::Widget::InitParams::Activatable::kYes;
  composer_widget_->Init(std::move(params));
  composer_widget_->AddObserver(this);
  composer_view_ = composer_widget_->SetContentsView(std::make_unique<ComposerView>(
      view_->GetProfile(), base::BindRepeating([](base::WeakPtr<BrowserController> self) {
        return self ? self->ComposerTabs() : std::vector<ComposerChoice>();
      }, weak_.GetWeakPtr()),
      base::BindRepeating(&BrowserController::AcceptComposer, weak_.GetWeakPtr()),
      base::BindRepeating(&BrowserController::CloseComposer, weak_.GetWeakPtr(), true)));
  composer_widget_->SetBounds(view_->GetActiveContentsWebView()->GetBoundsInScreen());
  composer_widget_->Show();
  composer_view_->Begin(edit_current && active
      ? base::UTF8ToUTF16(active->GetVisibleURL().spec()) : std::u16string());
}

void BrowserController::CloseComposer(bool restore_focus) {
  if (!composer_widget_) return;
  composer_widget_->RemoveObserver(this);
  composer_widget_.reset();
  composer_view_ = nullptr;
  composer_edit_tab_.reset();
  router_.SetEditorOwnsInput(false);
  if (restore_focus && view_->GetActiveContentsWebView())
    view_->GetActiveContentsWebView()->RequestFocus();
}

void BrowserController::AcceptComposer(ComposerChoice choice) {
  if (!composer_widget_) return;
  auto* tabs = view_->browser()->tab_strip_model();
  if (choice.tab) {
    // A closed exact tab is never replaced with a new tab at the same URL.
    auto* target = Contents(*choice.tab);
    if (!target) {
      composer_view_->TabClosed(*choice.tab);
      return;
    }
    CloseComposer(false);
    tabs->ActivateTabAt(tabs->GetIndexOfWebContents(target));
    view_->GetActiveContentsWebView()->RequestFocus();
    return;
  }
  if (!choice.url.is_valid()) return;
  const auto edit = composer_edit_tab_;
  auto* edit_target = edit ? Contents(*edit) : nullptr;
  if (edit && !edit_target) {
    composer_view_->TabClosed(*edit, true);
    return;
  }
  CloseComposer(false);
  NavigateParams params(view_->browser(), choice.url, ui::PAGE_TRANSITION_TYPED);
  params.source_contents = edit_target;
  params.disposition = edit ? WindowOpenDisposition::CURRENT_TAB
                            : WindowOpenDisposition::NEW_FOREGROUND_TAB;
  params.window_action = NavigateParams::WindowAction::kShowWindow;
  Navigate(&params);
}

void BrowserController::OnWidgetActivationChanged(views::Widget* widget, bool active) {
  if (widget == composer_widget_.get() && !active) {
    base::SequencedTaskRunner::GetCurrentDefault()->PostTask(FROM_HERE,
        base::BindOnce([](base::WeakPtr<BrowserController> self, std::uint64_t generation) {
          if (self && self->composer_generation_ == generation) self->CloseComposer(false);
        }, weak_.GetWeakPtr(), composer_generation_));
  }
}

void BrowserController::Refresh() {
  RefreshDebuggerStatus();
  if (model_.mode() == Mode::kHidden) {
    navigator_widget_.reset();
    navigator_view_ = nullptr;
    return;
  }
  auto* contents_view = view_->GetActiveContentsWebView();
  if (!contents_view || !view_->GetWidget()) return;
  const auto bounds = contents_view->GetBoundsInScreen();
  if (bounds.IsEmpty()) return;
  if (!navigator_widget_) {
    navigator_widget_ = std::make_unique<views::Widget>();
    views::Widget::InitParams params(views::Widget::InitParams::CLIENT_OWNS_WIDGET,
                                     views::Widget::InitParams::TYPE_CONTROL);
    params.name = "plico Tab Navigator";
    params.parent = view_->GetWidget()->GetNativeView();
    params.opacity = views::Widget::InitParams::WindowOpacity::kTranslucent;
    params.activatable = views::Widget::InitParams::Activatable::kNo;
    navigator_widget_->Init(std::move(params));
    auto select = base::BindRepeating([](base::WeakPtr<BrowserController> self, TabId tab) {
      base::SequencedTaskRunner::GetCurrentDefault()->PostTask(FROM_HERE,
          base::BindOnce(&BrowserController::Choose, self, tab));
    }, weak_.GetWeakPtr());
    auto stack = base::BindRepeating([](base::WeakPtr<BrowserController> self, int slot) {
      base::SequencedTaskRunner::GetCurrentDefault()->PostTask(FROM_HERE,
          base::BindOnce(&BrowserController::ChooseStack, self, slot));
    }, weak_.GetWeakPtr());
    auto cancel = base::BindRepeating([](base::WeakPtr<BrowserController> self) {
      base::SequencedTaskRunner::GetCurrentDefault()->PostTask(FROM_HERE,
          base::BindOnce(&BrowserController::Cancel, self));
    }, weak_.GetWeakPtr());
    navigator_view_ = navigator_widget_->SetContentsView(
        std::make_unique<NavigatorView>(std::move(select), std::move(stack), std::move(cancel)));
  }
  navigator_widget_->SetBounds(bounds);
  navigator_view_->SetSize(bounds.size());
  std::map<TabId, TabPresentation> presentations;
  for (TabId id : known_) {
    auto* contents = Contents(id);
    if (!contents) continue;
    TabPresentation presentation;
    presentation.title = contents->GetTitle();
    if (presentation.title.empty()) presentation.title = u"Untitled tab";
    presentation.origin = base::UTF8ToUTF16(contents->GetVisibleURL().GetWithEmptyPath().spec());
    if (auto* favicon = favicon::ContentFaviconDriver::FromWebContents(contents))
      presentation.icon = ui::ImageModel::FromImage(favicon->GetFavicon());
    presentation.debugger_attached = content::DevToolsAgentHost::IsDebuggerAttached(contents);
    presentations.emplace(id, std::move(presentation));
  }
  navigator_view_->Update(model_.visible(), model_.candidate(), presentations);
  navigator_widget_->ShowInactive();
}

void BrowserController::DevToolsAgentHostAttached(content::DevToolsAgentHost*) {
  ScheduleDebuggerRefresh();
}
void BrowserController::DevToolsAgentHostDetached(content::DevToolsAgentHost*) {
  ScheduleDebuggerRefresh();
}
void BrowserController::DevToolsAgentHostDestroyed(content::DevToolsAgentHost*) {
  ScheduleDebuggerRefresh();
}
void BrowserController::ScheduleDebuggerRefresh() {
  if (debugger_refresh_pending_) return;
  debugger_refresh_pending_ = true;
  base::SequencedTaskRunner::GetCurrentDefault()->PostTask(FROM_HERE,
      base::BindOnce([](base::WeakPtr<BrowserController> self) {
        if (!self) return;
        self->debugger_refresh_pending_ = false;
        self->Refresh();
      }, weak_.GetWeakPtr()));
}

void BrowserController::ToggleInspection(TabId id) {
  auto* contents = Contents(id);
  if (!contents) return;
  auto& metadata = TabMetadata::Get(contents);
  metadata.inspection_blocked = !metadata.inspection_blocked;
  if (metadata.inspection_blocked) {
    // Block new attachments before detaching so automatic reconnect cannot win.
    // Only this tab's targets are affected; other tabs keep their sessions.
    const auto alive = weak_.GetWeakPtr();
    for (const auto& host : content::DevToolsAgentHost::GetAll()) {
      if (host->GetWebContents() == contents) host->ForceDetachAllSessions();
      if (!alive) return;
    }
  }
  Refresh();
}

void BrowserController::RefreshDebuggerStatus() {
  auto* contents = view_->browser()->tab_strip_model()->GetActiveWebContents();
  if (!contents || !view_->GetWidget() || !view_->GetActiveContentsWebView()) return;
  const bool blocked = TabMetadata::Get(contents).inspection_blocked;
  const bool attached = content::DevToolsAgentHost::IsDebuggerAttached(contents);
  if (!blocked && !attached) {
    debugger_widget_.reset();
    debugger_tab_.reset();
    return;
  }
  const TabId id = Id(contents);
  if (!debugger_widget_ || debugger_tab_ != id || debugger_blocked_ != blocked) {
    debugger_widget_.reset();
    debugger_tab_ = id;
    debugger_blocked_ = blocked;
    debugger_widget_ = std::make_unique<views::Widget>();
    views::Widget::InitParams params(views::Widget::InitParams::CLIENT_OWNS_WIDGET,
                                    views::Widget::InitParams::TYPE_CONTROL);
    params.name = "plico Debugger Status";
    params.parent = view_->GetWidget()->GetNativeView();
    params.opacity = views::Widget::InitParams::WindowOpacity::kTranslucent;
    params.activatable = views::Widget::InitParams::Activatable::kNo;
    debugger_widget_->Init(std::move(params));
    auto button = std::make_unique<views::LabelButton>(base::BindRepeating(
        [](base::WeakPtr<BrowserController> self, TabId id) {
          base::SequencedTaskRunner::GetCurrentDefault()->PostTask(FROM_HERE,
              base::BindOnce(&BrowserController::ToggleInspection, self, id));
        }, weak_.GetWeakPtr(), id), blocked ? u"Debugger blocked · Allow" : u"Debugger connected · Stop");
    button->SetBackground(views::CreateRoundedRectBackground(SkColorSetRGB(35, 35, 39), 8));
    button->SetEnabledTextColors(SK_ColorWHITE);
    button->SetBorder(views::CreateEmptyBorder(gfx::Insets::VH(4, 10)));
    button->GetViewAccessibility().SetName(blocked
        ? u"Debugging blocked for this tab. Allow new debugger connections."
        : u"Debugger attached to this tab. Stop and block new connections.");
    debugger_widget_->SetContentsView(std::move(button));
  }
  const auto bounds = view_->GetActiveContentsWebView()->GetBoundsInScreen();
  debugger_widget_->SetBounds(gfx::Rect(bounds.right() - 244, bounds.bottom() - 42, 232, 30));
  debugger_widget_->ShowInactive();
}

bool BrowserController::HandleNativeEvent(NSEvent* event) {
  auto* widget = view_->GetWidget();
  if (!widget || NSApp.keyWindow != widget->GetNativeWindow().GetNativeNSWindow()) return false;
  if (NSApp.keyWindow.attachedSheet) { Cancel(); return false; }
  if (event.type != NSEventTypeFlagsChanged && event.type != NSEventTypeKeyDown) return false;
  const unsigned modifiers = Modifiers(event);
  auto* focused = view_->GetFocusManager()->GetFocusedView();
  auto* shortcuts = browser_shortcuts::BrowserShortcutServiceFactory::GetForProfile(view_->GetProfile());
  router_.SetEditorOwnsInput(shortcuts->IsCaptureActive() ||
      (focused && views::IsViewClass<views::Textfield>(focused)));
  if (event.type == NSEventTypeFlagsChanged) {
    Apply(router_.ModifiersChanged(modifiers, Now()));
    return false;
  }
  const auto key = ui::KeyboardCodeFromNSEvent(event);
  Action action = Action::kOther;
  int slot = -1;
  unsigned routed_modifiers = modifiers;
  if (key == ui::VKEY_ESCAPE) action = Action::kEscape;
  else if (key == ui::VKEY_RETURN && model_.mode() == Mode::kLatched) action = Action::kAccept;
  else {
    const int flags = ((modifiers & kCommand) ? ui::EF_COMMAND_DOWN : 0) |
        ((modifiers & kControl) ? ui::EF_CONTROL_DOWN : 0) |
        ((modifiers & kOption) ? ui::EF_ALT_DOWN : 0) |
        ((modifiers & kShift) ? ui::EF_SHIFT_DOWN : 0);
    const ui::Accelerator physical(key, flags);
    const ui::Accelerator latched(key, flags | ui::EF_COMMAND_DOWN);
    for (const auto& [accelerator, command] : shortcuts->GetAcceleratorMap()) {
      auto route = plico::shortcuts::Decode(command);
      if (!route) continue;
      const bool latch_motion = model_.mode() == Mode::kLatched &&
          !(modifiers & (kCommand | kControl | kOption)) &&
          (route->action == Action::kLeft || route->action == Action::kRight ||
           route->action == Action::kUp || route->action == Action::kDown ||
           route->action == Action::kStack);
      if (accelerator != physical && !(latch_motion && accelerator == latched)) continue;
      action = route->action;
      slot = route->slot;
      routed_modifiers = (modifiers & ~kShift) | ((route->move || route->reverse) ? kShift : 0);
      break;
    }
  }
  auto result = router_.KeyDown(action, routed_modifiers, event.isARepeat, slot);
  const bool consumed = result.consumed;
  Apply(std::move(result));
  return consumed;
}
}  // namespace plico
