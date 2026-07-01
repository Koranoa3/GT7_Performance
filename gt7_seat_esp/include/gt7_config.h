#ifndef GT7_CONFIG_H
#define GT7_CONFIG_H

#include <Arduino.h>

#if __has_include("config.h")
#include "config.h"
#endif

namespace gt7::config
{
constexpr uint8_t kMagic0 = 'G';
constexpr uint8_t kMagic1 = '7';
constexpr uint8_t kProtocolVersion = 1;

constexpr uint32_t kBaudRate = 115200;
constexpr uint32_t kPingIntervalMs = 1000;
constexpr uint32_t kLinkTimeoutMs = 2500;
constexpr uint32_t kTelemetryTimeoutMs = 2500;
constexpr uint32_t kLedRefreshIntervalMs = 20;
constexpr uint32_t kCollisionDurationMs = 900;
constexpr uint32_t kCollisionVibrationMinDurationMs = 200;
constexpr uint32_t kCollisionVibrationMaxDurationMs = 800;
constexpr uint32_t kLapFlashDurationMs = 600;

constexpr size_t kMaxPayloadSize = 96;
constexpr size_t kMaxFrameSize = 128;
constexpr size_t kTelemetryPayloadSize = 28;
constexpr size_t kSectionPreviewPayloadSize = 5;

constexpr float kSpeedFullScaleMps = 50.0f;
constexpr float kMileageScale = 32.0f;
constexpr uint32_t kGaugeAnimationPeriodMs = 600;
constexpr uint8_t kGaugeAnimationMinBrightness = 40;
constexpr uint8_t kGaugeAnimationMaxBrightness = 255;
constexpr float kGearGlowFlashBoost = 128.0f;
constexpr float kGearGlowFlashDecayForce = 12.0f;
constexpr uint32_t kSectionPreviewDurationMs = 10000;

constexpr uint8_t kFanPwmChannel = 0;
constexpr uint32_t kFanPwmFrequencyHz = 5000;
constexpr uint8_t kFanPwmResolutionBits = 8;
constexpr uint8_t kFanPwmMaxDuty = (1u << kFanPwmResolutionBits) - 1u;
constexpr uint8_t kFanIdleDuty = (1u << kFanPwmResolutionBits) - 1u;
}  // namespace gt7::config

#ifndef GT7_DEVICE_ID
#define GT7_DEVICE_ID 1
#endif

#ifndef GT7_STATUS_LED_PIN
#define GT7_STATUS_LED_PIN 2
#endif

#ifndef BRIGHTNESS
#define BRIGHTNESS 96
#endif

#ifndef GT7_BASE_LED_PIN
#define GT7_BASE_LED_PIN 26
#endif

#ifndef GT7_MONITOR_LED_PIN
#define GT7_MONITOR_LED_PIN 27
#endif

#ifndef GT7_ARM_LEFT_LED_PIN
#define GT7_ARM_LEFT_LED_PIN 12
#endif

#ifndef GT7_ARM_RIGHT_LED_PIN
#define GT7_ARM_RIGHT_LED_PIN 14
#endif

#ifndef GT7_BASE_LED_COUNT
#define GT7_BASE_LED_COUNT 300
#endif

#ifndef GT7_MONITOR_LED_COUNT
#define GT7_MONITOR_LED_COUNT 136
#endif

#ifndef GT7_ARM_LEFT_LED_COUNT
#define GT7_ARM_LEFT_LED_COUNT 23
#endif

#ifndef GT7_ARM_RIGHT_LED_COUNT
#define GT7_ARM_RIGHT_LED_COUNT 23
#endif

#ifndef GT7_FAN_PWM_PIN
#define GT7_FAN_PWM_PIN 32
#endif

#ifndef GT7_VIBRATION_PIN
#define GT7_VIBRATION_PIN 33
#endif

#define GT7_LED_TYPE WS2812B
#define GT7_COLOR_ORDER GRB

#endif  // GT7_CONFIG_H
