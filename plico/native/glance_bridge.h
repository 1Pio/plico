// Copyright 2026 The plico Authors
// SPDX-License-Identifier: GPL-3.0-only
#ifndef PLICO_NATIVE_GLANCE_BRIDGE_H_
#define PLICO_NATIVE_GLANCE_BRIDGE_H_

#include "base/functional/callback.h"
#include "base/memory/weak_ptr.h"

struct NavigateParams;
namespace content { class NavigationHandle; }
namespace plico {
using GlanceNavigation = base::RepeatingCallback<bool(
    NavigateParams*, base::WeakPtr<content::NavigationHandle>*)>;
// The browser delegate invokes this only after the normal popup-blocking path.
// A false result leaves all normal navigation behavior intact.
void RegisterGlance(const void* owner, GlanceNavigation handler);
void UnregisterGlance(const void* owner);
bool NavigateGlance(NavigateParams* params,
                    base::WeakPtr<content::NavigationHandle>* result);
}  // namespace plico
#endif
