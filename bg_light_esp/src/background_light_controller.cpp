#include "background_light_controller.h"

#include <math.h>

namespace bg_light
{
float BackgroundLightController::wrap01(float value)
{
  value = fmodf(value, 1.0f);
  if (value < 0.0f)
  {
    value += 1.0f;
  }
  return value;
}

float BackgroundLightController::circularDistance(float a, float b)
{
  const float delta = fabsf(a - b);
  return delta < (1.0f - delta) ? delta : (1.0f - delta);
}

float BackgroundLightController::computeBrightness01(float position, float light_point_ratio)
{
  const float distance = circularDistance(position, light_point_ratio);
  const float brightness = BG_LIGHT_WAVE_DISTANCE_OFFSET - distance * BG_LIGHT_WAVE_DISTANCE_FACTOR;
  const float clamped = constrain(brightness, 0.0f, 40.0f);
  return clamped / 40.0f;
}

CRGB BackgroundLightController::hsvToRgb(float hue_ratio, float saturation, float value)
{
  const float hue = wrap01(hue_ratio) * 6.0f;
  const float sat = constrain(saturation, 0.0f, 1.0f);
  const float val = constrain(value, 0.0f, 1.0f);
  const int sector = static_cast<int>(floorf(hue)) % 6;
  const float fraction = hue - floorf(hue);

  const float p = val * (1.0f - sat);
  const float q = val * (1.0f - sat * fraction);
  const float t = val * (1.0f - sat * (1.0f - fraction));

  float red = 0.0f;
  float green = 0.0f;
  float blue = 0.0f;

  switch (sector)
  {
    case 0:
      red = val;
      green = t;
      blue = p;
      break;
    case 1:
      red = q;
      green = val;
      blue = p;
      break;
    case 2:
      red = p;
      green = val;
      blue = t;
      break;
    case 3:
      red = p;
      green = q;
      blue = val;
      break;
    case 4:
      red = t;
      green = p;
      blue = val;
      break;
    default:
      red = val;
      green = p;
      blue = q;
      break;
  }

  return CRGB(static_cast<uint8_t>(red * 255.0f + 0.5f),
              static_cast<uint8_t>(green * 255.0f + 0.5f),
              static_cast<uint8_t>(blue * 255.0f + 0.5f));
}

void BackgroundLightController::renderStrip(CRGB leds[],
                                            uint16_t led_count,
                                            float hue_phase_ratio,
                                            float light_point_ratio,
                                            bool reverse_direction)
{
  if (led_count == 0)
  {
    return;
  }

  for (uint16_t index = 0; index < led_count; ++index)
  {
    const float normalized = led_count <= 1
                                 ? 0.0f
                                 : (static_cast<float>(index) + 0.5f) / static_cast<float>(led_count);
    const float position = reverse_direction ? wrap01(1.0f - normalized) : normalized;
    const float hue_cycle_position = (position / config::kHueCycleLengthRatio) + hue_phase_ratio;
    const float hue_ratio = wrap01(hue_cycle_position);
    const float brightness = computeBrightness01(position, light_point_ratio);
    leds[index] = hsvToRgb(hue_ratio, 1.0f, brightness);
  }
}

void BackgroundLightController::setup()
{
  FastLED.addLeds<BG_LIGHT_LED_TYPE, BG_LIGHT_LEFT_LED_PIN, BG_LIGHT_COLOR_ORDER>(left_leds_, BG_LIGHT_LEFT_LED_COUNT);
  FastLED.addLeds<BG_LIGHT_LED_TYPE, BG_LIGHT_RIGHT_LED_PIN, BG_LIGHT_COLOR_ORDER>(right_leds_, BG_LIGHT_RIGHT_LED_COUNT);
  FastLED.setBrightness(BRIGHTNESS);
  FastLED.clear(true);
}

void BackgroundLightController::loop()
{
  const uint32_t now = millis();
  if ((now - last_render_ms_) < config::kLedRefreshIntervalMs)
  {
    return;
  }

  const float delta_seconds = last_render_ms_ == 0 ? 0.0f : static_cast<float>(now - last_render_ms_) / 1000.0f;
  last_render_ms_ = now;

  hue_phase_ratio_ = wrap01(hue_phase_ratio_ + delta_seconds * config::kHueSpeedRatioPerSecond);
  light_point_ratio_ = wrap01(light_point_ratio_ + delta_seconds * config::kLightPointSpeedRatioPerSecond);

  renderStrip(left_leds_, BG_LIGHT_LEFT_LED_COUNT, hue_phase_ratio_, light_point_ratio_, false);
  renderStrip(right_leds_, BG_LIGHT_RIGHT_LED_COUNT, hue_phase_ratio_, light_point_ratio_, false);

  FastLED.show();
}
}  // namespace bg_light
