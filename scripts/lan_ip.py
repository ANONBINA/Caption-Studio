"""Print this machine's LAN IPv4 address (best-effort, empty output on failure).

Used by scripts/serve.sh and scripts/serve.bat in mobile (--lan) mode.
The UDP "connect" trick makes the OS pick the default-route adapter without
sending any traffic.
"""
import socket


def main() -> None:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        print(s.getsockname()[0])
    except OSError:
        pass  # no default route — caller shows manual instructions
    finally:
        s.close()


if __name__ == "__main__":
    main()
