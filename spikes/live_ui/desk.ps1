# Real Windows input and capture for the live UI driver: keys, mouse, screenshots, window rects.
# Usage: desk.ps1 shot <file> | key <combo> | click <x> <y> | move <x> <y> | rect <pid> | front <pid> | type <text>
param([string]$cmd, [string]$a, [string]$b)
Add-Type -AssemblyName System.Drawing, System.Windows.Forms
Add-Type @"
using System; using System.Runtime.InteropServices;
public static class U {
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint x, uint y, uint d, IntPtr e);
  [DllImport("user32.dll")] public static extern void keybd_event(byte vk, byte scan, uint f, IntPtr e);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  public delegate bool EnumProc(IntPtr h, IntPtr l);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc p, IntPtr l);
  [DllImport("user32.dll")] public static extern bool SetProcessDpiAwarenessContext(IntPtr v);
  [DllImport("user32.dll")] public static extern IntPtr WindowFromPoint(POINT p);
  [DllImport("user32.dll")] public static extern IntPtr GetAncestor(IntPtr h, uint f);
  public struct POINT { public int X, Y; }
  public struct RECT { public int L, T, R, B; }
}
"@
[U]::SetProcessDpiAwarenessContext([IntPtr](-4)) | Out-Null
$VK = @{ ctrl = 0x11; alt = 0x12; shift = 0x10; win = 0x5B; esc = 0x1B; enter = 0x0D; tab = 0x09; space = 0x20; f7 = 0x76; f8 = 0x77; f9 = 0x78; f12 = 0x7B }
switch ($cmd) {
  "shot" {
    $s = [System.Windows.Forms.SystemInformation]::VirtualScreen
    $bmp = New-Object System.Drawing.Bitmap $s.Width, $s.Height
    $g = [System.Drawing.Graphics]::FromImage($bmp); $g.CopyFromScreen($s.Left, $s.Top, 0, 0, $bmp.Size)
    $bmp.Save($a, [System.Drawing.Imaging.ImageFormat]::Png); "$($s.Width)x$($s.Height)"
  }
  "key" {
    # combo like ctrl+alt+shift+f7; "hold:<ms>" in $b keeps it down (push to talk)
    $keys = $a.ToLower().Split("+") | ForEach-Object { if ($VK.ContainsKey($_)) { $VK[$_] } else { [byte][char]$_.ToUpper() } }
    foreach ($k in $keys) { [U]::keybd_event([byte]$k, 0, 0, [IntPtr]::Zero) }
    if ($b) { Start-Sleep -Milliseconds ([int]$b) } else { Start-Sleep -Milliseconds 40 }
    [array]::Reverse($keys); foreach ($k in $keys) { [U]::keybd_event([byte]$k, 0, 2, [IntPtr]::Zero) }
  }
  "type" { [System.Windows.Forms.SendKeys]::SendWait($a) }
  "move" { [U]::SetCursorPos([int]$a, [int]$b) | Out-Null }
  "pidat" { $pt = New-Object U+POINT; $pt.X = [int]$a; $pt.Y = [int]$b; $h = [U]::GetAncestor([U]::WindowFromPoint($pt), 2); $p = 0; [U]::GetWindowThreadProcessId($h, [ref]$p) | Out-Null; $p }
  "click" { [U]::SetCursorPos([int]$a, [int]$b) | Out-Null; Start-Sleep -Milliseconds 60; [U]::mouse_event(2, 0, 0, 0, [IntPtr]::Zero); [U]::mouse_event(4, 0, 0, 0, [IntPtr]::Zero) }
  "rect" {
    $out = @(); $target = [uint32]$a
    [U]::EnumWindows({ param($h, $l) $p = 0; [U]::GetWindowThreadProcessId($h, [ref]$p) | Out-Null
      if ($p -eq $target -and [U]::IsWindowVisible($h)) { $r = New-Object U+RECT; [U]::GetWindowRect($h, [ref]$r) | Out-Null; $script:out += "$($r.L),$($r.T),$($r.R),$($r.B)" }; $true }, [IntPtr]::Zero) | Out-Null
    $out -join ";"
  }
  "front" {
    $target = [uint32]$a
    [U]::EnumWindows({ param($h, $l) $p = 0; [U]::GetWindowThreadProcessId($h, [ref]$p) | Out-Null
      if ($p -eq $target -and [U]::IsWindowVisible($h)) { [U]::SetForegroundWindow($h) | Out-Null; return $false }; $true }, [IntPtr]::Zero) | Out-Null
  }
  "focused" { $h = [U]::GetForegroundWindow(); $p = 0; [U]::GetWindowThreadProcessId($h, [ref]$p) | Out-Null; $p }
}
