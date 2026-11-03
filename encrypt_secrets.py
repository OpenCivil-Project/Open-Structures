"""Retired: desktop releases must not contain shared credential bundles."""

def main():
    raise SystemExit(
        "Credential bundling has been retired. Configure Firebase Authentication "
        "using docs/FIREBASE_SETUP.md. Never distribute MongoDB, SMTP, or Firebase "
        "Admin credentials in the desktop application."
    )

if __name__ == "__main__":
    main()
