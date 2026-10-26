<#
.SYNOPSIS
  ADR-012 probe: how much of an app Swift could see and act on through structured Windows
  APIs (Win32 + UI Automation) instead of screenshots, and how fast.

.DESCRIPTION
  Reports NUMBERS ONLY: element counts by type, timings, which patterns are available,
  lengths of the selection and document. No window title, element name or text is printed
  or saved (names are measured, never shown). Read-only, except -Word, which opens a NEW
  blank Word document, writes into it while you watch, undoes and closes it unsaved.

  Uses Windows' built-in .NET UI Automation client: no install needed. Swift itself would use
  native UIA (from Rust or Python), usually faster than these numbers.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File spikes\desktop\uia_probe.ps1 -Label word
  # then switch to Word (with a document open and some text selected) within 5 seconds

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File spikes\desktop\uia_probe.ps1 -Word
#>
param(
  [int]$Delay = 5,
  [string]$Label = "",
  [int]$MaxElements = 4000,
  [double]$MaxSeconds = 20,
  [switch]$Word,
  # Probe a top-level window found by class name instead of the foreground one (for testing).
  [string]$ClassName = "",
  [string]$Out = (Join-Path $env:TEMP "swift-desktop-probe.jsonl")
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class SwiftProbeWin32 {
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll", CharSet = CharSet.Unicode)] public static extern IntPtr FindWindow(string cls, string title);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hwnd, out uint pid);
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }
  [StructLayout(LayoutKind.Sequential)] public struct GUITHREADINFO {
    public int cbSize; public int flags;
    public IntPtr hwndActive, hwndFocus, hwndCapture, hwndMenuOwner, hwndMoveSize, hwndCaret;
    public RECT rcCaret;
  }
  [DllImport("user32.dll")] public static extern bool GetGUIThreadInfo(uint tid, ref GUITHREADINFO info);
  [StructLayout(LayoutKind.Sequential)] public struct POINT { public int X, Y; }
  [DllImport("user32.dll")] public static extern bool GetCursorPos(out POINT p);
}
"@

$AE = [System.Windows.Automation.AutomationElement]
$TP = [System.Windows.Automation.TextPattern]
$VP = [System.Windows.Automation.ValuePattern]

function Ms([System.Diagnostics.Stopwatch]$sw) { [math]::Round($sw.Elapsed.TotalMilliseconds, 1) }

# Some elements (seen in File Explorer) report no control type at all.
function TypeName($controlType) {
  if ($null -eq $controlType) { return "Unknown" }
  $controlType.ProgrammaticName -replace '^ControlType\.', ''
}

# ---- 1. Win32 basics: which window, which app, caret, cursor --------------------------------

function Probe-Basics([IntPtr]$hwnd) {
  $sw = [System.Diagnostics.Stopwatch]::StartNew()
  [uint32]$procId = 0
  $tid = [SwiftProbeWin32]::GetWindowThreadProcessId($hwnd, [ref]$procId)
  $proc = Get-Process -Id $procId
  $gti = New-Object SwiftProbeWin32+GUITHREADINFO
  $gti.cbSize = [System.Runtime.InteropServices.Marshal]::SizeOf($gti)
  [void][SwiftProbeWin32]::GetGUIThreadInfo($tid, [ref]$gti)
  $pt = New-Object SwiftProbeWin32+POINT
  [void][SwiftProbeWin32]::GetCursorPos([ref]$pt)
  $sw.Stop()
  [ordered]@{
    process = $proc.ProcessName            # e.g. WINWORD, chrome; never the window title
    pid = [int]$procId
    system_caret = ($gti.hwndCaret -ne [IntPtr]::Zero)
    basics_ms = (Ms $sw)
  }
}

# ---- 2. The focused element: type, patterns, selection, document size -----------------------

function Probe-Focus([int]$procId) {
  $r = [ordered]@{}
  $sw = [System.Diagnostics.Stopwatch]::StartNew()
  try { $f = $AE::FocusedElement } catch { $r.error = "no focused element"; return $r }
  $r.focus_ms = Ms $sw
  $r.in_window = ($f.Current.ProcessId -eq $procId)
  $r.type = TypeName $f.Current.ControlType
  $r.has_name = -not [string]::IsNullOrEmpty($f.Current.Name)
  $r.has_automation_id = -not [string]::IsNullOrEmpty($f.Current.AutomationId)
  $r.is_password = $f.Current.IsPassword
  $r.patterns = @($f.GetSupportedPatterns() | ForEach-Object { $_.ProgrammaticName -replace 'Identifiers\.Pattern$', '' })
  $tpObj = $null
  if ($f.TryGetCurrentPattern($TP::Pattern, [ref]$tpObj) -and -not $f.Current.IsPassword) {
    $sw.Restart()
    $sel = $tpObj.GetSelection()
    $r.selection_ranges = $sel.Count
    $r.selection_chars = [int](($sel | ForEach-Object { $_.GetText(100000).Length } | Measure-Object -Sum).Sum)
    $r.selection_ms = Ms $sw
    $sw.Restart()
    $r.document_chars = $tpObj.DocumentRange.GetText(500000).Length   # capped at 500k; a count, never the text
    $r.document_ms = Ms $sw
  }
  $vpObj = $null
  if ($f.TryGetCurrentPattern($VP::Pattern, [ref]$vpObj)) { $r.value_read_only = $vpObj.Current.IsReadOnly }
  $r
}

# ---- 3. The window's tree: coverage, interactivity, snapshot size, time ----------------------

$InteractiveProps = @(
  $AE::IsInvokePatternAvailableProperty, $AE::IsValuePatternAvailableProperty,
  $AE::IsTogglePatternAvailableProperty, $AE::IsSelectionItemPatternAvailableProperty,
  $AE::IsExpandCollapsePatternAvailableProperty, $AE::IsTextPatternAvailableProperty
)

function Probe-Tree([System.Windows.Automation.AutomationElement]$root) {
  $cache = New-Object System.Windows.Automation.CacheRequest
  foreach ($p in @($AE::ControlTypeProperty, $AE::NameProperty, $AE::AutomationIdProperty,
                   $AE::IsOffscreenProperty, $AE::IsKeyboardFocusableProperty, $AE::IsPasswordProperty) + $InteractiveProps) {
    $cache.Add($p)
  }
  $walker = [System.Windows.Automation.TreeWalker]::ControlViewWalker
  $types = @{}
  $n = 0; $named = 0; $ids = 0; $interactive = 0; $onscreenInteractive = 0; $maxDepth = 0; $snapshotChars = 0
  $truncated = $false
  $sw = [System.Diagnostics.Stopwatch]::StartNew()
  $queue = New-Object System.Collections.Generic.Queue[object]
  $queue.Enqueue(@($root.GetUpdatedCache($cache), 0))
  while ($queue.Count -gt 0) {
    if ($n -ge $MaxElements -or $sw.Elapsed.TotalSeconds -ge $MaxSeconds) { $truncated = $true; break }
    $item = $queue.Dequeue(); $el = $item[0]; $depth = $item[1]
    $n++
    if ($depth -gt $maxDepth) { $maxDepth = $depth }
    $c = $el.Cached
    $type = TypeName $c.ControlType
    $types[$type] = 1 + [int]$types[$type]
    $hasName = -not [string]::IsNullOrEmpty($c.Name)
    if ($hasName) { $named++ }
    if (-not [string]::IsNullOrEmpty($c.AutomationId)) { $ids++ }
    $isInteractive = $false
    foreach ($p in $InteractiveProps) {
      if ($el.GetCachedPropertyValue([System.Windows.Automation.AutomationProperty]$p, $false)) { $isInteractive = $true; break }
    }
    if ($isInteractive) {
      $interactive++
      if (-not $c.IsOffscreen) {
        $onscreenInteractive++
        # What a structured snapshot line would cost: "e123 Button 'Name (max 60)'". Measured, not kept.
        $name = if ($c.IsPassword) { "" } else { [string]$c.Name }
        $snapshotChars += 8 + $type.Length + [math]::Min(60, $name.Length)
      }
    }
    try {
      $child = $walker.GetFirstChild($el, $cache)
      while ($null -ne $child) {
        $queue.Enqueue(@($child, ($depth + 1)))
        $child = $walker.GetNextSibling($child, $cache)
      }
    } catch { }  # elements can vanish mid-walk
  }
  $sw.Stop()
  # The same tree in one cross-process call (how Swift would take a snapshot), when it's not huge.
  $bulkMs = $null; $bulkCount = $null
  if (-not $truncated) {
    $bulk = [System.Diagnostics.Stopwatch]::StartNew()
    $cache.TreeScope = [System.Windows.Automation.TreeScope]::Element
    $active = $cache.Activate()
    try { $bulkCount = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Condition]::TrueCondition).Count }
    catch { $bulkCount = "failed: " + $_.Exception.InnerException.GetType().Name }  # live pages change mid-read
    finally { $active.Dispose() }
    $bulkMs = Ms $bulk
  }
  [ordered]@{
    bulk_ms = $bulkMs
    bulk_elements = $bulkCount
    elements = $n
    truncated = $truncated
    walk_ms = (Ms $sw)
    ms_per_element = if ($n) { [math]::Round($sw.Elapsed.TotalMilliseconds / $n, 2) } else { $null }
    max_depth = $maxDepth
    named_pct = if ($n) { [math]::Round(100 * $named / $n) } else { 0 }
    automation_id_pct = if ($n) { [math]::Round(100 * $ids / $n) } else { 0 }
    interactive = $interactive
    interactive_onscreen = $onscreenInteractive
    snapshot_chars = $snapshotChars
    snapshot_tokens_est = [math]::Round($snapshotChars / 4)
    types = $types.GetEnumerator() | Sort-Object Value -Descending | Select-Object -First 12 |
      ForEach-Object -Begin { $o = [ordered]@{} } -Process { $o[$_.Key] = $_.Value } -End { $o }
  }
}

# ---- 4. Optional: write into a NEW Word document live, read it back, undo, close unsaved ------

function Probe-Word {
  $r = [ordered]@{}
  $sw = [System.Diagnostics.Stopwatch]::StartNew()
  $app = New-Object -ComObject Word.Application
  $app.Visible = $true
  $doc = $app.Documents.Add()
  $doc.Activate()
  $r.open_ms = Ms $sw
  $lines = @(
    "Swift probe: this document is temporary and will close without saving.",
    "Heading: what structured access looks like",
    "Each line appears as Swift writes it, through Word's own object model.",
    "No screenshot, no mouse, no keystrokes.",
    "Ctrl+Z would undo it like your own typing."
  )
  $times = @()
  foreach ($line in $lines) {
    $sw.Restart()
    $app.Selection.TypeText($line)
    $app.Selection.TypeParagraph()
    $times += (Ms $sw)
    Start-Sleep -Milliseconds 400   # slow enough to watch
  }
  $r.insert_ms_per_paragraph = [math]::Round(($times | Measure-Object -Average).Average, 1)
  $r.chars_via_com = $doc.Content.Text.Length
  # The same document seen through UI Automation: is the text there, without any screenshot?
  try {
    $hwnd = [IntPtr]$app.ActiveWindow.Hwnd
    $win = $AE::FromHandle($hwnd)
    $docEl = $win.FindFirst([System.Windows.Automation.TreeScope]::Descendants,
      (New-Object System.Windows.Automation.PropertyCondition($AE::ControlTypeProperty, [System.Windows.Automation.ControlType]::Document)))
    $tpObj = $null
    $r.uia_document_found = ($null -ne $docEl)
    if ($docEl -and $docEl.TryGetCurrentPattern($TP::Pattern, [ref]$tpObj)) {
      $r.chars_via_uia = $tpObj.DocumentRange.GetText(500000).Length
    }
  } catch { $r.uia_error = $_.Exception.GetType().Name }
  $sw.Restart()
  [void]$doc.Undo($lines.Count * 2)
  $r.undo_ms = Ms $sw
  $r.chars_after_undo = $doc.Content.Text.Length
  Start-Sleep -Seconds 1
  $doc.Close(0)   # wdDoNotSaveChanges
  # No arguments: Word's Quit takes by-reference options PowerShell can't pass as plain values.
  # Nothing is left to save at this point, so Word won't ask.
  if ($app.Documents.Count -eq 0) { $app.Quit() }
  [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($app)
  $r
}

# ---- run ------------------------------------------------------------------------------------

$result = [ordered]@{ ts = (Get-Date).ToString("s"); label = $Label; probe = "uia_probe/1" }
if ($Word) {
  Write-Host "Opening a new blank Word document; watch it fill in, undo, and close without saving..."
  $result.word = Probe-Word
} else {
  if ($ClassName) {
    $hwnd = [SwiftProbeWin32]::FindWindow($ClassName, $null)
    if ($hwnd -eq [IntPtr]::Zero) { throw "No window of class $ClassName" }
  } else {
    for ($i = $Delay; $i -gt 0; $i--) { Write-Host "Switch to the app to probe... $i"; Start-Sleep -Seconds 1 }
    $hwnd = [SwiftProbeWin32]::GetForegroundWindow()
  }
  $result.basics = Probe-Basics $hwnd
  Write-Host ("Measuring: {0}  (if that's not the app you meant, run again and switch to it during the countdown)" -f $result.basics.process) -ForegroundColor Cyan
  $sw = [System.Diagnostics.Stopwatch]::StartNew()
  $root = $AE::FromHandle($hwnd)
  $result.uia_attach_ms = Ms $sw
  $result.focus = Probe-Focus $result.basics.pid
  $result.tree = Probe-Tree $root
  if ($result.basics.process -in @("chrome", "msedge", "firefox", "brave")) {
    # Browsers build their accessibility tree when first asked: walk again once it exists.
    Start-Sleep -Seconds 2
    $result.tree_second_walk = Probe-Tree $root
  }
}
$json = $result | ConvertTo-Json -Depth 6 -Compress
Add-Content -Path $Out -Value $json -Encoding UTF8
$result | ConvertTo-Json -Depth 6
Write-Host "Appended to $Out"
