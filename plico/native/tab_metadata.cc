// Copyright 2026 The plico Authors
// SPDX-License-Identifier: GPL-3.0-only
#include "plico/native/tab_metadata.h"

#include "base/json/json_reader.h"
#include "base/json/json_writer.h"
#include "base/values.h"

namespace plico {

TabMetadata::TabMetadata(content::WebContents* contents)
    : content::WebContentsUserData<TabMetadata>(*contents) {}
TabMetadata::~TabMetadata() = default;
WEB_CONTENTS_USER_DATA_KEY_IMPL(TabMetadata);

TabMetadata& TabMetadata::Get(content::WebContents* contents) {
  CreateForWebContents(contents);
  return *FromWebContents(contents);
}

std::string TabMetadata::Serialize() const {
  base::DictValue value;
  value.Set("slot", slot);
  value.Set("order", order);
  value.Set("last", last_in_stack);
  value.Set("activated", activated_at);
  return base::WriteJson(value).value_or("{}");
}

void TabMetadata::Restore(content::WebContents* contents,
                          const std::map<std::string, std::string>& extra) {
  const auto entry = extra.find(kTabMetadataKey);
  if (entry == extra.end()) return;
  auto value = base::JSONReader::ReadDict(entry->second, base::JSON_PARSE_RFC);
  if (!value) return;
  const int slot = value->FindInt("slot").value_or(-1);
  const int order = value->FindInt("order").value_or(0);
  if (slot < -1 || slot >= 10 || order < 0) return;
  auto& data = Get(contents);
  data.restored = true;
  data.slot = slot;
  data.order = order;
  data.last_in_stack = value->FindBool("last").value_or(false);
  data.activated_at = value->FindDouble("activated").value_or(0);
}

void TabMetadata::Populate(content::WebContents* contents,
                           std::map<std::string, std::string>* extra) {
  if (auto* data = FromWebContents(contents))
    (*extra)[kTabMetadataKey] = data->Serialize();
}

}  // namespace plico
