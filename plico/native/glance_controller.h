// Copyright 2026 The plico Authors
// SPDX-License-Identifier: GPL-3.0-only
#ifndef PLICO_NATIVE_GLANCE_CONTROLLER_H_
#define PLICO_NATIVE_GLANCE_CONTROLLER_H_

#include <memory>
#include "base/memory/raw_ptr.h"
#include "base/memory/weak_ptr.h"
#include "services/network/public/mojom/web_sandbox_flags.mojom-shared.h"
#include "ui/views/widget/widget_observer.h"

class BrowserView;
class BrowserWindowInterface;
struct NavigateParams;
#ifdef __OBJC__
@class NSEvent;
#else
class NSEvent;
#endif
namespace content { class NavigationHandle; class WebContents; }
namespace views { class Widget; }

namespace plico {
// The preview is a real popup Browser. Its existing delegates retain permission
// UI, security state, downloads and beforeunload behavior. It never enters the
// parent's tab model until the same WebContents is explicitly promoted.
class GlanceController : public views::WidgetObserver {
 public:
  explicit GlanceController(BrowserView* parent);
  ~GlanceController() override;
  base::WeakPtr<content::NavigationHandle> Navigate(NavigateParams* params);
  bool Owns(content::WebContents* contents) const;
  void OnWidgetDestroying(views::Widget*) override;
  void OnWidgetBoundsChanged(views::Widget*, const gfx::Rect&) override;

 private:
  BrowserView* PreviewView() const;
  void ShowControls();
  void Close();
  void Promote();
  void DetachNativeWindow();
  bool HandleEvent(NSEvent* event);
  raw_ptr<BrowserView> parent_;
  base::WeakPtr<BrowserWindowInterface> preview_;
  raw_ptr<views::Widget> observed_ = nullptr;
  std::unique_ptr<views::Widget> controls_;
  std::unique_ptr<GlanceController> nested_;
  network::mojom::WebSandboxFlags sandbox_flags_ = network::mojom::WebSandboxFlags::kNone;
  base::WeakPtrFactory<GlanceController> weak_{this};
};
}  // namespace plico
#endif
