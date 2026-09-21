// Copyright 2026 The plico Authors
// SPDX-License-Identifier: GPL-3.0-only
#include "plico/native/glance_controller.h"

#import <Cocoa/Cocoa.h>
#include <algorithm>
#include "base/functional/bind.h"
#include "base/task/sequenced_task_runner.h"
#include "chrome/browser/profiles/profile.h"
#include "chrome/browser/ui/browser.h"
#include "chrome/browser/ui/browser_commands.h"
#include "chrome/browser/ui/browser_window/public/create_browser_window.h"
#include "chrome/browser/ui/navigator/browser_navigator.h"
#include "chrome/browser/ui/navigator/browser_navigator_params.h"
#include "chrome/browser/ui/tabs/tab_strip_model.h"
#include "chrome/browser/ui/views/frame/browser_view.h"
#include "content/public/browser/web_contents.h"
#include "plico/native/event_dispatch_mac.h"
#include "plico/native/tab_metadata.h"
#include "ui/events/keycodes/keyboard_code_conversion_mac.h"
#include "ui/views/accessibility/view_accessibility.h"
#include "ui/views/background.h"
#include "ui/views/controls/button/label_button.h"
#include "ui/views/controls/webview/webview.h"
#include "ui/views/widget/widget.h"

namespace plico {
GlanceController::GlanceController(BrowserView* parent) : parent_(parent) {
  RegisterEventHandler(this, base::BindRepeating(
      &GlanceController::HandleEvent, base::Unretained(this)));
}
GlanceController::~GlanceController() {
  UnregisterEventHandler(this);
  nested_.reset();
  controls_.reset();
  if (observed_) observed_->RemoveObserver(this);
  observed_ = nullptr;
  DetachNativeWindow();
  // Normal close may be canceled by beforeunload. In that case the preview
  // remains a standalone browser window, preserving the user's unsaved work.
  if (auto* view = PreviewView()) view->Close();
}

BrowserView* GlanceController::PreviewView() const {
  return preview_ ? BrowserView::GetBrowserViewForBrowser(preview_.get()) : nullptr;
}
bool GlanceController::Owns(content::WebContents* contents) const {
  return (preview_ && preview_->GetTabStripModel()->GetIndexOfWebContents(contents) >= 0) ||
      (nested_ && nested_->Owns(contents));
}

base::WeakPtr<content::NavigationHandle> GlanceController::Navigate(NavigateParams* params) {
  if (nested_ && nested_->Owns(params->source_contents)) return nested_->Navigate(params);
  if (preview_ && (preview_->GetTabStripModel()->GetIndexOfWebContents(params->source_contents) >= 0 ||
                   sandbox_flags_ != params->plico_sandbox_flags)) {
    // A nested preview gets its own WebContents and source sandbox policy.
    // Reusing the outer preview could silently weaken an iframe's restrictions.
    if (!nested_) nested_ = std::make_unique<GlanceController>(parent_);
    return nested_->Navigate(params);
  }
  if (!preview_) {
    BrowserWindowCreateParams create(BrowserWindowInterface::TYPE_POPUP,
                                     parent_->GetProfile(), true);
    create.omit_from_session_restore = true;
    create.should_trigger_session_restore = false;
    create.is_trusted_source = false;
    const gfx::Rect parent_bounds = parent_->GetActiveContentsWebView()->GetBoundsInScreen();
    create.initial_bounds = parent_bounds;
    create.initial_bounds.ClampToCenteredSize(gfx::Size(
        std::max(320, parent_bounds.width() - 100),
        std::max(240, parent_bounds.height() - 80)));
    if (GetBrowserWindowCreationStatusForProfile(*parent_->GetProfile()) !=
        BrowserWindowInterface::CreationStatus::kOk) return {};
    auto* browser = CreateBrowserWindow(std::move(create));
    if (!browser) return {};
    preview_ = browser->GetWeakPtr();
    content::WebContents::CreateParams contents_params(parent_->GetProfile());
    // A preview never weakens the initiating frame's restrictions, including
    // response-to-download restrictions. The browser supplied these flags.
    sandbox_flags_ = params->plico_sandbox_flags;
    contents_params.starting_sandbox_flags = sandbox_flags_;
    browser->GetTabStripModel()->InsertWebContentsAt(0,
        content::WebContents::Create(contents_params), AddTabTypes::ADD_ACTIVE);
    if (auto* view = PreviewView()) {
      observed_ = view->GetWidget();
      observed_->AddObserver(this);
      NSWindow* child = observed_->GetNativeWindow().GetNativeNSWindow();
      [params->source_contents->GetTopLevelNativeWindow().GetNativeNSWindow()
          addChildWindow:child ordered:NSWindowAbove];
    }
  }
  params->browser = preview_.get();
  auto* current = preview_->GetTabStripModel()->GetActiveWebContents();
  // The original request's initiator, referrer and renderer classification stay
  // in params. Only its browser and target WebContents change.
  params->source_contents = current;
  params->disposition = WindowOpenDisposition::CURRENT_TAB;
  params->window_action = NavigateParams::WindowAction::kShowWindow;
  auto handle = ::Navigate(params);
  ShowControls();
  return handle;
}

void GlanceController::DetachNativeWindow() {
  if (auto* view = PreviewView()) {
    NSWindow* child = view->GetNativeWindow().GetNativeNSWindow();
    [child.parentWindow removeChildWindow:child];
  }
}

void GlanceController::Close() {
  if (auto* view = PreviewView()) view->Close();
}

void GlanceController::Promote() {
  if (!preview_) return;
  auto* source = preview_->GetTabStripModel();
  auto* current = source->GetActiveWebContents();
  if (!current) return;
  controls_.reset();
  DetachNativeWindow();
  // Keep the WebContents, renderer, JS state, history and debugger target.
  auto contents = source->DetachWebContentsAtForInsertion(source->GetIndexOfWebContents(current));
  auto& metadata = TabMetadata::Get(contents.get());
  metadata.slot = -1;
  metadata.last_in_stack = false;
  auto* destination = parent_->browser()->tab_strip_model();
  destination->InsertWebContentsAt(destination->count(), std::move(contents), AddTabTypes::ADD_ACTIVE);
  parent_->Show();
  parent_->GetActiveContentsWebView()->RequestFocus();
}

void GlanceController::ShowControls() {
  auto* view = PreviewView();
  if (!view || !view->GetActiveContentsWebView()) return;
  if (!controls_) {
    controls_ = std::make_unique<views::Widget>();
    views::Widget::InitParams init(views::Widget::InitParams::CLIENT_OWNS_WIDGET,
                                   views::Widget::InitParams::TYPE_CONTROL);
    init.parent = view->GetWidget()->GetNativeView();
    init.name = "plico Glance controls";
    init.opacity = views::Widget::InitParams::WindowOpacity::kTranslucent;
    init.activatable = views::Widget::InitParams::Activatable::kNo;
    controls_->Init(std::move(init));
    auto row = std::make_unique<views::View>();
    row->SetBackground(views::CreateRoundedRectBackground(SkColorSetRGB(30, 30, 32), 8));
    auto add = [&](std::u16string label, int x, int width, bool promote) {
      auto button = std::make_unique<views::LabelButton>(base::BindRepeating(
          [](base::WeakPtr<GlanceController> self, bool promote) {
            base::SequencedTaskRunner::GetCurrentDefault()->PostTask(FROM_HERE,
                base::BindOnce([](base::WeakPtr<GlanceController> self, bool promote) {
                  if (!self) return;
                  if (promote) self->Promote(); else self->Close();
                }, self, promote));
          }, weak_.GetWeakPtr(), promote), label);
      button->SetEnabledTextColors(SK_ColorWHITE);
      button->GetViewAccessibility().SetName(label);
      row->AddChildView(std::move(button))->SetBounds(x, 0, width, 36);
    };
    add(u"Close · Esc", 0, 116, false);
    add(u"Open as tab · ⌘↵", 116, 184, true);
    controls_->SetContentsView(std::move(row));
  }
  auto bounds = view->GetActiveContentsWebView()->GetBoundsInScreen();
  controls_->SetBounds(gfx::Rect(bounds.CenterPoint().x() - 150, bounds.bottom() - 52, 300, 36));
  controls_->ShowInactive();
}

void GlanceController::OnWidgetDestroying(views::Widget* widget) {
  if (observed_ != widget) return;
  nested_.reset();
  controls_.reset();
  observed_->RemoveObserver(this);
  observed_ = nullptr;
  preview_.reset();
}
void GlanceController::OnWidgetBoundsChanged(views::Widget*, const gfx::Rect&) {
  base::SequencedTaskRunner::GetCurrentDefault()->PostTask(FROM_HERE,
      base::BindOnce(&GlanceController::ShowControls, weak_.GetWeakPtr()));
}

bool GlanceController::HandleEvent(NSEvent* event) {
  auto* view = PreviewView();
  if (!view || NSApp.keyWindow != view->GetNativeWindow().GetNativeNSWindow() ||
      NSApp.keyWindow.attachedSheet || event.type != NSEventTypeKeyDown) return false;
  const auto key = ui::KeyboardCodeFromNSEvent(event);
  const auto flags = event.modifierFlags & NSEventModifierFlagDeviceIndependentFlagsMask;
  if (key == ui::VKEY_ESCAPE && !(flags & (NSEventModifierFlagCommand | NSEventModifierFlagControl | NSEventModifierFlagOption))) {
    Close();
    return true;
  }
  if (key == ui::VKEY_RETURN && (flags & NSEventModifierFlagCommand)) {
    if (!event.isARepeat) Promote();
    return true;
  }
  if (key == ui::VKEY_C && (flags & (NSEventModifierFlagCommand | NSEventModifierFlagShift)) ==
      (NSEventModifierFlagCommand | NSEventModifierFlagShift)) {
    chrome::CopyURL(view->browser(), view->browser()->tab_strip_model()->GetActiveWebContents());
    return true;
  }
  return false;
}
}  // namespace plico
