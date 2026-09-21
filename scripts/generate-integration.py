from pathlib import Path
import difflib
import json
import re
import sys

root = Path(sys.argv[1]).resolve()
src = root / 'build/src'
saved = root / 'build/upstream-files'
destination = root / 'plico/patches'
pin = json.loads((root / 'config/upstream.json').read_text())
marker = saved / 'PLATFORM_COMMIT'
if marker.exists() and marker.read_text().strip() != pin['platform_commit']:
    raise SystemExit('Upstream snapshots belong to another pin. Preserve them and prepare fresh snapshots.')
if not marker.exists():
    for snapshot in saved.rglob('*'):
        if snapshot.is_file() and snapshot.read_bytes() != (src / snapshot.relative_to(saved)).read_bytes():
            raise SystemExit('Existing upstream snapshots do not match the current source.')
    saved.mkdir(parents=True, exist_ok=True)
    marker.write_text(pin['platform_commit'] + '\n')
changes = {}

def edit(name, old, new):
    if name not in changes:
        snapshot = saved / name
        if not snapshot.exists():
            snapshot.parent.mkdir(parents=True, exist_ok=True)
            snapshot.write_bytes((src / name).read_bytes())
        changes[name] = snapshot.read_text()
    text = changes[name]
    if text.count(old) != 1:
        raise RuntimeError(f'{name}: expected one anchor, found {text.count(old)}: {old[:80]}')
    changes[name] = text.replace(old, new, 1)

name = 'chrome/browser/chrome_browser_application_mac.mm'
edit(name, '#include <Carbon/Carbon.h>', '#include "plico/native/event_dispatch_mac.h"\n\n#include <Carbon/Carbon.h>')
edit(name, '    BOOL sendEventToKeyWindow = NO;',
     '    if (plico::DispatchEvent(event)) return;\n\n    BOOL sendEventToKeyWindow = NO;')

name = 'chrome/browser/BUILD.gn'
edit(name, '      ":chrome_browser_application_mac",\n      ":chrome_browser_main_mac",',
     '      ":chrome_browser_application_mac",\n      "//plico:event_dispatch",\n      ":chrome_browser_main_mac",')

name = 'chrome/browser/ui/BUILD.gn'
edit(name, '  defines = []\n  libs = []', '''  if (is_mac) {
    sources += [
      "//plico/native/browser_controller.h",
      "//plico/native/browser_controller_mac.mm",
      "//plico/native/composer_view.cc",
      "//plico/native/composer_view.h",
      "//plico/native/navigator_view.cc",
      "//plico/native/navigator_view.h",
      "//plico/native/shortcuts.h",
    ]
  }

  defines = []
  libs = []''')
# Add at the end of this target's existing dependency list through its stable
# beginning, rather than creating a second assignment later in the target.
start = changes[name].index('static_library("ui") {')
deps = changes[name].index('  public_deps = [', start)
changes[name] = (changes[name][:deps] + changes[name][deps:].replace(
    '  public_deps = [', '  public_deps = [\n    "//plico:core",\n    "//plico:tab_metadata",', 1))
# Existing mac platform dependencies already live in an is_mac block.
edit(name, '      "//chrome/browser:chrome_browser_application_mac",',
     '      "//chrome/browser:chrome_browser_application_mac",\n      "//plico:event_dispatch",')

name = 'chrome/browser/ui/views/frame/browser_view.h'
edit(name, 'class AccessibilityFocusHighlight;',
     'namespace plico { class BrowserController; }\n\nclass AccessibilityFocusHighlight;')
edit(name, '  mutable base::WeakPtrFactory<BrowserView> weak_ptr_factory_{this};', '''#if BUILDFLAG(IS_MAC)
  std::unique_ptr<plico::BrowserController> plico_controller_;
#endif
  mutable base::WeakPtrFactory<BrowserView> weak_ptr_factory_{this};''')

name = 'chrome/browser/ui/views/frame/browser_view.cc'
edit(name, '#include "chrome/browser/ui/views/frame/browser_view.h"', '''#include "chrome/browser/ui/views/frame/browser_view.h"

#if BUILDFLAG(IS_MAC)
#include "plico/native/browser_controller.h"
#endif''')
edit(name, 'BrowserView::~BrowserView() {', '''BrowserView::~BrowserView() {
#if BUILDFLAG(IS_MAC)
  plico_controller_.reset();
#endif''')
edit(name, '  initialized_ = true;\n}', '''  initialized_ = true;
#if BUILDFLAG(IS_MAC)
  if (GetIsNormalType() && base::CommandLine::ForCurrentProcess()->HasSwitch(
          "plico-native-navigation")) {
    plico_controller_ = std::make_unique<plico::BrowserController>(this);
  }
#endif
}''')
edit(name, 'void BrowserView::OnWidgetDestroying(views::Widget* widget) {', '''void BrowserView::OnWidgetDestroying(views::Widget* widget) {
#if BUILDFLAG(IS_MAC)
  plico_controller_.reset();
#endif''')
edit(name, '  // Collapse zen mode chrome when the window is deactivated.', '''#if BUILDFLAG(IS_MAC)
  if (!active && plico_controller_) plico_controller_->Cancel();
#endif
  // Collapse zen mode chrome when the window is deactivated.''')
edit(name, '  TryNotifyWindowBoundsChanged(new_bounds);', '''  TryNotifyWindowBoundsChanged(new_bounds);
#if BUILDFLAG(IS_MAC)
  if (plico_controller_) plico_controller_->Refresh();
#endif''')

name = 'chrome/browser/ui/browser_live_tab_context.cc'
edit(name, '#include "chrome/browser/ui/browser_live_tab_context.h"',
     '#include "chrome/browser/ui/browser_live_tab_context.h"\n#include "plico/native/tab_metadata.h"')
edit(name, '  return extra_data;', '''  plico::TabMetadata::Populate(tab_strip_model_->GetWebContentsAt(index), &extra_data);
  return extra_data;''')

name = 'chrome/browser/ui/browser_tabrestore.cc'
edit(name, '#include "chrome/browser/ui/browser_tabrestore.h"',
     '#include "chrome/browser/ui/browser_tabrestore.h"\n#include "plico/native/tab_metadata.h"')
edit(name, '  glic::RestoreGlicStateFromExtraData(web_contents.get(), extra_data);',
     '  plico::TabMetadata::Restore(web_contents.get(), extra_data);\n  glic::RestoreGlicStateFromExtraData(web_contents.get(), extra_data);')

name = 'chrome/browser/sessions/session_service.cc'
edit(name, '#include "chrome/browser/sessions/session_service.h"',
     '#include "chrome/browser/sessions/session_service.h"\n#include "plico/native/tab_metadata.h"')
edit(name, '  SessionID session_id(session_tab_helper->session_id());', '''  SessionID session_id(session_tab_helper->session_id());
  if (auto* metadata = plico::TabMetadata::FromWebContents(tab)) {
    command_storage_manager()->AppendRebuildCommand(
        sessions::CreateAddTabExtraDataCommand(session_id,
            plico::kTabMetadataKey, metadata->Serialize()));
  }''')
name = 'chrome/browser/sessions/BUILD.gn'
edit(name, '    "//chrome/browser/glic",',
     '    "//chrome/browser/glic",\n    "//plico:tab_metadata",')

name = 'chrome/browser/devtools/chrome_devtools_manager_delegate.cc'
edit(name, '#include "chrome/browser/devtools/chrome_devtools_manager_delegate.h"',
     '#include "chrome/browser/devtools/chrome_devtools_manager_delegate.h"\n#include "plico/native/tab_metadata.h"')
edit(name, '''    content::RenderFrameHost* rfh) {
  Profile* profile =''', '''    content::RenderFrameHost* rfh) {
  if (auto* contents = content::WebContents::FromRenderFrameHost(rfh)) {
    if (auto* state = plico::TabMetadata::FromWebContents(contents);
        state && state->inspection_blocked) return false;
  }
  Profile* profile =''')
edit(name, '''    content::DevToolsAgentHost* agent_host) {
  // For Android, we have the same implementation''', '''    content::DevToolsAgentHost* agent_host) {
  if (auto* contents = agent_host->GetWebContents()) {
    if (auto* state = plico::TabMetadata::FromWebContents(contents);
        state && state->inspection_blocked) return false;
  }
  // For Android, we have the same implementation''')
name = 'chrome/browser/devtools/BUILD.gn'
edit(name, '''    "//chrome/browser:file_select_helper",''',
     '''    "//plico:tab_metadata",
    "//chrome/browser:file_select_helper",''')

name = 'chrome/browser/ui/browser_shortcuts/browser_shortcut_service.h'
edit(name, '#include <optional>', '#include <optional>\n#include <set>')
edit(name, '  bool HasCommand(int command_id) const;', '''  bool HasCommand(int command_id) const;
  void SetCaptureActive(const void* owner, bool active);
  bool IsCaptureActive() const { return !capture_owners_.empty(); }''')
edit(name, '  CommandAccelerators defaults_;',
     '  std::set<const void*> capture_owners_;\n  CommandAccelerators defaults_;')

name = 'chrome/browser/ui/browser_shortcuts/browser_shortcut_service.cc'
edit(name, '#include "chrome/browser/ui/browser_shortcuts/browser_shortcut_service.h"',
     '#include "chrome/browser/ui/browser_shortcuts/browser_shortcut_service.h"\n#include "plico/native/shortcuts.h"')
edit(name, '  std::u16string display_name = gfx::RemoveAccelerator(',
     '  if (!label.message_id && label.replacement) return *label.replacement;\n  std::u16string display_name = gfx::RemoveAccelerator(')
edit(name, '  std::vector<std::pair<ui::Accelerator, int>> map;',
     '  std::vector<std::pair<ui::Accelerator, int>> map;\n  if (IsCaptureActive()) return map;')
edit(name, 'bool BrowserShortcutService::HasCommand(int command_id) const {', '''void BrowserShortcutService::SetCaptureActive(const void* owner, bool active) {
  const bool previous = IsCaptureActive();
  if (active) capture_owners_.insert(owner);
  else capture_owners_.erase(owner);
  if (previous != IsCaptureActive()) NotifyChanged();
}

bool BrowserShortcutService::HasCommand(int command_id) const {''')
edit(name, '    if (!seen_accelerators.insert(ui_accelerator).second) {',
     '    if (has_label) defaults.try_emplace(command_id);\n    if (!seen_accelerators.insert(ui_accelerator).second) {')
edit(name, '''#if BUILDFLAG(IS_MAC)
  for (const BrowserShortcutPlatformDefaultAccelerator& accelerator :''', '''#if BUILDFLAG(IS_MAC)
  if (plico::shortcuts::Enabled()) {
    for (const auto& [accelerator, command] : plico::shortcuts::Defaults())
      insert_default(command, accelerator, true, false);
    defaults.try_emplace(IDC_HIDE_APP);
  }
  for (const BrowserShortcutPlatformDefaultAccelerator& accelerator :''')
edit(name, '''  for (const auto& platform_default : GetPlatformDefaultAccelerators()) {
    if (platform_default.command_id''', '''  for (const auto& platform_default : GetPlatformDefaultAccelerators()) {
    if (plico::shortcuts::Enabled() && platform_default.command_id == IDC_HIDE_APP) continue;
    if (platform_default.command_id''')

name = 'chrome/browser/ui/browser_shortcuts/browser_shortcut_metadata.cc'
edit(name, '#include "chrome/browser/ui/browser_shortcuts/browser_shortcut_metadata.h"',
     '#include "chrome/browser/ui/browser_shortcuts/browser_shortcut_metadata.h"\n#include "plico/native/shortcuts.h"')
edit(name, '  if (ShouldHideBrowserShortcutCommand(command_id)) {',
     '  if (auto label = plico::shortcuts::Label(command_id)) return BrowserShortcutCommandLabel{0, *label};\n  if (ShouldHideBrowserShortcutCommand(command_id)) {')

name = 'chrome/browser/ui/browser_shortcuts/browser_shortcut_platform_mac.mm'
edit(name, '#include "chrome/browser/ui/browser_shortcuts/browser_shortcut_platform_mac.h"',
     '#include "chrome/browser/ui/browser_shortcuts/browser_shortcut_platform_mac.h"\n#include "plico/native/shortcuts.h"')
edit(name, '''    const std::optional<ui::Accelerator>& accelerator) {
  if (IsDynamicCloseCommand(command_id)) {''',
     '''    const std::optional<ui::Accelerator>& accelerator) {
  if (plico::shortcuts::Enabled() && command_id == IDC_HIDE_APP) return true;
  if (IsDynamicCloseCommand(command_id)) {''')

name = 'chrome/browser/ui/webui/settings/browser_shortcuts.mojom'
edit(name, 'interface BrowserShortcutsHandler {',
     'interface BrowserShortcutsHandler {\n  SetCaptureActive(bool active);')
name = 'chrome/browser/ui/webui/settings/browser_shortcuts_handler.h'
edit(name, '  // mojom::BrowserShortcutsHandler:',
     '  // mojom::BrowserShortcutsHandler:\n  void SetCaptureActive(bool active) override;')
name = 'chrome/browser/ui/webui/settings/browser_shortcuts_handler.cc'
edit(name, '#include <utility>', '#include <utility>\n#include "base/functional/bind.h"')
edit(name, '  service_->AddObserver(this);', '''  service_->AddObserver(this);
  receiver_.set_disconnect_handler(base::BindOnce(
      &BrowserShortcutsHandler::SetCaptureActive, base::Unretained(this), false));''')
edit(name, '  service_->RemoveObserver(this);',
     '  service_->RemoveObserver(this);\n  service_->SetCaptureActive(this, false);')
edit(name, 'void BrowserShortcutsHandler::GetCommands(GetCommandsCallback callback) {', '''void BrowserShortcutsHandler::SetCaptureActive(bool active) {
  service_->SetCaptureActive(this, active);
}

void BrowserShortcutsHandler::GetCommands(GetCommandsCallback callback) {''')
name = 'chrome/browser/resources/settings/system_page/browser_shortcuts_page.ts'
edit(name, '  private upsertCommand_(command: Command) {', '''  override disconnectedCallback() {
    this.handler_.setCaptureActive(false);
    super.disconnectedCallback();
  }

  private upsertCommand_(command: Command) {''')
edit(name, '    this.showCaptureDialog_ = true;',
     '    this.handler_.setCaptureActive(true);\n    this.showCaptureDialog_ = true;')
edit(name, '  private closeDialogs_() {',
     '  private closeDialogs_() {\n    this.handler_.setCaptureActive(false);')

name = 'chrome/app/theme/chromium/BRANDING'
edit(name, 'COMPANY_FULLNAME=The Helium Authors', 'COMPANY_FULLNAME=The plico Authors')
edit(name, 'COMPANY_SHORTNAME=The Helium Authors', 'COMPANY_SHORTNAME=The plico Authors')
edit(name, 'PRODUCT_FULLNAME=Helium', 'PRODUCT_FULLNAME=plico')
edit(name, 'PRODUCT_SHORTNAME=Helium', 'PRODUCT_SHORTNAME=plico')
edit(name, 'PRODUCT_INSTALLER_FULLNAME=Helium Installer', 'PRODUCT_INSTALLER_FULLNAME=plico Installer')
edit(name, 'PRODUCT_INSTALLER_SHORTNAME=Helium Installer', 'PRODUCT_INSTALLER_SHORTNAME=plico Installer')
edit(name, 'MAC_BUNDLE_ID=net.imput.helium', 'MAC_BUNDLE_ID=io.github.1Pio.plico')
edit(name, 'MAC_CREATOR_CODE=Cr24', 'MAC_CREATOR_CODE=Plco')
edit(name, 'MAC_TEAM_ID=S4Q33XPHB4', 'MAC_TEAM_ID=')

name = 'chrome/app/chromium_strings.grd'
original = (src / name).read_text()
for message in ('IDS_PRODUCT_NAME', 'IDS_SHORT_PRODUCT_NAME', 'IDS_APP_MENU_PRODUCT_NAME',
                'IDS_HELPER_NAME', 'IDS_SHORT_HELPER_NAME'):
    blocks = re.findall(r'<message name="' + message + r'"[^>]*>.*?</message>', original, re.S)
    if not blocks:
        raise RuntimeError('Missing product message: ' + message)
    for block in blocks:
        edit(name, block, block.replace('Helium', 'plico'))

name = 'chrome/common/chrome_paths_mac.mm'
edit(name, 'product_dir_name = "net.imput.helium";',
     'product_dir_name = "io.github.1Pio.plico";')
name = 'chrome/app/app-Info.plist'
edit(name, '\t<key>CFBundleIdentifier</key>',
     '\t<key>CrProductDirName</key>\n\t<string>io.github.1Pio.plico</string>\n\t<key>CFBundleIdentifier</key>')
name = 'components/os_crypt/common/keychain_password_mac.mm'
edit(name, '"Helium Storage Key"', '"plico Storage Key"')
edit(name, '"Helium"', '"plico"')

name = 'chrome/browser/mac/sparkle_glue.mm'
original = (src / name).read_text()
start = original.index('VersionUpdaterSparkle::VersionUpdaterSparkle(Profile* profile)')
end = original.index('VersionUpdaterSparkle::~VersionUpdaterSparkle()', start)
edit(name, original[start:end], '''VersionUpdaterSparkle::VersionUpdaterSparkle(Profile* profile)
    : weak_ptr_factory_(this) {
  // Development builds must never install updates from Helium's feed. A signed
  // plico release/update authority must be established before enabling updates.
}

''')

destination.mkdir(parents=True, exist_ok=True)
patch = []
for name, updated in changes.items():
    original = (saved / name).read_text()
    patch.extend(difflib.unified_diff(original.splitlines(True), updated.splitlines(True),
                                     fromfile='a/'+name, tofile='b/'+name))
    check = root / 'build/plico-check-tree' / name
    check.parent.mkdir(parents=True, exist_ok=True)
    check.write_text(updated)
(destination / '0001-native-navigation.patch').write_text(''.join(patch))
(destination / 'series').write_text('0001-native-navigation.patch\n')
(destination / 'manifest.json').write_text(json.dumps({
    'baseline': pin['platform_commit'],
    'touched_upstream_files': sorted(changes),
    'purpose': 'Native navigation, composer, session metadata and per-tab debugger controls',
}, indent=2)+'\n')
print(f'Generated {len(changes)}-file integration patch; build source remains unchanged.')
