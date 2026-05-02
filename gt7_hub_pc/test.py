from granturismo.intake import Listener
import datetime as dt
import time, sys
import signal

# Windows では SIGQUIT, SIGABRT が存在しないため、SIGTERM に割り当てる
if not hasattr(signal, "SIGQUIT"):
    signal.SIGQUIT = signal.SIGTERM
if not hasattr(signal, "SIGABRT"):
    signal.SIGABRT = signal.SIGTERM


if __name__ == '__main__':
  ip_address = sys.argv[1]

  # To use the Listener session without a `with` clause, you'll need to call the `.start()` function. 
  listener = Listener(ip_address)

  try:
    with listener:
        count = 0
        while True:
            # get the latest packet from PlayStation
            packet = listener.get(timeout=0.1)

            if not packet.flags.loading_or_processing and not packet.flags.paused:
                throttle = packet.throttle
            
                # print the throttle value to the console
                if count % 10 == 0:  # Print every 10th packet
                    print(f"Throttle: {throttle}")
            count += 1
        
        
  finally:
    listener.close()