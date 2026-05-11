#!/usr/bin/env bash
# Ebenezer 1-shot 설치 스크립트 (Oracle Free Tier Ubuntu 22.04)
set -euo pipefail

REPO_DIR="/home/ubuntu/asterdex-copytrader"
LOG_DIR="/var/log/copytrader"
LIB_DIR="/var/lib/copytrader"

echo "====== Ebenezer 설치 시작 ======"

# 시스템 패키지
sudo apt-get update -qq
sudo apt-get install -y python3.10 python3-pip python3-venv git sqlite3

# 디렉토리
sudo mkdir -p "$LOG_DIR" "$LIB_DIR"
sudo chown "$USER":"$USER" "$LOG_DIR" "$LIB_DIR"

# 가상환경 + 의존성
cd "$REPO_DIR"
python3 -m venv venv
source venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt

# .env 확인
if [ ! -f .env ]; then
    cp .env.example .env
    echo "⚠️  .env 파일이 생성됐습니다. API 키를 입력하세요: nano $REPO_DIR/.env"
fi

# 단위 테스트
echo "단위 테스트 실행..."
python -m pytest tests/unit/ -q

# systemd 등록
sudo cp deploy/copytrader.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable copytrader

# logrotate
sudo cp deploy/logrotate.conf /etc/logrotate.d/copytrader

echo ""
echo "====== 설치 완료 ======"
echo "1. .env에 API 키 입력 후:"
echo "   sudo systemctl start copytrader"
echo "2. 로그 확인:"
echo "   journalctl -u copytrader -f"
echo "3. DRY_RUN 1주일 검증 후 실거래 전환:"
echo "   python main.py --live"
