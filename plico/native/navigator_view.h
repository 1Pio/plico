// Copyright 2026 The plico Authors
// SPDX-License-Identifier: GPL-3.0-only
#ifndef PLICO_NATIVE_NAVIGATOR_VIEW_H_
#define PLICO_NATIVE_NAVIGATOR_VIEW_H_

#include <map>
#include <string>
#include "base/functional/callback.h"
#include "base/memory/raw_ptr.h"
#include "plico/core/navigator_model.h"
#include "ui/base/models/image_model.h"
#include "ui/views/view.h"

namespace views { class ScrollView; }
namespace plico {
struct TabPresentation {
  std::u16string title;
  std::u16string origin;
  ui::ImageModel icon;
  bool debugger_attached = false;
};

class NavigatorView : public views::View {
 public:
  NavigatorView(base::RepeatingCallback<void(TabId)> select,
                base::RepeatingCallback<void(int)> stack,
                base::RepeatingClosure cancel);
  ~NavigatorView() override;
  void Update(const plico::Layout& layout, std::optional<TabId> candidate,
              const std::map<TabId, TabPresentation>& tabs);
  bool OnMousePressed(const ui::MouseEvent& event) override;

 private:
  base::RepeatingCallback<void(TabId)> select_;
  base::RepeatingCallback<void(int)> stack_;
  base::RepeatingClosure cancel_;
  raw_ptr<views::ScrollView> bar_;
  raw_ptr<views::ScrollView> stack_list_;
  int initial_center_padding_ = -1;
};
}  // namespace plico
#endif
