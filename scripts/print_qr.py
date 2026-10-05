"""Print an ASCII QR code for the URL given as the first argument.

Exit codes: 0 = printed, 1 = not printable (missing qrcode package, bad URL,
or a console that cannot render it). Callers must treat failure as cosmetic.
"""
import sys


def main() -> int:
    url = sys.argv[1] if len(sys.argv) > 1 else ""
    if not url:
        return 1
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass  # older Pythons / unusual streams — best effort only
    try:
        import qrcode

        qr = qrcode.QRCode(border=1)
        qr.add_data(url)
        qr.print_ascii(invert=True)
        return 0
    except Exception:
        return 1


if __name__ == "__main__":
    sys.exit(main())
