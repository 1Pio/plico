// Copyright 2026 The plico Authors
// SPDX-License-Identifier: GPL-3.0-only
#ifndef PLICO_NATIVE_TAB_METADATA_H_
#define PLICO_NATIVE_TAB_METADATA_H_

#include <map>
#include <string>

#include "content/public/browser/web_contents_user_data.h"

namespace plico {

inline constexpr char kTabMetadataKey[] = "plico.navigation.v1";

// Small metadata attached to Chromium's existing tab. SessionService owns disk
// persistence; this object does not create another tab/session store.
class TabMetadata : public content::WebContentsUserData<TabMetadata> {
 public:
  ~TabMetadata() override;
  int slot = -1;
  int order = 0;
  bool last_in_stack = false;
  double activated_at = 0;
  int window = 0;  // Transient: distinguishes cross-window transfers.
  bool inspection_blocked = false;  // Current tab lifetime; user can allow again.
  std::string Serialize() const;
  static TabMetadata& Get(content::WebContents* contents);
  static void Restore(content::WebContents* contents,
                      const std::map<std::string, std::string>& extra);
  static void Populate(content::WebContents* contents,
                       std::map<std::string, std::string>* extra);

 private:
  friend class content::WebContentsUserData<TabMetadata>;
  explicit TabMetadata(content::WebContents* contents);
  WEB_CONTENTS_USER_DATA_KEY_DECL();
};

}  // namespace plico
#endif
