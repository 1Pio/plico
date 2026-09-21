// Copyright 2026 The plico Authors
// SPDX-License-Identifier: GPL-3.0-only
#ifndef PLICO_NATIVE_EVENT_DISPATCH_MAC_H_
#define PLICO_NATIVE_EVENT_DISPATCH_MAC_H_

#include "base/functional/callback.h"

@class NSEvent;

namespace plico {
// Runs before AppKit's menu key equivalents so Command+H can belong to the
// browser without changing the OS-wide Hide shortcut. Handlers filter windows.
void RegisterEventHandler(const void* owner,
                          base::RepeatingCallback<bool(NSEvent*)> handler);
void UnregisterEventHandler(const void* owner);
bool DispatchEvent(NSEvent* event);
}  // namespace plico
#endif
