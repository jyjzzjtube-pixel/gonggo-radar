# 공공공고 레이더 - GitHub 저장소 생성 + Pages 배포
# 선행조건: gh auth login (사장님 1회 브라우저 로그인)
# 실행 후 주소는 영구히 바뀌지 않는다.

$ErrorActionPreference = "Stop"
$REPO = "gonggo-radar"
Set-Location "C:\Users\jyjzz\WORKSPACE\apps\gonggo_radar"

Write-Host "[1/6] GitHub 로그인 확인" -ForegroundColor Cyan
$auth = gh auth status 2>&1 | Out-String
if ($auth -match "not logged") {
    Write-Host ""
    Write-Host "  GitHub 로그인이 안 되어 있습니다." -ForegroundColor Yellow
    Write-Host "  아래를 먼저 실행하세요 (브라우저에서 1회 승인):" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "      gh auth login --web --scopes repo,workflow" -ForegroundColor White
    Write-Host ""
    exit 1
}
$USER = (gh api user --jq .login).Trim()
Write-Host "  로그인: $USER" -ForegroundColor Green

Write-Host "[2/6] 저장소 확인 및 생성" -ForegroundColor Cyan
$exists = $true
try { gh repo view "$USER/$REPO" 2>&1 | Out-Null } catch { $exists = $false }
if (-not $exists) {
    # public 이어야 GitHub Pages와 Actions 무제한이 무료다.
    # 저장소에는 공개된 공고 데이터만 들어가며, 개인 조건은 폰에만 저장된다.
    gh repo create $REPO --public --source=. --remote=origin --description "LH·SH·GH 공고 통합 검색 PWA"
    Write-Host "  생성됨: $USER/$REPO" -ForegroundColor Green
} else {
    Write-Host "  기존 저장소 사용: $USER/$REPO" -ForegroundColor Green
    if (-not (git remote | Select-String origin)) {
        git remote add origin "https://github.com/$USER/$REPO.git"
    }
}

Write-Host "[3/6] 코드 push" -ForegroundColor Cyan
git push -u origin main

Write-Host "[4/6] GitHub Pages 활성화 (Actions 소스)" -ForegroundColor Cyan
try {
    gh api -X POST "repos/$USER/$REPO/pages" -f "build_type=workflow" 2>&1 | Out-Null
    Write-Host "  Pages 활성화 완료" -ForegroundColor Green
} catch {
    Write-Host "  Pages가 이미 활성화되어 있거나 곧 활성화됩니다" -ForegroundColor Yellow
}

Write-Host "[5/6] 첫 수집 워크플로 실행" -ForegroundColor Cyan
Start-Sleep -Seconds 3
try { gh workflow run collect.yml } catch { Write-Host "  push 트리거로 이미 실행 중" -ForegroundColor Yellow }

Write-Host "[6/6] 완료" -ForegroundColor Cyan
$URL = "https://$USER.github.io/$REPO/"
Write-Host ""
Write-Host "  ==================================================" -ForegroundColor Green
Write-Host "   앱 주소 (영구):  $URL" -ForegroundColor White
Write-Host "  ==================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  첫 배포는 2~4분 걸립니다. 진행 상황:" -ForegroundColor Gray
Write-Host "      gh run watch" -ForegroundColor White
Write-Host ""
Write-Host "  폰에서 위 주소를 열고 [설치] 버튼을 누르면 앱으로 깔립니다." -ForegroundColor Gray
Write-Host "  이후 하루 3회(07/13/19시) 자동 수집됩니다. PC는 꺼져 있어도 됩니다." -ForegroundColor Gray
Write-Host ""
$URL | Set-Clipboard
Write-Host "  (주소가 클립보드에 복사되었습니다)" -ForegroundColor Gray
