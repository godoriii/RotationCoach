<#
.SYNOPSIS
    M0 검증: 저장된 WCL 클라이언트 값으로 API v2를 호출해 보고 요청 점수 소모를 잰다.

.DESCRIPTION
    1) 토큰 발급 (client credentials)
    2) 현재 요청 한도 조회
    3) 보스 목록 조회 → 대상 보스 선택
    4) 사냥꾼 전문화 상위 랭킹 1쪽 조회
    5) 1위 로그의 시전 이벤트 조회 → 첫 시전 12개의 주문 ID 출력
    각 단계 뒤에 소모 점수를 출력한다. 플레이어 이름은 출력하지 않는다.

    먼저 tools\Save-WclCredential.ps1 -Kind confidential 로 값을 저장해 두어야 한다.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tools\Test-WclApi.ps1 -Spec Survival
#>
[CmdletBinding()]
param(
    [string]$CredentialPath = (Join-Path $env:APPDATA 'RotationTeacher\wcl-client.xml'),
    [ValidateSet('BeastMastery', 'Marksmanship', 'Survival')]
    [string]$Spec = 'Survival',
    [int]$Difficulty = 5,          # 5 = 신화, 4 = 영웅, 3 = 일반
    [int]$EncounterId = 0          # 0 이면 목록에서 자동 선택
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$TokenUrl = 'https://www.warcraftlogs.com/oauth/token'
$ApiUrl = 'https://www.warcraftlogs.com/api/v2/client'

# @($null).Count 는 1이므로, 비어 있는 목록을 안전하게 배열로 바꾼다.
function ConvertTo-List($Value) {
    return , @($Value | Where-Object { $null -ne $_ })
}

function ConvertTo-PlainText([System.Security.SecureString]$Secure) {
    if ($null -eq $Secure) { return '' }
    return (New-Object System.Net.NetworkCredential('', $Secure)).Password
}

if (-not (Test-Path -LiteralPath $CredentialPath)) {
    throw "저장된 값이 없습니다: $CredentialPath  (먼저 tools\Save-WclCredential.ps1 -Kind confidential 실행)"
}
$saved = Import-Clixml -LiteralPath $CredentialPath
if ($saved.Kind -ne 'confidential') {
    throw 'PKCE 클라이언트로는 이 검증을 할 수 없습니다. PKCE 체크를 해제한 클라이언트를 만들어 -Kind confidential 로 저장하세요.'
}

# 1) 토큰
$pair = '{0}:{1}' -f (ConvertTo-PlainText $saved.ClientId), (ConvertTo-PlainText $saved.ClientSecret)
$basic = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes($pair))
$tokenResponse = Invoke-RestMethod -Method Post -Uri $TokenUrl -Headers @{ Authorization = "Basic $basic" } `
    -Body @{ grant_type = 'client_credentials' }
$token = $tokenResponse.access_token
Write-Host ("1) 토큰 발급 성공 (만료까지 {0:N0}일)" -f ($tokenResponse.expires_in / 86400))

function Invoke-Wcl([string]$Query, [hashtable]$Variables = @{}) {
    $body = @{ query = $Query; variables = $Variables } | ConvertTo-Json -Depth 10 -Compress
    $response = Invoke-RestMethod -Method Post -Uri $ApiUrl -ContentType 'application/json' `
        -Headers @{ Authorization = "Bearer $token"; Accept = 'application/json' } `
        -Body ([Text.Encoding]::UTF8.GetBytes($body))
    if ($response.PSObject.Properties.Name -contains 'errors') {
        throw ('GraphQL 오류: ' + ($response.errors | ConvertTo-Json -Depth 5 -Compress))
    }
    return $response.data
}

function Get-Points {
    $d = Invoke-Wcl '{ rateLimitData { limitPerHour pointsSpentThisHour pointsResetIn } }'
    return $d.rateLimitData
}

$script:lastSpent = $null
function Show-Cost([string]$Label) {
    $r = Get-Points
    if ($null -ne $script:lastSpent) {
        Write-Host ("   {0}: 약 {1:N1}점 소모 (누적 {2:N1} / 시간당 {3:N0})" -f $Label, ($r.pointsSpentThisHour - $script:lastSpent), $r.pointsSpentThisHour, $r.limitPerHour)
    }
    $script:lastSpent = $r.pointsSpentThisHour
    return $r
}

# 2) 한도
$limit = Show-Cost '시작'
Write-Host ("2) 요청 한도: 시간당 {0:N0}점, 지금까지 {1:N1}점 사용, {2:N0}초 뒤 초기화" -f $limit.limitPerHour, $limit.pointsSpentThisHour, $limit.pointsResetIn)

# 3) 보스 목록
$world = Invoke-Wcl '{ worldData { expansions { id name zones { id name frozen encounters { id name } } } } }'
$latest = $world.worldData.expansions | Sort-Object id -Descending | Select-Object -First 1
Write-Host "3) 최신 확장팩: $($latest.name)"
$zones = ConvertTo-List ($latest.zones | Where-Object { -not $_.frozen -and (ConvertTo-List $_.encounters).Count -gt 0 })
if ($zones.Count -eq 0) { throw '보스가 있는 지역을 찾지 못했습니다.' }
foreach ($z in $zones) {
    Write-Host ("   지역 {0}: {1} (보스 {2}개)" -f $z.id, $z.name, (ConvertTo-List $z.encounters).Count)
}
Show-Cost '보스 목록' | Out-Null

if ($EncounterId -eq 0) {
    $raid = $zones | Where-Object { $_.name -notmatch 'Mythic\+|Dungeon|Delve|Beta|PTR' } | Sort-Object id -Descending | Select-Object -First 1
    if ($null -eq $raid) { $raid = $zones | Select-Object -First 1 }
    $encounter = (ConvertTo-List $raid.encounters)[0]
    $EncounterId = $encounter.id
    Write-Host "   자동 선택: [$($raid.name)] $($encounter.name) (ID $EncounterId). 바꾸려면 -EncounterId 지정"
}

# 4) 랭킹
$rankQuery = 'query($enc: Int!, $spec: String!, $diff: Int!) { worldData { encounter(id: $enc) { name characterRankings(className: "Hunter", specName: $spec, difficulty: $diff, metric: dps, page: 1) } } }'
$rankData = Invoke-Wcl $rankQuery @{ enc = $EncounterId; spec = $Spec; diff = $Difficulty }
$rankings = $rankData.worldData.encounter.characterRankings
if ($rankings -is [string]) { $rankings = $rankings | ConvertFrom-Json }
if ($null -eq $rankings -or $rankings.PSObject.Properties.Name -notcontains 'rankings') {
    Write-Host ('   랭킹 응답 형식이 예상과 다릅니다: ' + ($rankings | ConvertTo-Json -Depth 4 -Compress))
    return
}
$rows = ConvertTo-List $rankings.rankings
Write-Host ("4) 랭킹: {0} / {1} / 난이도 {2} → {3}건" -f $rankData.worldData.encounter.name, $Spec, $Difficulty, $rows.Count)
Show-Cost '랭킹 1쪽' | Out-Null
if ($rows.Count -eq 0) {
    Write-Host '   랭킹이 비어 있습니다. -Difficulty 4 또는 다른 -EncounterId 로 다시 시도하세요.'
    return
}

# 5) 1위 로그의 시전 이벤트
$top = $rows[0]
$code = $top.report.code
$fightId = [int]$top.report.fightID
$metaQuery = 'query($code: String!, $fid: Int!) { reportData { report(code: $code) { fights(fightIDs: [$fid]) { startTime endTime } masterData { actors(type: "Player") { id name } } } } }'
$meta = Invoke-Wcl $metaQuery @{ code = $code; fid = $fightId }
$fight = (ConvertTo-List $meta.reportData.report.fights)[0]
if ($null -eq $fight) { throw '리포트에서 해당 전투를 찾지 못했습니다.' }
$actor = $meta.reportData.report.masterData.actors | Where-Object { $_.name -eq $top.name } | Select-Object -First 1
if ($null -eq $actor) { throw '랭킹의 플레이어를 리포트 참가자 목록에서 찾지 못했습니다.' }
Show-Cost '리포트 정보' | Out-Null

$eventQuery = 'query($code: String!, $fid: Int!, $src: Int!, $start: Float!, $end: Float!) { reportData { report(code: $code) { events(dataType: Casts, fightIDs: [$fid], sourceID: $src, startTime: $start, endTime: $end, limit: 10000) { data nextPageTimestamp } } } }'
$events = Invoke-Wcl $eventQuery @{ code = $code; fid = $fightId; src = [int]$actor.id; start = [double]$fight.startTime; end = [double]$fight.endTime }
$casts = ConvertTo-List ($events.reportData.report.events.data | Where-Object { $_.type -eq 'cast' })
$seconds = ($fight.endTime - $fight.startTime) / 1000
Write-Host ("5) 1위 로그: 전투 {0:N0}초, 시전 {1}회, 다음 쪽 있음: {2}" -f $seconds, $casts.Count, ($null -ne $events.reportData.report.events.nextPageTimestamp))
$casts | Select-Object -First 12 | ForEach-Object {
    Write-Host ("   {0,6:N2}초  주문 {1}" -f (($_.timestamp - $fight.startTime) / 1000), $_.abilityGameID)
}
Show-Cost '시전 이벤트 1건' | Out-Null
Write-Host '완료. 위 출력 전체를 복사해서 알려 주세요.'
