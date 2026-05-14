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
  void previewSection(uint8_t strip_id, uint16_t start_index, uint16_t end_index, uint32_t duration_ms = config::kSectionPreviewDurationMs);
  void update(const TelemetryState &telemetry,
              bool race_active,
              bool collision_active,
              uint32_t collision_elapsed_ms,
              bool lap_flash_active,
              uint32_t lap_flash_elapsed_ms);

private:
  struct PreviewState
  {
    bool active = false;
    uint8_t strip_id = LedStripBase;
    uint16_t start_index = 0;
    uint16_t end_index = 0;
    uint32_t expires_at_ms = 0;
  };

  CRGB base_leds_[GT7_BASE_LED_COUNT] = {};
  CRGB monitor_leds_[GT7_MONITOR_LED_COUNT] = {};

  Segment base_ripple_left_{base_leds_, 0, 140};
  Segment base_ripple_right_{base_leds_, 141, 280};
  Segment base_left_{base_leds_, 195, 131};
  Segment base_right_{base_leds_, 51, 130};
  Segment rail_left_{base_leds_, 196, 249};
  Segment rail_right_{base_leds_, 50, 0};

  Segment monitor_ripple_left_{monitor_leds_, 0, 51};
  Segment monitor_ripple_right_{monitor_leds_, 52, 102};
  Segment monitor_left_{monitor_leds_,102, 76};
  Segment monitor_right_{monitor_leds_, 0, 26};
  Segment monitor_bottom_{monitor_leds_, 27, 75};

  uint32_t last_led_render_ms_ = 0;
  uint32_t last_animation_ms_ = 0;
  float speed_mileage_ = 0.0f;
  float idle_ripple_prev_ = 0.0f;
  PreviewState preview_;

  static uint16_t segmentLength(const Segment &segment);
  static uint16_t segmentIndex(const Segment &segment, uint16_t offset);
  static uint16_t clampIndex(uint16_t index, uint16_t led_count);
  static void fillSegment(const Segment &segment, const CRGB &color);
  static void fillInclusiveRange(CRGB leds[], uint16_t led_count, uint16_t start_index, uint16_t end_index, const CRGB &color);
  static void fillRatioRange(const Segment &segment, float from_ratio, float to_ratio, const CRGB &color);
  static CRGB gaugeColorForGear(int8_t current_gear);

  void gaugeAnimation(CRGB leds[], uint16_t start, uint16_t end, float value, int8_t current_gear) const;
  void speedAnimation(const TelemetryState &telemetry, CRGB leds[], uint16_t start, uint16_t end, float value) const;
  void rpmAnimation(const TelemetryState &telemetry, CRGB leds[], uint16_t start, uint16_t end) const;
  void whiteRippleAnimation(CRGB leds[], uint16_t start, uint16_t end, float value) const;
  void collisionBlinkAnimation(CRGB leds[], uint16_t start, uint16_t end, uint32_t elapsed_ms) const;
  void whiteFlashAnimation(CRGB leds[], uint16_t start, uint16_t end, uint32_t elapsed_ms) const;

  void renderIdle();
  bool renderPreview(uint32_t now);
  void renderRace(const TelemetryState &telemetry,
                  bool collision_active,
                  uint32_t collision_elapsed_ms,
                  bool lap_flash_active,
                  uint32_t lap_flash_elapsed_ms);
};
}  // namespace gt7

#endif  // LED_RENDERER_H
