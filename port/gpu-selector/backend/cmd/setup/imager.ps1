$ErrorActionPreference = 'Stop'
function Find-Pixel2Imager {
    foreach ($root in @($env:ProgramFiles, ${env:ProgramFiles(x86)}, $env:LOCALAPPDATA)) {
        if (!$root) { continue }
        foreach ($relative in @('Raspberry Pi Ltd\Imager\rpi-imager.exe','Raspberry Pi Imager\rpi-imager.exe','Programs\Raspberry Pi Ltd\Imager\rpi-imager.exe')) {
            $candidate = Join-Path $root $relative
            if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
        }
    }
}
$imager = Find-Pixel2Imager
if (!$imager) {
    Add-Type -AssemblyName System.Windows.Forms
    $answer = [Windows.Forms.MessageBox]::Show('已生成完整镜像。现在从 Raspberry Pi 官方下载并打开 Imager 安装程序吗？安装结束后将继续选择 TF 卡。','GKD Pixel 2','YesNo','Question')
    if ($answer -ne [Windows.Forms.DialogResult]::Yes) { exit 0 }
    $dir = Join-Path ([IO.Path]::GetTempPath()) ('Pixel2-Imager-'+[guid]::NewGuid().ToString('N'))
    [void][IO.Directory]::CreateDirectory($dir)
    $installer = Join-Path $dir 'imager-v2.0.12.exe'
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        $uri = 'https://github.com/raspberrypi/rpi-imager/releases/download/v2.0.12/imager-v2.0.12.exe'
        $client = New-Object Net.WebClient
        try { $client.DownloadFile($uri,$installer) } finally { $client.Dispose() }
        if ((Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash -ine '98bff90afe23339d0768915f6f68d35ac254740ec1eac2082ebeaa9ba41bc8e3') { throw '官方刷卡器校验失败' }
        $result = Start-Process -FilePath $installer -Wait -PassThru
        if ($result.ExitCode -ne 0) { throw '刷卡器安装尚未完成。镜像已保存，可以稍后继续。' }
    } finally {
        if ([IO.File]::Exists($installer)) { [IO.File]::Delete($installer) }
        if ([IO.Directory]::Exists($dir) -and [IO.Directory]::GetFileSystemEntries($dir).Length -eq 0) { [IO.Directory]::Delete($dir,$false) }
    }
    $imager = Find-Pixel2Imager
    if (!$imager) {
        $association = [Microsoft.Win32.Registry]::ClassesRoot.OpenSubKey('.rpi-imager-manifest')
        if ($association) {
            $association.Dispose()
            Start-Process -FilePath $env:PIXEL2_LOCAL_MANIFEST
            exit 0
        }
        throw '已保存镜像。请在 Raspberry Pi Imager 的「使用自定义镜像」中选择它。'
    }
}
if ($env:PIXEL2_LOCAL_MANIFEST.Contains('"')) { throw '无效的清单路径' }
Start-Process -FilePath $imager -ArgumentList ('--repo "'+$env:PIXEL2_LOCAL_MANIFEST+'"')
