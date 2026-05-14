#ifndef HARDWARE_CONTROLLER_H
#define HARDWARE_CONTROLLER_H

#include "gt7_types.h"

namespace gt7
{
class HardwareController
{
public:
  void setup();
  void triggerCollisionVibration(uint32_t now, uint8_t strength);
  void updateActuators(const TelemetryState &telemetry, bool telemetry_fresh);
  void updateStatusLed(bool link_healthy);

private:
  uint32_t collision_vibration_started_ms_ = 0;
  uint32_t collision_vibration_duration_ms_ = 0;
  uint32_t last_status_toggle_ms_ = 0;
  bool status_led_on_ = false;

  uint32_t collisionVibrationDurationForStrength(uint8_t strength) const;
};
}  // namespace gt7

#endif  // HARDWARE_CONTROLLER_H
