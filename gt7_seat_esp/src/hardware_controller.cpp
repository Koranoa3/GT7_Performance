#include "hardware_controller.h"

#include <Arduino.h>
#include <math.h>

#include "gt7_config.h"

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

void HardwareController::updateActuators(const TelemetryState &telemetry, bool telemetry_fresh)
{
  if (!telemetry_fresh)
  {
    ledcWrite(config::kFanPwmChannel, config::kFanIdleDuty);
    digitalWrite(GT7_VIBRATION_PIN, LOW);
    return;
  }

  if (telemetry.play_state == PlayRace)
  {
    const float speed_ratio = constrain(telemetry.car_speed / config::kSpeedFullScaleMps, 0.0f, 1.0f);
    const uint8_t pwm_duty = static_cast<uint8_t>(speed_ratio * config::kFanPwmMaxDuty + 0.5f);
    ledcWrite(config::kFanPwmChannel, pwm_duty);
    digitalWrite(GT7_VIBRATION_PIN, fabsf(telemetry.velocity_right) > 15.0f ? HIGH : LOW);
    return;
  }

  ledcWrite(config::kFanPwmChannel, config::kFanIdleDuty);
  digitalWrite(GT7_VIBRATION_PIN, LOW);
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
