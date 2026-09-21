// Copyright 2026 The plico Authors
// SPDX-License-Identifier: GPL-3.0-only
#include "plico/native/glance_bridge.h"

#include <map>
#include <vector>
#include "base/no_destructor.h"

namespace plico {
namespace {
using Handlers = std::map<const void*, GlanceNavigation>;
Handlers& Registry() {
  static base::NoDestructor<Handlers> handlers;
  return *handlers;
}
}  // namespace
void RegisterGlance(const void* owner, GlanceNavigation handler) {
  Registry().insert_or_assign(owner, std::move(handler));
}
void UnregisterGlance(const void* owner) { Registry().erase(owner); }
bool NavigateGlance(NavigateParams* params,
                    base::WeakPtr<content::NavigationHandle>* result) {
  std::vector<const void*> owners;
  for (const auto& [owner, handler] : Registry()) owners.push_back(owner);
  for (const void* owner : owners) {
    const auto found = Registry().find(owner);
    if (found == Registry().end()) continue;
    auto handler = found->second;
    if (handler.Run(params, result)) return true;
  }
  return false;
}
}  // namespace plico
