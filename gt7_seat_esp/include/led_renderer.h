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
  void update(AnimationStatus animation_status,
              const TelemetryState &telemetry,
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
  CRGB arm_left_leds_[GT7_ARM_LEFT_LED_COUNT] = {};
  CRGB arm_right_leds_[GT7_ARM_RIGHT_LED_COUNT] = {};

  Segment base_ripple_left_{base_leds_, 105, 1};
  Segment base_ripple_right_{base_leds_, 203, 106};
  Segment rail_right_{base_leds_, 1, 46};
  Segment base_right_{base_leds_, 105, 57};
  Segment base_left_{base_leds_, 106, 146};
  Segment rail_left_{base_leds_, 203, 159};
  Segment arm_bottom_{base_leds_, 257, 278};

  Segment monitor_ripple_left_{monitor_leds_, 0, 67};
  Segment monitor_ripple_right_{monitor_leds_, 68, 135};
  Segment monitor_left_{monitor_leds_,135, 102};
  Segment monitor_right_{monitor_leds_, 0, 33};
  Segment monitor_bottom_{monitor_leds_, 39, 96};
  Segment arm_left_{arm_left_leds_, 3, 22};
  Segment arm_right_{arm_right_leds_, 2, 21};

  uint32_t last_led_render_ms_ = 0;
  uint32_t last_animation_ms_ = 0;
  float speed_mileage_ = 0.0f;
  float idle_ripple_prev_ = 0.0f;
  int8_t last_gear_ = -127;
  float gear_offset_flash_ = 0.0f;
  PreviewState preview_;

  static uint16_t segmentLength(const Segment &segment);
  static uint16_t segmentIndex(const Segment &segment, uint16_t offset);
  static uint16_t clampIndex(uint16_t index, uint16_t led_count);
  static void fillSegment(const Segment &segment, const CRGB &color);
  static void fillInclusiveRange(CRGB leds[], uint16_t led_count, uint16_t start_index, uint16_t end_index, const CRGB &color);
  static void fillRatioRange(const Segment &segment, float from_ratio, float to_ratio, const CRGB &color);
  static CRGB gaugeColorForGear(int8_t current_gear);
  static float gearGlowPointForGear(int8_t current_gear);
  static float gearGlowBaseOffsetForGear(int8_t current_gear);
  static void animatedGaugeFill(const Segment &segment, float value, const CRGB &base_color);

  void gaugeAnimation(CRGB leds[], uint16_t start, uint16_t end, float value, const CRGB &color) const;
  void gearGlowAnimation(const Segment &segment, int8_t current_gear) const;
  void speedAnimation(const TelemetryState &telemetry, CRGB leds[], uint16_t start, uint16_t end, float value) const;
  void rpmAnimation(const TelemetryState &telemetry, CRGB leds[], uint16_t start, uint16_t end) const;
  void whiteRippleAnimation(CRGB leds[], uint16_t start, uint16_t end, float value) const;
  void collisionBlinkAnimation(CRGB leds[], uint16_t start, uint16_t end, uint32_t elapsed_ms) const;
  void whiteFlashAnimation(CRGB leds[], uint16_t start, uint16_t end, uint32_t elapsed_ms) const;

  void renderSleep();
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
