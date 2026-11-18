<#
.SYNOPSIS
    Warcraft Logs API 클라이언트 값을 DPAPI로 암호화해 XML 파일로 저장한다.

.DESCRIPTION
    값은 화면에 보이지 않게 입력받고(SecureString), Export-Clixml로 저장한다.
    Windows에서 SecureString은 DPAPI(현재 Windows 사용자 + 이 PC)로 암호화되므로,
    저장된 XML은 같은 PC의 같은 사용자 계정에서만 복호화된다.
    클라이언트 ID/시크릿 값은 이 스크립트나 저장소 어디에도 적지 않는다.

    기본 저장 위치: %APPDATA%\RotationTeacher\wcl-client.xml  (저장소 밖, OneDrive 동기화 대상 아님)

.PARAMETER Kind
    pkce         : PKCE 클라이언트 (시크릿 없음, 클라이언트 ID만 저장)
    confidential : 일반 클라이언트 (클라이언트 ID + 시크릿 저장)

.PARAMETER RedirectUri
    PKCE 클라이언트에 등록한 리디렉션 URL. 비밀이 아니므로 평문으로 저장한다.

.PARAMETER Show
    저장된 파일을 복호화해서 앞 4글자만 보여 준다 (저장 확인용).

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tools\Save-WclCredential.ps1 -Kind pkce -RedirectUri "http://localhost:8765/callback"

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tools\Save-WclCredential.ps1 -Show
#>
[CmdletBinding()]
param(
    [string]$Path = (Join-Path $env:APPDATA 'RotationTeacher\wcl-client.xml'),
    [ValidateSet('pkce', 'confidential')]
    [string]$Kind = 'pkce',
    [string]$RedirectUri = '',
    [switch]$Show
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

if ($env:OS -ne 'Windows_NT') {
    throw 'DPAPI는 Windows에서만 동작합니다. WoW를 실행하는 Windows PC에서 실행하세요.'
}

function ConvertTo-PlainText([System.Security.SecureString]$Secure) {
    if ($null -eq $Secure) { return '' }
    return (New-Object System.Net.NetworkCredential('', $Secure)).Password
}

function Get-Masked([string]$Text) {
    if ([string]::IsNullOrEmpty($Text)) { return '(없음)' }
    $head = $Text.Substring(0, [Math]::Min(4, $Text.Length))
    return ('{0}**** ({1}자)' -f $head, $Text.Length)
}

if ($Show) {
    if (-not (Test-Path -LiteralPath $Path)) { throw "파일이 없습니다: $Path" }
    $saved = Import-Clixml -LiteralPath $Path
    Write-Host "파일      : $Path"
    Write-Host "종류      : $($saved.Kind)"
    Write-Host "클라이언트 ID : $(Get-Masked (ConvertTo-PlainText $saved.ClientId))"
    Write-Host "시크릿    : $(Get-Masked (ConvertTo-PlainText $saved.ClientSecret))"
    Write-Host "리디렉션 URL : $($saved.RedirectUri)"
    Write-Host "저장 시각 : $($saved.SavedAt)  ($($saved.SavedBy))"
    return
}

# 저장소 안에 저장하면 실수로 커밋될 수 있으므로 막는다.
$repoRoot = Split-Path -Parent $PSScriptRoot
$fullPath = [System.IO.Path]::GetFullPath($Path)
if ($fullPath.StartsWith([System.IO.Path]::GetFullPath($repoRoot), [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "저장소 폴더 안에는 저장할 수 없습니다: $fullPath"
}

Write-Host 'Warcraft Logs > API Clients 페이지의 값을 붙여넣으세요. 입력 내용은 화면에 표시되지 않습니다.'
$clientId = Read-Host -AsSecureString '클라이언트 ID'
if ((ConvertTo-PlainText $clientId).Trim().Length -eq 0) { throw '클라이언트 ID가 비어 있습니다.' }

$clientSecret = $null
if ($Kind -eq 'confidential') {
    $clientSecret = Read-Host -AsSecureString '클라이언트 시크릿'
    if ((ConvertTo-PlainText $clientSecret).Trim().Length -eq 0) { throw '클라이언트 시크릿이 비어 있습니다.' }
}

$record = [pscustomobject]@{
    Schema       = 1
    Kind         = $Kind
    ClientId     = $clientId          # SecureString -> DPAPI 암호화되어 저장됨
    ClientSecret = $clientSecret      # SecureString 또는 $null
    RedirectUri  = $RedirectUri
    SavedAt      = (Get-Date).ToString('s')
    SavedBy      = "$env:USERNAME@$env:COMPUTERNAME"
}

$dir = Split-Path -Parent $fullPath
if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir | Out-Null }
$record | Export-Clixml -LiteralPath $fullPath

# 저장 직후 다시 읽어 복호화되는지 확인한다.
$check = Import-Clixml -LiteralPath $fullPath
if ((ConvertTo-PlainText $check.ClientId) -ne (ConvertTo-PlainText $clientId)) {
    throw '저장 확인 실패: 다시 읽은 값이 입력값과 다릅니다.'
}
Write-Host "저장 완료: $fullPath"
Write-Host "클라이언트 ID: $(Get-Masked (ConvertTo-PlainText $check.ClientId))"
Write-Host '이 파일은 이 PC의 현재 Windows 계정에서만 복호화됩니다. 다른 PC에서는 다시 실행하세요.'
