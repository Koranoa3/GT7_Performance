#include "hardware_controller.h"

#include <Arduino.h>
#include <math.h>

#include "gt7_config.h"
#include "gt7_utils.h"

namespace gt7
{
void HardwareController::setup()
{
  pinMode(GT7_STATUS_LED_PIN, OUTPUT);
  digitalWrite(GT7_STATUS_LED_PIN, LOW);

  pinMode(GT7_FAN_PWM_PIN, OUTPUT);
  pinMode(GT7_VIBRATION_PIN, OUTPUT);
  digitalWrite(GT7_VIBRATION_PIN, LOW);

  ledcSetup(config::kFanPwmChannel, config::kFanPwmFrequencyHz, config::kFanPwmResolutionBits);
  ledcAttachPin(GT7_FAN_PWM_PIN, config::kFanPwmChannel);
  ledcWrite(config::kFanPwmChannel, config::kFanIdleDuty);
}

uint32_t HardwareController::collisionVibrationDurationForStrength(uint8_t strength) const
{
  if (strength == 0)
  {
    return config::kCollisionVibrationMaxDurationMs;
  }

  const uint32_t span = config::kCollisionVibrationMaxDurationMs - config::kCollisionVibrationMinDurationMs;
  const uint32_t scaled = static_cast<uint32_t>((static_cast<uint32_t>(strength - 1) * span + 127u) / 254u);
  return config::kCollisionVibrationMinDurationMs + scaled;
}

void HardwareController::triggerCollisionVibration(uint32_t now, uint8_t strength)
{
  collision_vibration_started_ms_ = now;
  collision_vibration_duration_ms_ = collisionVibrationDurationForStrength(strength);
}

void HardwareController::updateActuators(const TelemetryState &telemetry, bool telemetry_fresh)
{
  const uint32_t now = millis();
  const bool collision_vibration_active = collision_vibration_started_ms_ != 0 &&
                                          (now - collision_vibration_started_ms_) < collision_vibration_duration_ms_;

  if (!telemetry_fresh)
  {
    ledcWrite(config::kFanPwmChannel, config::kFanIdleDuty);
    digitalWrite(GT7_VIBRATION_PIN, collision_vibration_active ? HIGH : LOW);
    return;
  }

  if (telemetry.play_state == PlayRace)
  {
    const float speed_ratio = constrain((telemetry.car_speed - 20) / config::kSpeedFullScaleMps, 0.0f, 1.0f);
    const uint8_t pwm_duty = static_cast<uint8_t>((1.0f - speed_ratio) * config::kFanPwmMaxDuty + 0.5f);
    ledcWrite(config::kFanPwmChannel, pwm_duty);
    const bool lateral_vibration_active = fabsf(telemetry.velocity_right) > 15.0f;
    digitalWrite(GT7_VIBRATION_PIN, (collision_vibration_active || lateral_vibration_active) ? HIGH : LOW);
    return;
  }

  ledcWrite(config::kFanPwmChannel, config::kFanIdleDuty);
  digitalWrite(GT7_VIBRATION_PIN, collision_vibration_active ? HIGH : LOW);
}

void HardwareController::updateStatusLed(bool link_healthy)
{
  const uint32_t now = millis();
  if (link_healthy)
  {
    digitalWrite(GT7_STATUS_LED_PIN, LOW);
    status_led_on_ = false;
    last_status_toggle_ms_ = now;
    return;
  }

  if ((now - last_status_toggle_ms_) >= 250)
  {
    status_led_on_ = !status_led_on_;
    digitalWrite(GT7_STATUS_LED_PIN, status_led_on_ ? HIGH : LOW);
    last_status_toggle_ms_ = now;
  }
}
}  // namespace gt7
