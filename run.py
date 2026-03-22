"""
실행 스크립트

사용법:
  python run.py              # 로컬 네트워크 접속용
  python run.py --public     # 인터넷 외부 접속용 (ngrok 터널)
"""

import argparse
import subprocess
import sys
import socket
import os
from pathlib import Path

PORT = 8501
ROOT = Path(__file__).parent


def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def start_ngrok(port: int):
    try:
        from pyngrok import ngrok, conf

        # ngrok 토큰이 .env에 있으면 사용
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
        token = os.getenv("NGROK_AUTHTOKEN", "")
        if token:
            conf.get_default().auth_token = token

        tunnel = ngrok.connect(port, "http")
        return tunnel.public_url
    except Exception as e:
        print(f"[ngrok 오류] {e}")
        print("ngrok 없이 로컬 네트워크 모드로 실행합니다.")
        return None


def main():
    parser = argparse.ArgumentParser(description="스마트스토어 대표이미지 생성기 실행")
    parser.add_argument("--public", action="store_true", help="ngrok으로 외부 인터넷 접속 허용")
    parser.add_argument("--port", type=int, default=PORT, help=f"포트 번호 (기본: {PORT})")
    args = parser.parse_args()

    local_ip = get_local_ip()

    print("=" * 55)
    print("  🛍️  스마트스토어 대표이미지 생성기")
    print("=" * 55)
    print(f"  [내 PC]         http://localhost:{args.port}")
    print(f"  [같은 와이파이]  http://{local_ip}:{args.port}")

    if args.public:
        print("\n  ngrok 터널 연결 중...")
        public_url = start_ngrok(args.port)
        if public_url:
            print(f"  [인터넷 외부]   {public_url}")
            print("\n  ✅ 위 인터넷 주소를 다른 사람에게 공유하면")
            print("     어디서든 접속할 수 있습니다.")
    else:
        print(f"\n  외부 인터넷 접속을 원하면: python run.py --public")

    print("=" * 55)
    print("  종료: Ctrl+C")
    print("=" * 55)

    # Streamlit 실행
    cmd = [
        sys.executable, "-m", "streamlit", "run",
        str(ROOT / "ui" / "app.py"),
        "--server.port", str(args.port),
        "--server.address", "0.0.0.0",
        "--server.headless", "true",
    ]

    os.environ["PYTHONIOENCODING"] = "utf-8"
    subprocess.run(cmd, cwd=str(ROOT))


if __name__ == "__main__":
    main()
