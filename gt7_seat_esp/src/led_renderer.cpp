#include "led_renderer.h"

#include <Arduino.h>
#include <math.h>

#include "gt7_config.h"
#include "gt7_utils.h"

namespace gt7
{
uint16_t LedRenderer::segmentLength(const Segment &segment)
{
  return segment.end >= segment.start ? (segment.end - segment.start + 1) : (segment.start - segment.end + 1);
}

uint16_t LedRenderer::segmentIndex(const Segment &segment, uint16_t offset)
{
  return segment.end >= segment.start ? static_cast<uint16_t>(segment.start + offset) : static_cast<uint16_t>(segment.start - offset);
}

uint16_t LedRenderer::clampIndex(uint16_t index, uint16_t led_count)
{
  if (led_count == 0)
  {
    return 0;
  }
  return index < led_count ? index : static_cast<uint16_t>(led_count - 1);
}

void LedRenderer::fillSegment(const Segment &segment, const CRGB &color)
{
  const uint16_t length = segmentLength(segment);
  for (uint16_t i = 0; i < length; ++i)
  {
    segment.leds[segmentIndex(segment, i)] = color;
  }
}

void LedRenderer::fillInclusiveRange(CRGB leds[], uint16_t led_count, uint16_t start_index, uint16_t end_index, const CRGB &color)
{
  if (led_count == 0)
  {
    return;
  }

  const uint16_t start = clampIndex(start_index, led_count);
  const uint16_t end = clampIndex(end_index, led_count);
  const uint16_t lower = start < end ? start : end;
  const uint16_t upper = start < end ? end : start;
  for (uint16_t index = lower; index <= upper; ++index)
  {
    leds[index] = color;
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
  FastLED.addLeds<GT7_LED_TYPE, GT7_ARM_LEFT_LED_PIN, GT7_COLOR_ORDER>(arm_left_leds_, GT7_ARM_LEFT_LED_COUNT);
  FastLED.addLeds<GT7_LED_TYPE, GT7_ARM_RIGHT_LED_PIN, GT7_COLOR_ORDER>(arm_right_leds_, GT7_ARM_RIGHT_LED_COUNT);
  FastLED.setBrightness(BRIGHTNESS);
  FastLED.clear(true);
}

void LedRenderer::previewSection(uint8_t strip_id, uint16_t start_index, uint16_t end_index, uint32_t duration_ms)
{
  preview_.active = true;
  preview_.strip_id = strip_id == LedStripMonitor ? LedStripMonitor : LedStripBase;
  preview_.start_index = start_index;
  preview_.end_index = end_index;
  preview_.expires_at_ms = millis() + duration_ms;
}

CRGB LedRenderer::gaugeColorForGear(int8_t current_gear)
{
  switch (current_gear)
  {
    case 0:
      return CRGB(255, 50, 50);
    case 1:
      return CRGB(220, 220, 50);
    case 2:
      return CRGB(145, 240, 54);
    case 3:
      return CRGB(50, 190, 255);
    case 4:
      return CRGB(180, 255, 255);
    default:
      return CRGB::White;
  }
}

float LedRenderer::gearGlowPointForGear(int8_t current_gear)
{
  if (current_gear <= 1)
  {
    return 0.0f;
  }
  if (current_gear > 1 && current_gear < 5)
  {
    return static_cast<float>(current_gear-1) / 5.0f + 0.1f;
  }
  return 0.5f;
}

float LedRenderer::gearGlowBaseOffsetForGear(int8_t current_gear)
{
  if (current_gear > 0 && current_gear < 5)
  {
    return 0.0f;
  }
  if (current_gear == 0)
  {
    return 40.0f;
  }
  if (current_gear == 5)
  {
    return 40.0f;
  }
  if (current_gear >= 6)
  {
    return 80.0f;
  }
  return 0.0f;
}

void LedRenderer::animatedGaugeFill(const Segment &segment, float value, const CRGB &base_color)
{
  fillSegment(segment, CRGB::Black);

  const uint16_t length = segmentLength(segment);
  if (length == 0)
  {
    return;
  }

  const float clamped_value = constrain(value, 0.0f, 1.0f);
  uint16_t active_length = static_cast<uint16_t>(clamped_value * length + 0.5f);
  if (clamped_value > 0.0f && active_length == 0)
  {
    active_length = 1;
  }
  if (active_length > length)
  {
    active_length = length;
  }
  if (active_length == 0)
  {
    return;
  }

  const float phase = fmodf(static_cast<float>(millis()) / static_cast<float>(config::kGaugeAnimationPeriodMs), 1.0f);
  const float brightness_span = static_cast<float>(config::kGaugeAnimationMaxBrightness - config::kGaugeAnimationMinBrightness);

  for (uint16_t i = 0; i < active_length; ++i)
  {
    float x = (static_cast<float>(i) / static_cast<float>(active_length)) - phase;
    x = x - floorf(x);
    const float wave = 1.0f - fabsf((x * 2.0f) - 1.0f);
    const uint8_t brightness = static_cast<uint8_t>(
        config::kGaugeAnimationMinBrightness + (wave * wave) * brightness_span);

    CRGB color = base_color;
    color.nscale8_video(brightness);
    segment.leds[segmentIndex(segment, i)] = color;
  }
}

void LedRenderer::gaugeAnimation(CRGB leds[], uint16_t start, uint16_t end, float value, const CRGB &color) const
{
  const Segment segment{leds, start, end};
  animatedGaugeFill(segment, value, color);
}

void LedRenderer::gearGlowAnimation(const Segment &segment, int8_t current_gear) const
{
  fillSegment(segment, CRGB::Black);

  const uint16_t length = segmentLength(segment);
  if (length == 0 || current_gear < 0)
  {
    return;
  }

  const float glow_point = gearGlowPointForGear(current_gear);
  const float offset = gearGlowBaseOffsetForGear(current_gear) + gear_offset_flash_;
  const float center_index = glow_point * static_cast<float>(length - 1);
  const float peak_brightness = constrain(127.0f + offset, 0.0f, 255.0f);
  const float spread = 2.0f + offset * 0.07f;
  const float reach = spread * 2.4f;
  const CRGB base_color = gaugeColorForGear(current_gear);

  for (uint16_t i = 0; i < length; ++i)
  {
    const float distance = fabsf(static_cast<float>(i) - center_index);
    const float normalized = distance / reach;
    if (normalized >= 1.0f)
    {
      continue;
    }

    const float falloff = (1.0f - normalized * normalized);
    const uint8_t brightness = static_cast<uint8_t>(constrain(peak_brightness * falloff * falloff, 0.0f, 255.0f));

    CRGB color = base_color;
    color.nscale8_video(brightness);
    segment.leds[segmentIndex(segment, i)] = color;
  }
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
    float x = (static_cast<float>(i) / static_cast<float>(length)) - phase;
    x = x - floorf(x);
    const float wave = 1.0f - fabsf((x * 2.0f) - 1.0f);
    const uint8_t brightness = static_cast<uint8_t>((wave * wave) * base_brightness);
    const CRGB base_color = gaugeColorForGear(telemetry.current_gear);
    CRGB color = base_color;
    color.nscale8_video(brightness);
    segment.leds[segmentIndex(segment, i)] = color;
  }
}

void LedRenderer::rpmAnimation(const TelemetryState &telemetry, CRGB leds[], uint16_t start, uint16_t end) const
{
  const Segment segment{leds, start, end};
  const float alert_min = telemetry.rpm_alert_min > 1.0f ? telemetry.rpm_alert_min : 7000.0f;
  // const float alert_max = telemetry.rpm_alert_max > alert_min ? telemetry.rpm_alert_max : alert_min + 1000.0f;

  if (telemetry.engine_rpm <= alert_min / 2.0f)
  {
    fillSegment(segment, CRGB::Black);
    return;
  }
  if (alert_min / 2.0f <= telemetry.engine_rpm and telemetry.engine_rpm <= alert_min)
  {
    animatedGaugeFill(segment, (telemetry.engine_rpm - alert_min / 2.0f) / (alert_min / 2.0f), CRGB::Cyan);
    return;
  }

  fillSegment(segment, (millis()%150 < 75 ? CRGB::Magenta : CRGB::Cyan));
  // const float ratio = (telemetry.engine_rpm - alert_min) / (alert_max - alert_min);
  // fillRatioRange(segment, 0.0f, ratio, CRGB::White);
}

void LedRenderer::whiteRippleAnimation(CRGB leds[], uint16_t start, uint16_t end, float value) const
{
  const Segment segment{leds, start, end};
  const float raw = (static_cast<float>(millis() % 2000)) / 2000.0f;
  const float next = constrain(raw, 0.0f, 1.0f);
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
  const uint8_t brightness = static_cast<uint8_t>((300 - (elapsed_ms % 300)) * 0.8f);
  fillSegment(segment, CRGB(brightness, 0, 0));
}

void LedRenderer::whiteFlashAnimation(CRGB leds[], uint16_t start, uint16_t end, uint32_t elapsed_ms) const
{
  const Segment segment{leds, start, end};
  fillSegment(segment, (elapsed_ms % 150) < 75 ? CRGB::White : CRGB::Black);
}

void LedRenderer::renderSleep()
{
  fill_solid(base_leds_, GT7_BASE_LED_COUNT, CRGB::Black);
  fill_solid(monitor_leds_, GT7_MONITOR_LED_COUNT, CRGB::Black);
  fill_solid(arm_left_leds_, GT7_ARM_LEFT_LED_COUNT, CRGB::Black);
  fill_solid(arm_right_leds_, GT7_ARM_RIGHT_LED_COUNT, CRGB::Black);
  idle_ripple_prev_ = 0.0f;
}

void LedRenderer::renderIdle()
{
  fadeToBlackBy(base_leds_, GT7_BASE_LED_COUNT, 80);
  fadeToBlackBy(monitor_leds_, GT7_MONITOR_LED_COUNT, 80);
  fadeToBlackBy(arm_left_leds_, GT7_ARM_LEFT_LED_COUNT, 80);
  fadeToBlackBy(arm_right_leds_, GT7_ARM_RIGHT_LED_COUNT, 80);

  whiteRippleAnimation(base_ripple_left_.leds, base_ripple_left_.start, base_ripple_left_.end, idle_ripple_prev_);
  whiteRippleAnimation(base_ripple_right_.leds, base_ripple_right_.end, base_ripple_right_.start, idle_ripple_prev_);
  whiteRippleAnimation(monitor_ripple_left_.leds, monitor_ripple_left_.end, monitor_ripple_left_.start, idle_ripple_prev_);
  whiteRippleAnimation(monitor_ripple_right_.leds, monitor_ripple_right_.start, monitor_ripple_right_.end, idle_ripple_prev_);
  whiteRippleAnimation(arm_left_.leds, arm_left_.start, arm_left_.end, idle_ripple_prev_);
  whiteRippleAnimation(arm_right_.leds, arm_right_.start, arm_right_.end, idle_ripple_prev_);

  const float raw = (static_cast<float>(millis() % 2000)) / 2000.0f;
  idle_ripple_prev_ = constrain(raw, 0.0f, 1.0f);
}

bool LedRenderer::renderPreview(uint32_t now)
{
  if (!preview_.active)
  {
    return false;
  }
  if (static_cast<int32_t>(now - preview_.expires_at_ms) >= 0)
  {
    preview_.active = false;
    return false;
  }

  fill_solid(base_leds_, GT7_BASE_LED_COUNT, CRGB::Black);
  fill_solid(monitor_leds_, GT7_MONITOR_LED_COUNT, CRGB::Black);
  fill_solid(arm_left_leds_, GT7_ARM_LEFT_LED_COUNT, CRGB::Black);
  fill_solid(arm_right_leds_, GT7_ARM_RIGHT_LED_COUNT, CRGB::Black);

  CRGB *target_leds = preview_.strip_id == LedStripMonitor ? monitor_leds_ : base_leds_;
  const uint16_t target_count = preview_.strip_id == LedStripMonitor ? GT7_MONITOR_LED_COUNT : GT7_BASE_LED_COUNT;
  if (target_count == 0)
  {
    return true;
  }

  const uint16_t start = clampIndex(preview_.start_index, target_count);
  const uint16_t end = clampIndex(preview_.end_index, target_count);
  fillInclusiveRange(target_leds, target_count, start, end, CRGB(0, 30, 0));
  if (start == end)
  {
    target_leds[start] = CRGB(30, 0, 30);
    return true;
  }

  target_leds[start] = CRGB(0, 0, 30);
  target_leds[end] = CRGB(30, 0, 0);
  return true;
}

void LedRenderer::renderRace(const TelemetryState &telemetry,
                             bool collision_active,
                             uint32_t collision_elapsed_ms,
                             bool lap_flash_active,
                             uint32_t lap_flash_elapsed_ms)
{
  fill_solid(base_leds_, GT7_BASE_LED_COUNT, CRGB::Black);
  fill_solid(monitor_leds_, GT7_MONITOR_LED_COUNT, CRGB::Black);
  fill_solid(arm_left_leds_, GT7_ARM_LEFT_LED_COUNT, CRGB::Black);
  fill_solid(arm_right_leds_, GT7_ARM_RIGHT_LED_COUNT, CRGB::Black);

  speedAnimation(telemetry, base_leds_, base_left_.start, base_left_.end, speed_mileage_);
  speedAnimation(telemetry, base_leds_, base_right_.start, base_right_.end, speed_mileage_);
  speedAnimation(telemetry, monitor_leds_, monitor_bottom_.start+segmentLength(monitor_bottom_)/2-1, monitor_bottom_.start, speed_mileage_);
  speedAnimation(telemetry, monitor_leds_, monitor_bottom_.end-segmentLength(monitor_bottom_)/2-1, monitor_bottom_.end, speed_mileage_);
  speedAnimation(telemetry, base_leds_, rail_right_.start, rail_right_.end, speed_mileage_);
  speedAnimation(telemetry, base_leds_, rail_left_.start, rail_left_.end, speed_mileage_);
  rpmAnimation(telemetry, monitor_leds_, monitor_left_.start, monitor_left_.end);
  rpmAnimation(telemetry, monitor_leds_, monitor_right_.start, monitor_right_.end);
  gearGlowAnimation(arm_bottom_, telemetry.current_gear);
  gaugeAnimation(arm_right_leds_, arm_right_.start, arm_right_.end, telemetry.throttle / 255.0f, CRGB::Aquamarine);
  gaugeAnimation(arm_left_leds_, arm_left_.start, arm_left_.end, telemetry.brake / 255.0f, CRGB::OrangeRed);

  if (lap_flash_active)
  {
    whiteFlashAnimation(monitor_leds_, 0, GT7_MONITOR_LED_COUNT, lap_flash_elapsed_ms);
  }
  if (collision_active)
  {
    collisionBlinkAnimation(base_leds_, base_ripple_right_.start, base_ripple_left_.end, collision_elapsed_ms);
    collisionBlinkAnimation(monitor_leds_, monitor_bottom_.start, monitor_bottom_.end, collision_elapsed_ms);
  }
}

void LedRenderer::update(AnimationStatus animation_status,
                         const TelemetryState &telemetry,
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

  if (renderPreview(now))
  {
    last_animation_ms_ = now;
    FastLED.show();
    last_led_render_ms_ = now;
    return;
  }

  const float delta_seconds = last_animation_ms_ == 0 ? 0.0f : (now - last_animation_ms_) / 1000.0f;
  last_animation_ms_ = now;
  speed_mileage_ += telemetry.car_speed * delta_seconds * config::kMileageScale;
  if (speed_mileage_ > 100000.0f)
  {
    speed_mileage_ = fmodf(speed_mileage_, 360.0f);
  }

  if (animation_status == AnimationStatus::Race)
  {
    if (last_gear_ >= 0 && telemetry.current_gear >= 0 && telemetry.current_gear != last_gear_)
    {
      gear_offset_flash_ = config::kGearGlowFlashBoost;
    }
    last_gear_ = telemetry.current_gear;
    gear_offset_flash_ -= delta_seconds * gear_offset_flash_ * config::kGearGlowFlashDecayForce;
    if (gear_offset_flash_ < 0.0f)
    {
      gear_offset_flash_ = 0.0f;
    }
  }
  else
  {
    last_gear_ = telemetry.current_gear;
    gear_offset_flash_ = 0.0f;
  }

  if (animation_status == AnimationStatus::Race)
  {
    renderRace(telemetry, collision_active, collision_elapsed_ms, lap_flash_active, lap_flash_elapsed_ms);
  }
  else if (animation_status == AnimationStatus::Idle)
  {
    renderIdle();
  }
  else
  {
    renderSleep();
  }

  FastLED.show();
  last_led_render_ms_ = now;
}
}  // namespace gt7
