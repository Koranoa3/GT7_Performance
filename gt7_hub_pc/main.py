from __future__ import annotations

import signal

if not hasattr(signal, "SIGQUIT"):
    signal.SIGQUIT = signal.SIGTERM
if not hasattr(signal, "SIGABRT"):
    signal.SIGABRT = signal.SIGTERM

from gt7_runtime import main


if __name__ == "__main__":
    raise SystemExit(main())
