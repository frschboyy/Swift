param([string]$Out, [string]$File)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Data.Pdf.PdfDocument, Windows.Data.Pdf, ContentType = WindowsRuntime]
$null = [Windows.Storage.Streams.InMemoryRandomAccessStream, Windows.Storage.Streams, ContentType = WindowsRuntime]
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
$asAction = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncAction' })[0]
function Await($op, [Type]$t) { $task = $asTask.MakeGenericMethod($t).Invoke($null, @($op)); $task.Wait(-1) | Out-Null; $task.Result }
function AwaitAction($op) { $asAction.Invoke($null, @($op)).Wait(-1) | Out-Null }
$fileObject = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync((Resolve-Path $File).Path)) ([Windows.Storage.StorageFile])
$document = Await ([Windows.Data.Pdf.PdfDocument]::LoadFromFileAsync($fileObject)) ([Windows.Data.Pdf.PdfDocument])
$page = $document.GetPage(0)
$stream = New-Object Windows.Storage.Streams.InMemoryRandomAccessStream
$options = New-Object Windows.Data.Pdf.PdfPageRenderOptions
$scale = [Math]::Min(512 / $page.Size.Width, 720 / $page.Size.Height)
$options.DestinationWidth = [uint32][Math]::Max(1, [Math]::Round($page.Size.Width * $scale))
$options.DestinationHeight = [uint32][Math]::Max(1, [Math]::Round($page.Size.Height * $scale))
AwaitAction ($page.RenderToStreamAsync($stream, $options))
$source = [System.IO.WindowsRuntimeStreamExtensions]::AsStreamForRead($stream.GetInputStreamAt(0))
$target = [IO.File]::Create($Out)
try { $source.CopyTo($target) } finally { $target.Dispose(); $source.Dispose(); $stream.Dispose() }
Add-Type -AssemblyName System.Drawing
$image = [System.Drawing.Image]::FromFile($Out)
$scaledPath = "$Out.scaled.png"
try {
    $scale = [Math]::Min(1.0, [Math]::Min(512.0 / $image.Width, 720.0 / $image.Height))
    if ($scale -lt 1.0) {
        $width = [int][Math]::Max(1, [Math]::Floor($image.Width * $scale))
        $height = [int][Math]::Max(1, [Math]::Floor($image.Height * $scale))
        $scaled = New-Object System.Drawing.Bitmap($width, $height)
        try {
            $graphics = [System.Drawing.Graphics]::FromImage($scaled)
            try {
                $graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
                $graphics.DrawImage($image, 0, 0, $width, $height)
            } finally { $graphics.Dispose() }
            $scaled.Save($scaledPath, [System.Drawing.Imaging.ImageFormat]::Png)
        } finally { $scaled.Dispose() }
    }
} finally { $image.Dispose() }
if (Test-Path -LiteralPath $scaledPath) {
    Move-Item -LiteralPath $scaledPath -Destination $Out -Force
}
Write-Output ("ok`tpages={0}" -f $document.PageCount)
