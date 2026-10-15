# Runs the S2/S3 benchmarks sequentially (never in parallel, so CPU numbers are not contaminated).
# Usage: powershell -File spikes\run_s2_s3.ps1 -Models qwen3:1.7b,qwen3.5:4b [-SkipAudio]
param(
    [string[]]$Models = @("qwen3:1.7b", "qwen3.5:4b", "qwen3:8b"),
    [switch]$SkipAudio
)
$ErrorActionPreference = "Continue"
# -File passes "a,b" as one string; split it.
$Models = @($Models | ForEach-Object { $_ -split "," } | Where-Object { $_ })
$uv = "C:\Users\frchi\AppData\Roaming\Python\Python313\Scripts\uv.exe"
Set-Location (Split-Path $PSScriptRoot -Parent)
$clip = "spikes\latency\results\clips\clip_10s.wav"

if (-not $SkipAudio) {
    while (-not (Test-Path $clip)) { Start-Sleep -Seconds 10 }
    Start-Sleep -Seconds 20  # let piper_bench finish writing its result
    $env:OPENBLAS_NUM_THREADS = "1"  # see S2 report: avoids ~235 MB OpenBLAS commit
    "== stt_bench $(Get-Date -Format T)"
    & $uv run --group spikes python spikes/latency/stt_bench.py --reps 10 2>&1 | ForEach-Object { "$_" }
    "== ram_probe $(Get-Date -Format T)"
    & $uv run --group spikes python spikes/latency/ram_probe.py 2>&1 | ForEach-Object { "$_" }
}
"== llm_bench $($Models -join ',') $(Get-Date -Format T)"
& $uv run --group spikes python spikes/latency/llm_bench.py --models @Models --reps 3 2>&1 | ForEach-Object { "$_" }
"== routing $($Models -join ',') $(Get-Date -Format T)"
& $uv run --group spikes python spikes/routing/eval_routing.py --models @Models 2>&1 | ForEach-Object { "$_" }
"== done $(Get-Date -Format T)"
