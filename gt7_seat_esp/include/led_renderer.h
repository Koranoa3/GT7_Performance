#ifndef LED_RENDERER_H
#define LED_RENDERER_H

#include <FastLED.h>

#include "gt7_types.h"

namespace gt7
{
class LedRenderer
{
public:
  void setup();
  void update(const TelemetryState &telemetry,
              bool race_active,
              bool collision_active,
              uint32_t collision_elapsed_ms,
              bool lap_flash_active,
              uint32_t lap_flash_elapsed_ms);

private:
  CRGB base_leds_[GT7_BASE_LED_COUNT] = {};
  CRGB monitor_leds_[GT7_MONITOR_LED_COUNT] = {};

  Segment base_ripple_left_{base_leds_, 0, GT7_BASE_LED_COUNT / 2};
  Segment base_ripple_right_{base_leds_, GT7_BASE_LED_COUNT / 2, GT7_BASE_LED_COUNT};
  Segment base_left_{base_leds_, 0, GT7_BASE_LED_COUNT / 4};
  Segment base_right_{base_leds_, GT7_BASE_LED_COUNT / 4, GT7_BASE_LED_COUNT / 2};
  Segment rail_left_{base_leds_, GT7_BASE_LED_COUNT / 2, (GT7_BASE_LED_COUNT * 3) / 4};
  Segment rail_right_{base_leds_, (GT7_BASE_LED_COUNT * 3) / 4, GT7_BASE_LED_COUNT};

  Segment monitor_ripple_left_{monitor_leds_, 0, GT7_MONITOR_LED_COUNT / 2};
  Segment monitor_ripple_right_{monitor_leds_, GT7_MONITOR_LED_COUNT / 2, GT7_MONITOR_LED_COUNT};
  Segment monitor_left_{monitor_leds_, 0, GT7_MONITOR_LED_COUNT / 3};
  Segment monitor_right_{monitor_leds_, GT7_MONITOR_LED_COUNT / 3, (GT7_MONITOR_LED_COUNT * 2) / 3};
  Segment monitor_bottom_{monitor_leds_, (GT7_MONITOR_LED_COUNT * 2) / 3, GT7_MONITOR_LED_COUNT};

  uint32_t last_led_render_ms_ = 0;
  uint32_t last_animation_ms_ = 0;
  float speed_mileage_ = 0.0f;
  float idle_ripple_prev_ = 0.0f;

  static uint16_t segmentLength(const Segment &segment);
  static uint16_t segmentIndex(const Segment &segment, uint16_t offset);
  static void fillSegment(const Segment &segment, const CRGB &color);
  static void fillRatioRange(const Segment &segment, float from_ratio, float to_ratio, const CRGB &color);

  void gaugeAnimation(CRGB leds[], uint16_t start, uint16_t end, float value) const;
  void speedAnimation(const TelemetryState &telemetry, CRGB leds[], uint16_t start, uint16_t end, float value) const;
  void rpmAnimation(const TelemetryState &telemetry, CRGB leds[], uint16_t start, uint16_t end) const;
  void whiteRippleAnimation(CRGB leds[], uint16_t start, uint16_t end, float value) const;
  void collisionBlinkAnimation(CRGB leds[], uint16_t start, uint16_t end, uint32_t elapsed_ms) const;
  void whiteFlashAnimation(CRGB leds[], uint16_t start, uint16_t end, uint32_t elapsed_ms) const;

  void renderIdle();
  void renderRace(const TelemetryState &telemetry,
                  bool collision_active,
                  uint32_t collision_elapsed_ms,
                  bool lap_flash_active,
                  uint32_t lap_flash_elapsed_ms);
};
}  // namespace gt7

#endif  // LED_RENDERER_H
