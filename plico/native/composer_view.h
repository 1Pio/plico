// Copyright 2026 The plico Authors
// SPDX-License-Identifier: GPL-3.0-only
#ifndef PLICO_NATIVE_COMPOSER_VIEW_H_
#define PLICO_NATIVE_COMPOSER_VIEW_H_

#include <memory>
#include <optional>
#include <string>
#include <vector>
#include "base/functional/callback.h"
#include "base/memory/raw_ptr.h"
#include "base/memory/weak_ptr.h"
#include "components/omnibox/browser/autocomplete_controller.h"
#include "plico/core/navigator_model.h"
#include "ui/views/controls/textfield/textfield_controller.h"
#include "ui/views/view.h"
#include "url/gurl.h"

class Profile;
namespace views { class Textfield; class Label; class LabelButton; }
namespace plico {
struct ComposerChoice {
  std::optional<TabId> tab;
  GURL url;
  std::u16string title;
  std::u16string detail;
};

class ComposerView : public views::View,
                     public views::TextfieldController,
                     public AutocompleteController::Observer {
 public:
  ComposerView(Profile* profile,
               base::RepeatingCallback<std::vector<ComposerChoice>()> tabs,
               base::RepeatingCallback<void(ComposerChoice)> accept,
               base::RepeatingClosure cancel);
  ~ComposerView() override;
  void Begin(const std::u16string& initial);
  void TabClosed(TabId tab, bool editing = false);
  void ContentsChanged(views::Textfield*, const std::u16string&) override;
  bool HandleKeyEvent(views::Textfield*, const ui::KeyEvent&) override;
  bool OnMousePressed(const ui::MouseEvent&) override;
  void OnResultChanged(AutocompleteController*, bool) override;

 private:
  void Search();
  void Render();
  void Submit(ComposerChoice choice);
  void Dismiss();
  raw_ptr<Profile> profile_;
  raw_ptr<views::View> panel_;
  raw_ptr<views::View> rows_;
  raw_ptr<views::Textfield> input_;
  raw_ptr<views::Label> status_;
  std::unique_ptr<AutocompleteController> autocomplete_;
  base::RepeatingCallback<std::vector<ComposerChoice>()> tabs_;
  base::RepeatingCallback<void(ComposerChoice)> accept_;
  base::RepeatingClosure cancel_;
  std::vector<ComposerChoice> choices_;
  std::optional<size_t> selected_ = 0;
  bool selection_pinned_ = false;
  base::WeakPtrFactory<ComposerView> weak_{this};
};
}  // namespace plico
#endif
