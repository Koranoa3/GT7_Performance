#ifndef BG_LIGHT_CONFIG_H
#define BG_LIGHT_CONFIG_H

#include <Arduino.h>

#if __has_include("config.h")
#include "config.h"
#endif

namespace bg_light::config
{
constexpr uint32_t kLedRefreshIntervalMs = 20;
constexpr float kHueSpeedRatioPerSecond = -0.20f;
constexpr float kHueCycleLengthRatio = 0.30f;
constexpr float kLightPointSpeedRatioPerSecond = 0.15f;
constexpr float kRightStripHueOffsetRatio = 0.17f;
constexpr float kRightStripLightPointOffsetRatio = 0.31f;
}  // namespace bg_light::config

#ifndef BRIGHTNESS
#define BRIGHTNESS 80
#endif

#ifndef BG_LIGHT_LEFT_LED_PIN
#define BG_LIGHT_LEFT_LED_PIN 26
#endif

#ifndef BG_LIGHT_RIGHT_LED_PIN
#define BG_LIGHT_RIGHT_LED_PIN 27
#endif

#ifndef BG_LIGHT_LEFT_LED_COUNT
#define BG_LIGHT_LEFT_LED_COUNT 60
#endif

#ifndef BG_LIGHT_RIGHT_LED_COUNT
#define BG_LIGHT_RIGHT_LED_COUNT 60
#endif

#ifndef BG_LIGHT_WAVE_DISTANCE_OFFSET
#define BG_LIGHT_WAVE_DISTANCE_OFFSET 40.0f
#endif

#ifndef BG_LIGHT_WAVE_DISTANCE_FACTOR
#define BG_LIGHT_WAVE_DISTANCE_FACTOR 160.0f
#endif

#define BG_LIGHT_LED_TYPE WS2812B
#define BG_LIGHT_COLOR_ORDER GRB

#endif  // BG_LIGHT_CONFIG_H
