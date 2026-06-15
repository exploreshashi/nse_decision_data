"""
Web launcher: starts Streamlit on port 8501 and opens a public ngrok tunnel.
Run with:  python launch_web.py
Then share the https://xxxx.ngrok-free.app URL with your browser or phone.

First time: get a free authtoken at https://dashboard.ngrok.com/get-started/your-authtoken
Then run:  python launch_web.py --setup YOUR_TOKEN
"""

import sys
import os
import time
import subprocess
import argparse

STREAMLIT_PORT = 8501
NGROK_TOKEN_FILE = os.path.join(os.path.dirname(__file__), "data", "ngrok_token.txt")


def save_token(token: str):
    os.makedirs(os.path.dirname(NGROK_TOKEN_FILE), exist_ok=True)
    with open(NGROK_TOKEN_FILE, "w") as f:
        f.write(token.strip())
    print(f"Token saved to {NGROK_TOKEN_FILE}")


def load_token() -> str | None:
    if os.path.exists(NGROK_TOKEN_FILE):
        with open(NGROK_TOKEN_FILE) as f:
            return f.read().strip()
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--setup", metavar="TOKEN", help="Save ngrok authtoken and exit")
    parser.add_argument("--port", type=int, default=STREAMLIT_PORT)
    args = parser.parse_args()

    if args.setup:
        save_token(args.setup)
        from pyngrok import ngrok
        ngrok.set_auth_token(args.setup)
        print("Ngrok token configured. Run 'python launch_web.py' to start.")
        return

    token = load_token()
    if not token:
        print(
            "\nNo ngrok token found.\n"
            "1. Sign up free at https://dashboard.ngrok.com\n"
            "2. Copy your authtoken\n"
            "3. Run:  python launch_web.py --setup YOUR_TOKEN\n"
            "4. Then run:  python launch_web.py\n"
        )
        sys.exit(1)

    try:
        from pyngrok import ngrok, conf
    except ImportError:
        print("Install pyngrok:  pip install pyngrok")
        sys.exit(1)

    # Configure token
    ngrok.set_auth_token(token)

    # Start Streamlit as a subprocess
    print(f"Starting Streamlit on port {args.port}...")
    streamlit_proc = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", "app.py",
         "--server.port", str(args.port),
         "--server.headless", "true",
         "--server.enableCORS", "false",
         "--server.enableXsrfProtection", "false"],
        cwd=os.path.dirname(__file__),
    )

    # Wait for Streamlit to start
    time.sleep(3)

    # Open ngrok tunnel
    print("Opening ngrok tunnel...")
    tunnel = ngrok.connect(args.port, "http")
    public_url = tunnel.public_url

    print("\n" + "=" * 60)
    print(f"  Dashboard URL:  {public_url}")
    print(f"  Local URL:      http://localhost:{args.port}")
    print("=" * 60)
    print("Share the URL above to access from any browser or phone.")
    print("Press Ctrl+C to stop.\n")

    try:
        streamlit_proc.wait()
    except KeyboardInterrupt:
        print("\nShutting down...")
        ngrok.kill()
        streamlit_proc.terminate()


if __name__ == "__main__":
    main()
