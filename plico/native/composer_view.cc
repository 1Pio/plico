// Copyright 2026 The plico Authors
// SPDX-License-Identifier: GPL-3.0-only
#include "plico/native/composer_view.h"

#include <algorithm>
#include <set>
#include "base/functional/bind.h"
#include "base/i18n/case_conversion.h"
#include "base/strings/utf_string_conversions.h"
#include "base/task/sequenced_task_runner.h"
#include "chrome/browser/autocomplete/chrome_autocomplete_provider_client.h"
#include "chrome/browser/autocomplete/chrome_autocomplete_scheme_classifier.h"
#include "components/omnibox/browser/autocomplete_controller_config.h"
#include "components/omnibox/browser/autocomplete_input.h"
#include "components/omnibox/browser/autocomplete_match.h"
#include "components/omnibox/browser/autocomplete_provider.h"
#include "components/omnibox/browser/autocomplete_result.h"
#include "ui/accessibility/ax_enums.mojom.h"
#include "ui/events/event.h"
#include "ui/views/accessibility/view_accessibility.h"
#include "ui/views/background.h"
#include "ui/views/border.h"
#include "ui/views/controls/button/label_button.h"
#include "ui/views/controls/label.h"
#include "ui/views/controls/textfield/textfield.h"

namespace plico {
namespace {
constexpr SkColor kSurface = SkColorSetRGB(30, 30, 32);
constexpr SkColor kSelected = SkColorSetRGB(63, 72, 92);
constexpr SkColor kText = SkColorSetRGB(238, 238, 240);
constexpr int kRowHeight = 44;
constexpr size_t kMaxChoices = 7;
}  // namespace

ComposerView::ComposerView(Profile* profile,
    base::RepeatingCallback<std::vector<ComposerChoice>()> tabs,
    base::RepeatingCallback<void(ComposerChoice)> accept,
    base::RepeatingClosure cancel)
    : profile_(profile), tabs_(std::move(tabs)), accept_(std::move(accept)),
      cancel_(std::move(cancel)) {
  GetViewAccessibility().SetRole(ax::mojom::Role::kDialog);
  GetViewAccessibility().SetName(u"Search or switch tabs");
  panel_ = AddChildView(std::make_unique<views::View>());
  panel_->SetBackground(views::CreateRoundedRectBackground(kSurface, 12));
  input_ = panel_->AddChildView(std::make_unique<views::Textfield>());
  input_->SetPlaceholderText(u"Search, enter a URL, or switch tabs");
  input_->GetViewAccessibility().SetName(u"Search, enter a URL, or switch tabs");
  input_->set_controller(this);
  status_ = panel_->AddChildView(std::make_unique<views::Label>());
  status_->SetEnabledColor(kText);
  status_->SetHorizontalAlignment(gfx::ALIGN_LEFT);
  status_->GetViewAccessibility().SetRole(ax::mojom::Role::kStatus);
  rows_ = panel_->AddChildView(std::make_unique<views::View>());
  AutocompleteControllerConfig config;
  config.provider_types = AutocompleteProvider::TYPE_BOOKMARK |
      AutocompleteProvider::TYPE_HISTORY_QUICK |
      AutocompleteProvider::TYPE_HISTORY_URL |
      AutocompleteProvider::TYPE_SEARCH |
      AutocompleteProvider::TYPE_KEYWORD |
      AutocompleteProvider::TYPE_BUILTIN;
  config.disable_ml = true;
  config.show_iph_matches = false;
  autocomplete_ = std::make_unique<AutocompleteController>(
      std::make_unique<ChromeAutocompleteProviderClient>(profile), config);
  autocomplete_->AddObserver(this);
}

ComposerView::~ComposerView() {
  autocomplete_->RemoveObserver(this);
  input_->set_controller(nullptr);
}

void ComposerView::Begin(const std::u16string& initial) {
  selected_ = 0;
  selection_pinned_ = false;
  status_->SetText(std::u16string());
  input_->SetText(initial);
  input_->RequestFocus();
  input_->SelectAll(false);
  Search();
  Render();
}

void ComposerView::FocusInput() { input_->RequestFocus(); }

void ComposerView::TabClosed(TabId tab, bool editing) {
  std::erase_if(choices_, [tab](const ComposerChoice& choice) { return choice.tab == tab; });
  selected_.reset();
  selection_pinned_ = true;
  status_->SetText(editing
      ? u"The tab being edited closed. Press Escape, then open a new search."
      : u"That tab closed. Choose another result.");
  Render();
}

void ComposerView::ContentsChanged(views::Textfield*, const std::u16string&) {
  selected_ = 0;
  selection_pinned_ = false;
  status_->SetText(std::u16string());
  Search();
}

void ComposerView::Search() {
  AutocompleteInput input(std::u16string(input_->GetText()), metrics::OmniboxEventProto::OTHER,
                          ChromeAutocompleteSchemeClassifier(profile_));
  input.set_prevent_inline_autocomplete(true);
  autocomplete_->Start(input);
}

void ComposerView::OnResultChanged(AutocompleteController*, bool) {
  // Once a user deliberately selects a result, late provider replies cannot
  // substitute a different destination underneath Enter or the pointer.
  if (selection_pinned_) return;
  choices_.clear();
  const auto query = base::i18n::ToLower(input_->GetText());
  const auto& result = autocomplete_->result();
  std::set<std::string> urls;
  auto add_match = [&](const AutocompleteMatch& match) {
    if (!match.destination_url.is_valid() || choices_.size() >= kMaxChoices ||
        !urls.insert(match.destination_url.spec()).second) return;
    ComposerChoice choice;
    choice.url = match.destination_url;
    choice.title = match.description.empty() ? match.contents : match.description;
    if (choice.title.empty()) choice.title = base::UTF8ToUTF16(choice.url.spec());
    choice.detail = AutocompleteMatch::IsSearchType(match.type)
        ? u"Search" : base::UTF8ToUTF16(choice.url.spec());
    choices_.push_back(std::move(choice));
  };
  if (!result.empty() && !query.empty()) add_match(*result.begin());
  for (auto choice : tabs_.Run()) {
    if (choices_.size() >= kMaxChoices) break;
    const auto haystack = base::i18n::ToLower(choice.title + u" " +
        base::UTF8ToUTF16(choice.url.spec()));
    if (query.empty() || haystack.find(query) != std::u16string::npos)
      choices_.push_back(std::move(choice));
  }
  for (const auto& match : result) add_match(match);
  selected_ = 0;
  Render();
}

void ComposerView::Render() {
  const int panel_width = std::max(240, std::min(660, width() - 48));
  const int status_height = status_->GetText().empty() ? 0 : 32;
  const int panel_height = 64 + status_height + static_cast<int>(choices_.size()) * kRowHeight;
  panel_->SetBounds(std::max(0, (width() - panel_width) / 2),
                    std::max(12, (height() - panel_height) / 2), panel_width, panel_height);
  input_->SetBounds(12, 12, panel_width - 24, 40);
  status_->SetBounds(12, 56, panel_width - 24, status_height);
  status_->SetVisible(status_height > 0);
  rows_->SetBounds(8, 60 + status_height, panel_width - 16, panel_height - 60 - status_height);
  rows_->RemoveAllChildViews();
  for (size_t i = 0; i < choices_.size(); ++i) {
    const auto& choice = choices_[i];
    auto button = std::make_unique<views::LabelButton>(base::BindRepeating(
        &ComposerView::Submit, weak_.GetWeakPtr(), choice),
        choice.title + u"   " + choice.detail);
    button->SetEnabledTextColors(kText);
    button->SetHorizontalAlignment(gfx::ALIGN_LEFT);
    button->SetBorder(views::CreateEmptyBorder(gfx::Insets::VH(6, 10)));
    if (i == selected_)
      button->SetBackground(views::CreateRoundedRectBackground(kSelected, 6));
    button->GetViewAccessibility().SetName(choice.title + u", " + choice.detail);
    button->GetViewAccessibility().SetIsSelected(i == selected_);
    rows_->AddChildView(std::move(button))->SetBounds(
        0, static_cast<int>(i) * kRowHeight, panel_width - 16, kRowHeight);
  }
}

void ComposerView::Submit(ComposerChoice choice) {
  // Closing the widget must not destroy the button during its callback.
  base::SequencedTaskRunner::GetCurrentDefault()->PostTask(
      FROM_HERE, base::BindOnce([](base::WeakPtr<ComposerView> self, ComposerChoice choice) {
        if (self) self->accept_.Run(std::move(choice));
      }, weak_.GetWeakPtr(), std::move(choice)));
}

void ComposerView::Dismiss() {
  base::SequencedTaskRunner::GetCurrentDefault()->PostTask(FROM_HERE,
      base::BindOnce([](base::WeakPtr<ComposerView> self) {
        if (self) self->cancel_.Run();
      }, weak_.GetWeakPtr()));
}

bool ComposerView::HandleKeyEvent(views::Textfield*, const ui::KeyEvent& event) {
  if (event.type() != ui::EventType::kKeyPressed || input_->IsIMEComposing()) return false;
  if (event.key_code() == ui::VKEY_ESCAPE) {
    Dismiss();
    return true;
  }
  if (event.key_code() == ui::VKEY_RETURN) {
    if (selected_ && *selected_ < choices_.size()) Submit(choices_[*selected_]);
    return true;
  }
  if (!choices_.empty() && !event.IsCommandDown() &&
      (event.key_code() == ui::VKEY_DOWN || event.key_code() == ui::VKEY_UP)) {
    selection_pinned_ = true;
    const bool down = event.key_code() == ui::VKEY_DOWN;
    selected_ = selected_ ? (down ? (*selected_ + 1) % choices_.size()
                                 : (*selected_ + choices_.size() - 1) % choices_.size())
                          : (down ? 0 : choices_.size() - 1);
    Render();
    return true;
  }
  return false;
}

bool ComposerView::OnMousePressed(const ui::MouseEvent& event) {
  if (!panel_->bounds().Contains(event.location()))
    Dismiss();
  return true;
}
}  // namespace plico
