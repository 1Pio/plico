"""Explicit Option-link provenance and native preview integration patches."""


def add_glance(edit):
    name = 'third_party/blink/renderer/platform/runtime_enabled_features.json5'
    edit(name, '      name: "DocumentPatching",', '''      name: "PlicoGlance",
      status: "experimental",
      base_feature: "none",
    },
    {
      name: "DocumentPatching",''')

    name = 'third_party/blink/renderer/core/html/html_anchor_element.cc'
    edit(name, '    bool is_trusted,\n    base::TimeTicks platform_time_stamp,',
         '    bool is_trusted,\n    bool plico_glance,\n    base::TimeTicks platform_time_stamp,')
    edit(name, '  frame_request.SetNavigationPolicy(navigation_policy);',
         '  frame_request.SetNavigationPolicy(navigation_policy);\n  frame_request.SetPlicoGlance(plico_glance);')
    edit(name, '  // Respect the download attribute only if we can read the content, and the', '''  // Glance is an explicit trusted Option-click on a normal web link. Keep
  // download attributes and synthesized/keyboard events on their existing path.
  const bool plico_glance = RuntimeEnabledFeatures::PlicoGlanceEnabled() &&
      event.isTrusted() && event.detail() > 0 && event.button() == 0 && event.altKey() &&
      !event.metaKey() && !event.ctrlKey() && !event.shiftKey() &&
      navigation_policy == kNavigationPolicyDownload &&
      !FastHasAttribute(html_names::kDownloadAttr) &&
      completed_url.ProtocolIsInHttpFamily();
  if (plico_glance) navigation_policy = kNavigationPolicyNewPopup;

  // Respect the download attribute only if we can read the content, and the''')
    edit(name, '      std::move(request), navigation_policy, event.isTrusted(),',
         '      std::move(request), navigation_policy, event.isTrusted(), plico_glance,')
    name = 'third_party/blink/renderer/core/html/html_anchor_element.h'
    edit(name, '                           bool is_trusted,',
         '                           bool is_trusted,\n                           bool plico_glance,')

    name = 'third_party/blink/renderer/core/loader/frame_load_request.h'
    edit(name, '  NavigationPolicy GetNavigationPolicy() const { return navigation_policy_; }', '''  bool IsPlicoGlance() const { return plico_glance_; }
  void SetPlicoGlance(bool value) { plico_glance_ = value; }
  NavigationPolicy GetNavigationPolicy() const { return navigation_policy_; }''')
    edit(name, '  NavigationPolicy navigation_policy_ = kNavigationPolicyCurrentTab;',
         '  bool plico_glance_ = false;\n  NavigationPolicy navigation_policy_ = kNavigationPolicyCurrentTab;')
    name = 'third_party/blink/renderer/core/loader/frame_loader.cc'
    edit(name, '      request.GetScriptToolInvocationId());',
         '      request.GetScriptToolInvocationId(), request.IsPlicoGlance());')

    for name in (
        'third_party/blink/renderer/core/frame/local_frame_client.h',
        'third_party/blink/renderer/core/frame/local_frame_client_impl.h',
        'third_party/blink/renderer/core/loader/empty_clients.h',
    ):
        edit(name, 'std::optional<base::UnguessableToken> script_tool_invocation_id)',
             'std::optional<base::UnguessableToken> script_tool_invocation_id,\n      bool plico_glance = false)')
    for name in (
        'third_party/blink/renderer/core/frame/local_frame_client_impl.cc',
        'third_party/blink/renderer/core/loader/empty_clients.cc',
    ):
        edit(name, 'std::optional<base::UnguessableToken> script_tool_invocation_id)',
             'std::optional<base::UnguessableToken> script_tool_invocation_id,\n    bool plico_glance)')
    name = 'third_party/blink/renderer/core/frame/local_frame_client_impl.cc'
    edit(name, '  navigation_info->navigation_policy = static_cast<WebNavigationPolicy>(policy);',
         '  navigation_info->navigation_policy = static_cast<WebNavigationPolicy>(policy);\n  navigation_info->plico_glance = plico_glance;')
    name = 'third_party/blink/public/web/web_navigation_params.h'
    edit(name, '  WebNavigationPolicy navigation_policy = kWebNavigationPolicyCurrentTab;',
         '  WebNavigationPolicy navigation_policy = kWebNavigationPolicyCurrentTab;\n  bool plico_glance = false;')
    name = 'content/renderer/render_frame_impl.cc'
    edit(name, '  params->disposition = NavigationPolicyToDisposition(policy);\n  params->triggering_event_info = info->triggering_event_info;',
         '  params->disposition = NavigationPolicyToDisposition(policy);\n  params->plico_glance = info->plico_glance;\n  params->triggering_event_info = info->triggering_event_info;')
    name = 'third_party/blink/public/mojom/frame/remote_frame.mojom'
    edit(name, '  bool should_replace_current_entry;\n  bool user_gesture;',
         '  bool should_replace_current_entry;\n  bool user_gesture;\n  bool plico_glance = false;')

    name = 'content/browser/renderer_host/render_frame_host_impl.cc'
    edit(name, '''  // If the flag `is_unfenced_top_navigation` is set, this is a special code''', '''  // The renderer requests preview presentation, never additional authority.
  // Check sandbox policy in the browser and carry it to the new WebContents.
  if (params->plico_glance &&
      (params->disposition != WindowOpenDisposition::NEW_POPUP ||
       !validated_url.SchemeIsHTTPOrHTTPS() || params->post_body ||
       !params->initiator_frame_token ||
       *params->initiator_frame_token != GetFrameToken() ||
       !params->user_gesture ||
       params->triggering_event_info != blink::mojom::TriggeringEventInfo::kFromTrustedEvent ||
       IsSandboxed(network::mojom::WebSandboxFlags::kPopups) ||
       params->is_unfenced_top_navigation)) {
    return;
  }

  // If the flag `is_unfenced_top_navigation` is set, this is a special code''')
    edit(name, '      params->has_rel_opener, params->started_by_ad);',
         '      params->has_rel_opener, params->started_by_ad, params->plico_glance,\n      active_sandbox_flags());')

    name = 'content/browser/renderer_host/navigator.h'
    edit(name, '#include "ui/base/window_open_disposition.h"',
         '#include "ui/base/window_open_disposition.h"\n#include "services/network/public/mojom/web_sandbox_flags.mojom-shared.h"')
    edit(name, '      bool started_by_ad);', '''      bool started_by_ad,
      bool plico_glance = false,
      network::mojom::WebSandboxFlags plico_sandbox_flags = network::mojom::WebSandboxFlags::kNone);''')
    name = 'content/browser/renderer_host/navigator.cc'
    edit(name, '    bool started_by_ad) {', '''    bool started_by_ad,
    bool plico_glance,
    network::mojom::WebSandboxFlags plico_sandbox_flags) {''')
    edit(name, '  params.triggering_event_info = triggering_event_info;', '''  params.triggering_event_info = triggering_event_info;
  params.plico_glance = plico_glance;
  params.plico_sandbox_flags = plico_sandbox_flags;''')
    name = 'content/public/browser/page_navigator.h'
    edit(name, '#include "ui/base/window_open_disposition.h"',
         '#include "ui/base/window_open_disposition.h"\n#include "services/network/public/mojom/web_sandbox_flags.mojom-shared.h"')
    edit(name, '  WindowOpenDisposition disposition;', '''  WindowOpenDisposition disposition;
  bool plico_glance = false;
  network::mojom::WebSandboxFlags plico_sandbox_flags = network::mojom::WebSandboxFlags::kNone;''')

    name = 'chrome/browser/ui/navigator/browser_navigator_params.h'
    edit(name, '#include "content/public/common/referrer.h"',
         '#include "content/public/common/referrer.h"\n#include "services/network/public/mojom/web_sandbox_flags.mojom-shared.h"')
    edit(name, '  content::Referrer referrer;', '''  content::Referrer referrer;
  network::mojom::WebSandboxFlags plico_sandbox_flags = network::mojom::WebSandboxFlags::kNone;''')
    name = 'chrome/browser/ui/navigator/browser_navigator_params.cc'
    edit(name, '  this->initiator_frame_token = params.initiator_frame_token;',
         '  this->plico_sandbox_flags = params.plico_sandbox_flags;\n  this->initiator_frame_token = params.initiator_frame_token;')

    name = 'chrome/browser/ui/browser_web_contents_delegate/browser_web_contents_delegate.cc'
    edit(name, '#include "chrome/browser/ui/browser_web_contents_delegate/browser_web_contents_delegate.h"', '''#include "chrome/browser/ui/browser_web_contents_delegate/browser_web_contents_delegate.h"
#if BUILDFLAG(IS_MAC)
#include "plico/native/glance_bridge.h"
#endif''')
    edit(name, '''  base::WeakPtr<content::NavigationHandle> navigation_handle =
      Navigate(popup_delegate->nav_params());''', '''  base::WeakPtr<content::NavigationHandle> navigation_handle;
#if BUILDFLAG(IS_MAC)
  if (params.plico_glance) {
    if (!plico::NavigateGlance(popup_delegate->nav_params(), &navigation_handle))
      return nullptr;
  } else
#else
  if (params.plico_glance) return nullptr;
#endif
    navigation_handle = Navigate(popup_delegate->nav_params());''')
    name = 'chrome/browser/ui/browser_web_contents_delegate/BUILD.gn'
    edit(name, '    if (use_aura) {', '''    if (is_mac) {
      deps += [ "//plico:glance_bridge" ]
    }
    if (use_aura) {''')
