// Copyright 2026 The plico Authors
// SPDX-License-Identifier: GPL-3.0-only
#ifndef PLICO_NATIVE_BROWSER_CONTROLLER_H_
#define PLICO_NATIVE_BROWSER_CONTROLLER_H_

#include <map>
#include <memory>
#include <set>
#include "base/memory/raw_ptr.h"
#include "base/memory/weak_ptr.h"
#include "base/timer/timer.h"
#include "chrome/browser/ui/tabs/tab_strip_model_observer.h"
#include "content/public/browser/devtools_agent_host_observer.h"
#include "plico/core/gesture_router.h"
#include "ui/views/widget/widget_observer.h"

#ifdef __OBJC__
@class NSEvent;
#else
class NSEvent;
#endif

class BrowserView;
namespace content { class WebContents; }
namespace views { class Widget; }
namespace plico {
class NavigatorView;
class ComposerView;
struct ComposerChoice;
class GlanceController;

class BrowserController : public TabStripModelObserver,
                          public views::WidgetObserver,
                          public content::DevToolsAgentHostObserver {
 public:
  explicit BrowserController(BrowserView* view);
  ~BrowserController() override;
  void Cancel();
  void Refresh();
  void ToggleNavigator();
  void OnTabStripModelChanged(TabStripModel*, const TabStripModelChange&,
                              const TabStripSelectionChange&) override;
  void OnTabChangedAt(tabs::TabInterface*, TabChangeType) override;
  void OnWidgetActivationChanged(views::Widget*, bool active) override;
  void DevToolsAgentHostAttached(content::DevToolsAgentHost*) override;
  void DevToolsAgentHostDetached(content::DevToolsAgentHost*) override;
  void DevToolsAgentHostDestroyed(content::DevToolsAgentHost*) override;
  content::WebContents* Contents(TabId id) const;
  const NavigatorModel& model() const { return model_; }

 private:
  bool HandleNativeEvent(NSEvent* event);
  void RebuildFromTabs();
  void SyncTabs(bool active_changed);
  void Persist();
  void RecordActivation(TabId id);
  void Apply(GestureResult result);
  void ScheduleReveal();
  void Choose(TabId tab);
  void ChooseStack(int slot);
  void OpenComposer(bool edit_current);
  void CloseComposer(bool restore_focus);
  void AcceptComposer(ComposerChoice choice);
  std::vector<ComposerChoice> ComposerTabs() const;
  void ScheduleDebuggerRefresh();
  void RefreshDebuggerStatus();
  void ToggleInspection(TabId id);
  TabId Id(content::WebContents* contents) const;

  raw_ptr<BrowserView> view_;
  NavigatorModel model_;
  GestureRouter router_{model_};
  std::set<TabId> known_;
  bool applying_ = false;
  std::unique_ptr<views::Widget> navigator_widget_;
  raw_ptr<NavigatorView> navigator_view_ = nullptr;
  std::unique_ptr<views::Widget> composer_widget_;
  raw_ptr<ComposerView> composer_view_ = nullptr;
  std::optional<TabId> composer_edit_tab_;
  std::uint64_t composer_generation_ = 0;
  std::unique_ptr<views::Widget> debugger_widget_;
  std::optional<TabId> debugger_tab_;
  bool debugger_blocked_ = false;
  bool debugger_refresh_pending_ = false;
  base::OneShotTimer reveal_timer_;
  base::WeakPtrFactory<BrowserController> weak_{this};
};
}  // namespace plico
#endif
