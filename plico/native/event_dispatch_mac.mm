// Copyright 2026 The plico Authors
// SPDX-License-Identifier: GPL-3.0-only
#include "plico/native/event_dispatch_mac.h"

#include <map>
#include <vector>
#include "base/no_destructor.h"

namespace plico {
namespace {
using Handlers = std::map<const void*, base::RepeatingCallback<bool(NSEvent*)>>;
Handlers& Registry() {
  static base::NoDestructor<Handlers> handlers;
  return *handlers;
}
}  // namespace
void RegisterEventHandler(const void* owner,
                          base::RepeatingCallback<bool(NSEvent*)> handler) {
  Registry().insert_or_assign(owner, std::move(handler));
}
void UnregisterEventHandler(const void* owner) { Registry().erase(owner); }
bool DispatchEvent(NSEvent* event) {
  // A handled action may close its browser. Copy keys, then recheck lifetimes.
  std::vector<const void*> owners;
  for (const auto& [owner, handler] : Registry()) owners.push_back(owner);
  for (const auto* owner : owners) {
    const auto entry = Registry().find(owner);
    if (entry != Registry().end()) {
      auto handler = entry->second;
      if (handler.Run(event)) return true;
    }
  }
  return false;
}
}  // namespace plico
