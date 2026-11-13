# B4 spike: render a PDF's first page to PNG with Windows.Data.Pdf (built into Windows 10+), no dependency.
# Usage: pdf_page.ps1 OUT_PNG_OR_EMPTY PDF...   Prints: ok/fail, pages, width, ms. Saves only when OUT is given.
param([string]$Out, [Parameter(ValueFromRemainingArguments)] [string[]]$Files)
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Data.Pdf.PdfDocument, Windows.Data.Pdf, ContentType = WindowsRuntime]
$null = [Windows.Storage.Streams.InMemoryRandomAccessStream, Windows.Storage.Streams, ContentType = WindowsRuntime]
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
$asAction = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncAction' })[0]
function Await($op, [Type]$t) { $task = $asTask.MakeGenericMethod($t).Invoke($null, @($op)); $task.Wait(-1) | Out-Null; $task.Result }
function AwaitAction($op) { $asAction.Invoke($null, @($op)).Wait(-1) | Out-Null }
foreach ($f in $Files) {
  $sw = [Diagnostics.Stopwatch]::StartNew()
  try {
    $file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync((Resolve-Path $f).Path)) ([Windows.Storage.StorageFile])
    $doc = Await ([Windows.Data.Pdf.PdfDocument]::LoadFromFileAsync($file)) ([Windows.Data.Pdf.PdfDocument])
    $page = $doc.GetPage(0)
    $stream = New-Object Windows.Storage.Streams.InMemoryRandomAccessStream
    $opts = New-Object Windows.Data.Pdf.PdfPageRenderOptions
    $opts.DestinationWidth = 512
    AwaitAction ($page.RenderToStreamAsync($stream, $opts))
    $size = $stream.Size
    if ($Out) {
      $net = [System.IO.WindowsRuntimeStreamExtensions]::AsStreamForRead($stream.GetInputStreamAt(0))
      $fs = [IO.File]::Create($Out); $net.CopyTo($fs); $fs.Close()
    }
    "ok`tpages=$($doc.PageCount)`tpng=$size bytes`t$($sw.ElapsedMilliseconds) ms"
  } catch { $e = $_.Exception; while ($e.InnerException) { $e = $e.InnerException }; "fail`t$($e.Message)`t$($sw.ElapsedMilliseconds) ms" }
}
