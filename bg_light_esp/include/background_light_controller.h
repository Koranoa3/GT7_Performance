#ifndef BACKGROUND_LIGHT_CONTROLLER_H
#define BACKGROUND_LIGHT_CONTROLLER_H

#include <FastLED.h>

#include "bg_light_config.h"

namespace bg_light
{
class BackgroundLightController
{
public:
  void setup();
  void loop();

private:
  static_assert(BG_LIGHT_LEFT_LED_COUNT > 0, "BG_LIGHT_LEFT_LED_COUNT must be greater than zero.");
  static_assert(BG_LIGHT_RIGHT_LED_COUNT > 0, "BG_LIGHT_RIGHT_LED_COUNT must be greater than zero.");

  CRGB left_leds_[BG_LIGHT_LEFT_LED_COUNT] = {};
  CRGB right_leds_[BG_LIGHT_RIGHT_LED_COUNT] = {};

  uint32_t last_render_ms_ = 0;
  float hue_phase_ratio_ = 0.0f;
  float light_point_ratio_ = 0.0f;

  static float wrap01(float value);
  static float circularDistance(float a, float b);
  static float computeBrightness01(float position, float light_point_ratio);
  static CRGB hsvToRgb(float hue_ratio, float saturation, float value);
  static void renderStrip(CRGB leds[],
                          uint16_t led_count,
                          float hue_phase_ratio,
                          float light_point_ratio,
                          bool reverse_direction);
};
}  // namespace bg_light

#endif  // BACKGROUND_LIGHT_CONTROLLER_H
