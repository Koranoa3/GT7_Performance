#include "led_renderer.h"

#include <Arduino.h>
#include <math.h>

#include "gt7_config.h"
#include "gt7_utils.h"

namespace gt7
{
uint16_t LedRenderer::segmentLength(const Segment &segment)
{
  return segment.end > segment.start ? segment.end - segment.start : segment.start - segment.end;
}

uint16_t LedRenderer::segmentIndex(const Segment &segment, uint16_t offset)
{
  return segment.end >= segment.start ? segment.start + offset : segment.start - 1 - offset;
}

void LedRenderer::fillSegment(const Segment &segment, const CRGB &color)
{
  const uint16_t length = segmentLength(segment);
  for (uint16_t i = 0; i < length; ++i)
  {
    segment.leds[segmentIndex(segment, i)] = color;
  }
}

void LedRenderer::fillRatioRange(const Segment &segment, float from_ratio, float to_ratio, const CRGB &color)
{
  const uint16_t length = segmentLength(segment);
  if (length == 0)
  {
    return;
  }

  float from_value = constrain(from_ratio, 0.0f, 1.0f);
  float to_value = constrain(to_ratio, 0.0f, 1.0f);
  if (to_value < from_value)
  {
    const float temp = from_value;
    from_value = to_value;
    to_value = temp;
  }

  const uint16_t start = static_cast<uint16_t>(from_value * length);
  uint16_t end = static_cast<uint16_t>(to_value * length + 0.5f);
  if (end <= start)
  {
    end = start + 1;
  }
  if (end > length)
  {
    end = length;
  }

  for (uint16_t i = start; i < end; ++i)
  {
    segment.leds[segmentIndex(segment, i)] = color;
  }
}

void LedRenderer::setup()
{
  FastLED.addLeds<GT7_LED_TYPE, GT7_BASE_LED_PIN, GT7_COLOR_ORDER>(base_leds_, GT7_BASE_LED_COUNT);
  FastLED.addLeds<GT7_LED_TYPE, GT7_MONITOR_LED_PIN, GT7_COLOR_ORDER>(monitor_leds_, GT7_MONITOR_LED_COUNT);
  FastLED.setBrightness(BRIGHTNESS);
  FastLED.clear(true);
}

void LedRenderer::gaugeAnimation(CRGB leds[], uint16_t start, uint16_t end, float value) const
{
  const Segment segment{leds, start, end};
  fillSegment(segment, CRGB::Black);
  fillRatioRange(segment, 0.0f, constrain(value, 0.0f, 1.0f), CRGB::White);
}

void LedRenderer::speedAnimation(const TelemetryState &telemetry, CRGB leds[], uint16_t start, uint16_t end, float value) const
{
  const Segment segment{leds, start, end};
  const uint16_t length = segmentLength(segment);
  if (length == 0)
  {
    return;
  }

  const float speed_ratio = constrain(telemetry.car_speed / config::kSpeedFullScaleMps, 0.0f, 1.0f);
  const uint8_t base_brightness = static_cast<uint8_t>(30 + speed_ratio * 120.0f);
  const float phase = fmodf(value / 360.0f, 1.0f);

  for (uint16_t i = 0; i < length; ++i)
  {
    float x = (static_cast<float>(i) / static_cast<float>(length)) + phase;
    x = x - floorf(x);
    const float wave = 1.0f - fabsf((x * 2.0f) - 1.0f);
    const uint8_t brightness = static_cast<uint8_t>((wave * wave) * base_brightness);
    segment.leds[segmentIndex(segment, i)] = CRGB(0, brightness / 2, brightness);
  }
}

void LedRenderer::rpmAnimation(const TelemetryState &telemetry, CRGB leds[], uint16_t start, uint16_t end) const
{
  const Segment segment{leds, start, end};
  const float alert_min = telemetry.rpm_alert_min > 1.0f ? telemetry.rpm_alert_min : 7000.0f;
  const float alert_max = telemetry.rpm_alert_max > alert_min ? telemetry.rpm_alert_max : alert_min + 1000.0f;

  if (telemetry.engine_rpm <= alert_min / 2.0f)
  {
    fillSegment(segment, CRGB::Black);
    return;
  }
  if (alert_min / 2.0f <= telemetry.engine_rpm and telemetry.engine_rpm <= alert_min)
  {
    fillSegment(segment, CRGB::Black);
    fillRatioRange(segment, 0.0f, (telemetry.engine_rpm-alert_min/2)/(alert_min/2), CRGB::Cyan);
    return;
  }

  fillSegment(segment, (millis()%150 < 75 ? CRGB::Magenta : CRGB::Cyan));
  const float ratio = (telemetry.engine_rpm - alert_min) / (alert_max - alert_min);
  fillRatioRange(segment, 0.0f, ratio, CRGB::White);
}

void LedRenderer::whiteRippleAnimation(CRGB leds[], uint16_t start, uint16_t end, float value) const
{
  const Segment segment{leds, start, end};
  const float raw = (static_cast<float>(millis() % 2000)) / 2000.0f;
  const float next = constrain(raw * raw, 0.0f, 1.0f);
  if (next < value)
  {
    fillRatioRange(segment, value, 1.0f, CRGB::White);
    fillRatioRange(segment, 0.0f, next, CRGB::Black);
    return;
  }
  fillRatioRange(segment, value, next, CRGB::White);
}

void LedRenderer::collisionBlinkAnimation(CRGB leds[], uint16_t start, uint16_t end, uint32_t elapsed_ms) const
{
  const Segment segment{leds, start, end};
  const uint8_t brightness = static_cast<uint8_t>((300 - (elapsed_ms % 300)) * 0.2f);
  fillSegment(segment, CRGB(brightness, 0, 0));
}

void LedRenderer::whiteFlashAnimation(CRGB leds[], uint16_t start, uint16_t end, uint32_t elapsed_ms) const
{
  const Segment segment{leds, start, end};
  fillSegment(segment, (elapsed_ms % 150) < 75 ? CRGB::White : CRGB::Black);
}

void LedRenderer::renderIdle()
{
  fadeToBlackBy(base_leds_, GT7_BASE_LED_COUNT, 80);
  fadeToBlackBy(monitor_leds_, GT7_MONITOR_LED_COUNT, 80);

  whiteRippleAnimation(base_ripple_left_.leds, base_ripple_left_.end, base_ripple_left_.start, idle_ripple_prev_);
  whiteRippleAnimation(base_ripple_right_.leds, base_ripple_right_.start, base_ripple_right_.end, idle_ripple_prev_);
  whiteRippleAnimation(monitor_ripple_left_.leds, monitor_ripple_left_.start, monitor_ripple_left_.end, idle_ripple_prev_);
  whiteRippleAnimation(monitor_ripple_right_.leds, monitor_ripple_right_.end, monitor_ripple_right_.start, idle_ripple_prev_);

  const float raw = (static_cast<float>(millis() % 2000)) / 2000.0f;
  idle_ripple_prev_ = constrain(raw * raw, 0.0f, 1.0f);
}

void LedRenderer::renderRace(const TelemetryState &telemetry,
                             bool collision_active,
                             uint32_t collision_elapsed_ms,
                             bool lap_flash_active,
                             uint32_t lap_flash_elapsed_ms)
{
  fill_solid(base_leds_, GT7_BASE_LED_COUNT, CRGB::Black);
  fill_solid(monitor_leds_, GT7_MONITOR_LED_COUNT, CRGB::Black);

  speedAnimation(telemetry, base_leds_, base_left_.start, base_right_.end, speed_mileage_);
  speedAnimation(telemetry, monitor_leds_, monitor_bottom_.start, monitor_bottom_.end, speed_mileage_);
  rpmAnimation(telemetry, monitor_leds_, monitor_left_.start, monitor_left_.end);
  rpmAnimation(telemetry, monitor_leds_, monitor_right_.start, monitor_right_.end);
  gaugeAnimation(base_leds_, rail_right_.start, rail_right_.end, telemetry.throttle / 255.0f);
  gaugeAnimation(base_leds_, rail_left_.start, rail_left_.end, telemetry.brake / 255.0f);

  if (lap_flash_active)
  {
    whiteFlashAnimation(monitor_leds_, 0, GT7_MONITOR_LED_COUNT, lap_flash_elapsed_ms);
  }
  if (collision_active)
  {
    collisionBlinkAnimation(base_leds_, 0, GT7_BASE_LED_COUNT, collision_elapsed_ms);
    collisionBlinkAnimation(monitor_leds_, monitor_bottom_.start, monitor_bottom_.end, collision_elapsed_ms);
  }
}

void LedRenderer::update(const TelemetryState &telemetry,
                         bool race_active,
                         bool collision_active,
                         uint32_t collision_elapsed_ms,
                         bool lap_flash_active,
                         uint32_t lap_flash_elapsed_ms)
{
  const uint32_t now = millis();
  if ((now - last_led_render_ms_) < config::kLedRefreshIntervalMs)
  {
    return;
  }

  const float delta_seconds = last_animation_ms_ == 0 ? 0.0f : (now - last_animation_ms_) / 1000.0f;
  last_animation_ms_ = now;
  speed_mileage_ += telemetry.car_speed * delta_seconds * config::kMileageScale;
  if (speed_mileage_ > 100000.0f)
  {
    speed_mileage_ = fmodf(speed_mileage_, 360.0f);
  }

  if (race_active)
  {
    renderRace(telemetry, collision_active, collision_elapsed_ms, lap_flash_active, lap_flash_elapsed_ms);
  }
  else
  {
    renderIdle();
  }

  FastLED.show();
  last_led_render_ms_ = now;
}
}  // namespace gt7
