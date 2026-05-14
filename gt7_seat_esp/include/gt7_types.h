#ifndef GT7_TYPES_H
#define GT7_TYPES_H

#include <FastLED.h>

#include "gt7_config.h"

namespace gt7
{
enum class FrameType : uint8_t
{
  Ping = 1,
  Pong = 2,
  Telemetry = 3,
  Bind = 4,
  Event = 5,
  Ack = 6,
  SectionPreview = 7,
};

enum EventId : uint8_t
{
  EventCollision = 1,
  EventLap = 2,
};

enum PlayState : uint8_t
{
  PlayIdle = 0,
  PlayRace = 1,
};

enum LedStripId : uint8_t
{
  LedStripBase = 0,
  LedStripMonitor = 1,
};

struct TelemetryState
{
  float car_speed = 0.0f;
  float engine_rpm = 0.0f;
  float rpm_alert_min = 0.0f;
  float rpm_alert_max = 0.0f;
  uint8_t throttle = 0;
  int8_t current_gear = -1;
  float velocity_right = 0.0f;
  uint8_t play_state = PlayIdle;
};

struct Frame
{
  FrameType type = FrameType::Ping;
  uint8_t flags = 0;
  uint16_t seq = 0;
  uint16_t device_id = 0;
  uint8_t payload[config::kMaxPayloadSize];
  uint16_t payload_len = 0;
};

struct Segment
{
  constexpr Segment() = default;
  constexpr Segment(CRGB *leds_value, uint16_t start_value, uint16_t end_value)
      : leds(leds_value), start(start_value), end(end_value)
  {
  }

  CRGB *leds = nullptr;
  uint16_t start = 0;
  uint16_t end = 0;
};
}  // namespace gt7

#endif  // GT7_TYPES_H
