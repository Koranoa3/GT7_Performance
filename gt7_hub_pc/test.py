import datetime as dt
import time, sys
import signal

from gt7_runtime import RecoveringTelemetrySource

# Windows では SIGQUIT, SIGABRT が存在しないため、SIGTERM に割り当てる
if not hasattr(signal, "SIGQUIT"):
    signal.SIGQUIT = signal.SIGTERM
if not hasattr(signal, "SIGABRT"):
    signal.SIGABRT = signal.SIGTERM


if __name__ == '__main__':
  ip_address = sys.argv[1]
  listener = RecoveringTelemetrySource(ip_address)
  listener.start()

  try:
    count = 0
    while True:
        packet = listener.get(timeout=0.1)

        if not packet.flags.loading_or_processing and not packet.flags.paused:
            throttle = packet.throttle

            if count % 10 == 0:
                print(f"Throttle: {throttle}")
        count += 1
  finally:
    listener.close()
