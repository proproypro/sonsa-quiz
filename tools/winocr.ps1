# Windows 내장 OCR(Windows.Media.Ocr)로 폴더 안 PNG를 읽어 단어 좌표와 함께 JSON으로 저장
# 사용: powershell -ExecutionPolicy Bypass -File tools/winocr.ps1 -Dir <png폴더> -Out <결과.json> [-Lang ko]
param([string]$Dir, [string]$Out, [string]$Lang = "ko")

Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType=WindowsRuntime]
$null = [Windows.Globalization.Language, Windows.Globalization, ContentType=WindowsRuntime]
$null = [Windows.Storage.Streams.IRandomAccessStream, Windows.Storage.Streams, ContentType=WindowsRuntime]
$null = [Windows.Graphics.Imaging.SoftwareBitmap, Windows.Graphics.Imaging, ContentType=WindowsRuntime]
$null = [Windows.Media.Ocr.OcrResult, Windows.Media.Ocr, ContentType=WindowsRuntime]
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType=WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType=WindowsRuntime]
$null = [Windows.Foundation.IAsyncOperation`1, Windows.Foundation, ContentType=WindowsRuntime]

function Await($task, $type) {
  $asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
  $t = $asTask.MakeGenericMethod($type).Invoke($null, @($task))
  $t.Wait() | Out-Null
  $t.Result
}

$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage([Windows.Globalization.Language]::new($Lang))
if (-not $engine) { throw "OCR engine for $Lang not available" }

$result = @{}
Get-ChildItem -Path $Dir -Filter *.png | ForEach-Object {
  try {
    $file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($_.FullName)) ([Windows.Storage.StorageFile])
    $stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
    $decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
    $bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
    $ocr = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
    $words = New-Object System.Collections.ArrayList
    $li = 0
    foreach ($ln in $ocr.Lines) {
      foreach ($w in $ln.Words) {
        $r = $w.BoundingRect
        $null = $words.Add([pscustomobject]@{ t = $w.Text; l = $li; x0 = [math]::Round($r.X); y0 = [math]::Round($r.Y); x1 = [math]::Round($r.X + $r.Width); y1 = [math]::Round($r.Y + $r.Height) })
      }
      $li++
    }
    $result[$_.Name] = $words.ToArray()
    $stream.Dispose()
  } catch {
    $result[$_.Name] = @([pscustomobject]@{ t = ("ERR:" + $_.Exception.Message); l = -1; x0 = 0; y0 = 0; x1 = 0; y1 = 0 })
  }
}
$json = $result | ConvertTo-Json -Depth 6 -Compress
[System.IO.File]::WriteAllText($Out, $json, (New-Object System.Text.UTF8Encoding($false)))
"done " + $result.Count
