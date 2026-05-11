#include <Arduino.h>
#include <FastLED.h>

#if __has_include("config.h")
#include "config.h"
#endif

constexpr uint8_t kMagic0 = 'G';
constexpr uint8_t kMagic1 = '7';
constexpr uint8_t kProtocolVersion = 1;
constexpr uint32_t kBaudRate = 115200;
constexpr uint32_t kPingIntervalMs = 1000;
constexpr uint32_t kLinkTimeoutMs = 2500;
constexpr uint32_t kTelemetryTimeoutMs = 2500;
constexpr size_t kMaxPayloadSize = 96;
constexpr size_t kMaxFrameSize = 128;
constexpr size_t kTelemetryPayloadSize = 23;
constexpr uint32_t kLedRefreshIntervalMs = 20;
constexpr float kSpeedFullScaleMps = 50.0f;
constexpr float kMileageScale = 16.0f;
constexpr uint32_t kCollisionDurationMs = 900;
constexpr uint32_t kLapFlashDurationMs = 600;

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

#ifndef GT7_BASE_LED_COUNT
#define GT7_BASE_LED_COUNT 60
#endif

#ifndef GT7_MONITOR_LED_COUNT
#define GT7_MONITOR_LED_COUNT 60
#endif

#ifndef GT7_FAN_PWM_PIN
#define GT7_FAN_PWM_PIN 32
#endif

#ifndef GT7_VIBRATION_PIN
#define GT7_VIBRATION_PIN 33
#endif

#define LED_TYPE WS2812B
#define COLOR_ORDER GRB

constexpr uint8_t kFanPwmChannel = 0;
constexpr uint32_t kFanPwmFrequencyHz = 5000;
constexpr uint8_t kFanPwmResolutionBits = 8;
constexpr uint8_t kFanPwmMaxDuty = (1u << kFanPwmResolutionBits) - 1u;
constexpr uint8_t kFanIdleDuty = 36;

enum class FrameType : uint8_t
{
  Ping = 1,
  Pong = 2,
  Telemetry = 3,
  Bind = 4,
  Event = 5,
  Ack = 6,
};

enum EventId : uint8_t
{
  EventCollision = 1,
  EventLap = 2,
};

enum PlayState : uint8_t
{
  PlayIdle = 0,
  PlayRace = 1,
};

struct TelemetryState
{
  float car_speed = 0.0f;
  float engine_rpm = 0.0f;
  float rpm_alert_min = 0.0f;
  float rpm_alert_max = 0.0f;
  uint8_t throttle = 0;
  uint8_t brake = 0;
  float velocity_right = 0.0f;
  uint8_t play_state = PlayIdle;
};

struct Frame
{
  FrameType type = FrameType::Ping;
  uint8_t flags = 0;
  uint16_t seq = 0;
  uint16_t device_id = 0;
  uint8_t payload[kMaxPayloadSize];
  uint16_t payload_len = 0;
};

struct Segment
{
  CRGB *leds;
  uint16_t start;
  uint16_t end;
};

class FrameParser
{
public:
  void push(const uint8_t *data, size_t length)
  {
    for (size_t i = 0; i < length; ++i)
    {
      if (buffer_len_ < kMaxFrameSize)
      {
        buffer_[buffer_len_++] = data[i];
      }
      else
      {
        drop_prefix(1);
        buffer_[buffer_len_++] = data[i];
      }
    }
  }

  bool pop(Frame &out)
  {
    while (buffer_len_ >= kHeaderSize)
    {
      if (buffer_[0] != kMagic0 || buffer_[1] != kMagic1)
      {
        drop_prefix(1);
        continue;
      }

      const uint8_t version = buffer_[2];
      if (version != kProtocolVersion)
      {
        drop_prefix(kHeaderSize);
        continue;
      }

      const uint16_t payload_len = read_u16(10);
      const size_t frame_len = kHeaderSize + payload_len;
      if (payload_len > kMaxPayloadSize)
      {
        drop_prefix(2);
        continue;
      }
      if (buffer_len_ < frame_len)
      {
        return false;
      }

      out.type = static_cast<FrameType>(buffer_[3]);
      out.flags = buffer_[4];
      out.seq = read_u16(6);
      out.device_id = read_u16(8);
      out.payload_len = payload_len;
      if (payload_len > 0)
      {
        memcpy(out.payload, buffer_ + kHeaderSize, payload_len);
      }
      drop_prefix(frame_len);
      return true;
    }

    return false;
  }

private:
  static constexpr size_t kHeaderSize = 12;
  uint8_t buffer_[kMaxFrameSize];
  size_t buffer_len_ = 0;

  uint16_t read_u16(size_t offset) const
  {
    return static_cast<uint16_t>(buffer_[offset]) |
           static_cast<uint16_t>(buffer_[offset + 1]) << 8;
  }

  void drop_prefix(size_t count)
  {
    if (count >= buffer_len_)
    {
      buffer_len_ = 0;
      return;
    }
    memmove(buffer_, buffer_ + count, buffer_len_ - count);
    buffer_len_ -= count;
  }
};

TelemetryState telemetry_state;
FrameParser parser;
CRGB base_leds[GT7_BASE_LED_COUNT];
CRGB monitor_leds[GT7_MONITOR_LED_COUNT];

uint16_t next_seq = 1;
uint32_t last_ping_sent_ms = 0;
uint32_t last_pc_seen_ms = 0;
uint32_t last_telemetry_rx_ms = 0;
uint32_t last_status_toggle_ms = 0;
uint32_t last_led_render_ms = 0;
uint32_t last_animation_ms = 0;
uint32_t collision_started_ms = 0;
uint32_t lap_flash_started_ms = 0;
bool status_led_on = false;
bool has_binding = false;
char bound_ps5_ip[16] = {0};
float speed_mileage = 0.0f;
float idle_ripple_prev = 0.0f;

Segment base_left = {base_leds, 0, GT7_BASE_LED_COUNT / 4};
Segment base_right = {base_leds, GT7_BASE_LED_COUNT / 4, GT7_BASE_LED_COUNT / 2};
Segment rail_left = {base_leds, GT7_BASE_LED_COUNT / 2, (GT7_BASE_LED_COUNT * 3) / 4};
Segment rail_right = {base_leds, (GT7_BASE_LED_COUNT * 3) / 4, GT7_BASE_LED_COUNT};
Segment monitor_left = {monitor_leds, 0, GT7_MONITOR_LED_COUNT / 3};
Segment monitor_right = {monitor_leds, GT7_MONITOR_LED_COUNT / 3, (GT7_MONITOR_LED_COUNT * 2) / 3};
Segment monitor_bottom = {monitor_leds, (GT7_MONITOR_LED_COUNT * 2) / 3, GT7_MONITOR_LED_COUNT};

void write_u16(uint8_t *target, uint16_t value)
{
  target[0] = static_cast<uint8_t>(value & 0xFF);
  target[1] = static_cast<uint8_t>((value >> 8) & 0xFF);
}

void send_frame(FrameType type, uint16_t device_id, const uint8_t *payload, uint16_t payload_len, uint8_t flags = 0)
{
  uint8_t header[12];
  header[0] = kMagic0;
  header[1] = kMagic1;
  header[2] = kProtocolVersion;
  header[3] = static_cast<uint8_t>(type);
  header[4] = flags;
  header[5] = 0;
  write_u16(header + 6, next_seq++);
  write_u16(header + 8, device_id);
  write_u16(header + 10, payload_len);

  Serial.write(header, sizeof(header));
  if (payload_len > 0)
  {
    Serial.write(payload, payload_len);
  }
}

void send_ping()
{
  send_frame(FrameType::Ping, GT7_DEVICE_ID, nullptr, 0);
}

void send_pong(uint16_t device_id)
{
  send_frame(FrameType::Pong, device_id, nullptr, 0);
}

void send_bind_ack(uint16_t device_id, const char *ps5_ip)
{
  uint8_t payload[4];
  IPAddress ip;
  if (ip.fromString(ps5_ip))
  {
    payload[0] = ip[0];
    payload[1] = ip[1];
    payload[2] = ip[2];
    payload[3] = ip[3];
    send_frame(FrameType::Ack, device_id, payload, sizeof(payload));
    return;
  }
  send_frame(FrameType::Ack, device_id, nullptr, 0);
}

uint16_t segment_length(const Segment &segment)
{
  return segment.end > segment.start ? segment.end - segment.start : segment.start - segment.end;
}

uint16_t segment_index(const Segment &segment, uint16_t offset)
{
  return segment.end >= segment.start ? segment.start + offset : segment.start - 1 - offset;
}

void fill_segment(const Segment &segment, const CRGB &color)
{
  const uint16_t length = segment_length(segment);
  for (uint16_t i = 0; i < length; ++i)
  {
    segment.leds[segment_index(segment, i)] = color;
  }
}

void fade_segment(const Segment &segment, uint8_t amount)
{
  const uint16_t length = segment_length(segment);
  for (uint16_t i = 0; i < length; ++i)
  {
    segment.leds[segment_index(segment, i)].fadeToBlackBy(amount);
  }
}

void fill_ratio_range(const Segment &segment, float from_ratio, float to_ratio, const CRGB &color)
{
  const uint16_t length = segment_length(segment);
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
    segment.leds[segment_index(segment, i)] = color;
  }
}

void gauge_animation(const TelemetryState &, CRGB leds[], uint16_t start, uint16_t end, float value)
{
  Segment segment = {leds, start, end};
  fill_segment(segment, CRGB::Black);
  fill_ratio_range(segment, 0.0f, constrain(value, 0.0f, 1.0f), CRGB::White);
}

void speed_animation(const TelemetryState &telemetry, CRGB leds[], uint16_t start, uint16_t end, float value)
{
  Segment segment = {leds, start, end};
  const uint16_t length = segment_length(segment);
  if (length == 0)
  {
    return;
  }

  const float speed_ratio = constrain(telemetry.car_speed / kSpeedFullScaleMps, 0.0f, 1.0f);
  const uint8_t base_brightness = static_cast<uint8_t>(30 + speed_ratio * 120.0f);
  const float phase = fmodf(value / 360.0f, 1.0f);
  for (uint16_t i = 0; i < length; ++i)
  {
    float x = (static_cast<float>(i) / static_cast<float>(length)) + phase;
    x = x - floorf(x);
    const float wave = 1.0f - fabsf((x * 2.0f) - 1.0f);
    const uint8_t brightness = static_cast<uint8_t>((wave * wave) * base_brightness);
    segment.leds[segment_index(segment, i)] = CRGB(0, brightness / 2, brightness);
  }
}

void rpm_animation(const TelemetryState &telemetry, CRGB leds[], uint16_t start, uint16_t end, float)
{
  Segment segment = {leds, start, end};
  const float alert_min = telemetry.rpm_alert_min > 1.0f ? telemetry.rpm_alert_min : 7000.0f;
  const float alert_max = telemetry.rpm_alert_max > alert_min ? telemetry.rpm_alert_max : alert_min + 1000.0f;

  if (telemetry.engine_rpm <= alert_min)
  {
    fill_segment(segment, CRGB::Black);
    fill_ratio_range(segment, 0.0f, telemetry.engine_rpm / alert_min, CRGB::Cyan);
    return;
  }

  fill_segment(segment, CRGB(32, 32, 32));
  const float ratio = (telemetry.engine_rpm - alert_min) / (alert_max - alert_min);
  fill_ratio_range(segment, 0.0f, ratio, CRGB::Red);
}

void white_ripple_animation(const TelemetryState &, CRGB leds[], uint16_t start, uint16_t end, float value)
{
  Segment segment = {leds, start, end};
  const float raw = (static_cast<float>(millis() % 4000) - 2000.0f) / 2000.0f;
  const float next = constrain(raw * raw, 0.0f, 1.0f);
  fill_ratio_range(segment, value, next, CRGB::White);
}

void collision_blink_animation(const TelemetryState &, CRGB leds[], uint16_t start, uint16_t end, float value)
{
  Segment segment = {leds, start, end};
  const uint32_t elapsed = static_cast<uint32_t>(value);
  const uint8_t brightness = static_cast<uint8_t>((300 - (elapsed % 300)) * 0.2f);
  fill_segment(segment, CRGB(brightness, 0, 0));
}

void white_flash_animation(const TelemetryState &, CRGB leds[], uint16_t start, uint16_t end, float value)
{
  Segment segment = {leds, start, end};
  const uint32_t elapsed = static_cast<uint32_t>(value);
  fill_segment(segment, (elapsed % 150) < 75 ? CRGB::White : CRGB::Black);
}

bool telemetry_is_fresh()
{
  return (millis() - last_telemetry_rx_ms) <= kTelemetryTimeoutMs;
}

bool race_is_active()
{
  return telemetry_is_fresh() && telemetry_state.play_state == PlayRace;
}

bool collision_is_active(uint32_t now)
{
  return collision_started_ms != 0 && (now - collision_started_ms) < kCollisionDurationMs;
}

bool lap_flash_is_active(uint32_t now)
{
  return lap_flash_started_ms != 0 && (now - lap_flash_started_ms) < kLapFlashDurationMs;
}

void update_fan_and_vibration()
{
  if (!telemetry_is_fresh())
  {
    ledcWrite(kFanPwmChannel, kFanIdleDuty);
    digitalWrite(GT7_VIBRATION_PIN, LOW);
    return;
  }

  if (telemetry_state.play_state == PlayRace)
  {
    const float speed_ratio = constrain(telemetry_state.car_speed / kSpeedFullScaleMps, 0.0f, 1.0f);
    const uint8_t pwm_duty = static_cast<uint8_t>(speed_ratio * kFanPwmMaxDuty + 0.5f);
    ledcWrite(kFanPwmChannel, pwm_duty);
    digitalWrite(GT7_VIBRATION_PIN, fabsf(telemetry_state.velocity_right) > 15.0f ? HIGH : LOW);
    return;
  }

  ledcWrite(kFanPwmChannel, kFanIdleDuty);
  digitalWrite(GT7_VIBRATION_PIN, LOW);
}

void render_idle()
{
  fadeToBlackBy(base_leds, GT7_BASE_LED_COUNT, 80);
  fadeToBlackBy(monitor_leds, GT7_MONITOR_LED_COUNT, 80);

  white_ripple_animation(telemetry_state, base_leds, base_left.start, base_left.end, idle_ripple_prev);
  white_ripple_animation(telemetry_state, base_leds, base_right.end, base_right.start, idle_ripple_prev);
  white_ripple_animation(telemetry_state, base_leds, rail_left.start, rail_left.end, idle_ripple_prev);
  white_ripple_animation(telemetry_state, base_leds, rail_right.end, rail_right.start, idle_ripple_prev);
  white_ripple_animation(telemetry_state, monitor_leds, monitor_bottom.start, monitor_bottom.end, idle_ripple_prev);
  white_ripple_animation(telemetry_state, monitor_leds, monitor_left.end, monitor_left.start, idle_ripple_prev);
  white_ripple_animation(telemetry_state, monitor_leds, monitor_right.start, monitor_right.end, idle_ripple_prev);

  const float raw = (static_cast<float>(millis() % 4000) - 2000.0f) / 2000.0f;
  idle_ripple_prev = constrain(raw * raw, 0.0f, 1.0f);
}

void render_race(uint32_t now)
{
  fill_solid(base_leds, GT7_BASE_LED_COUNT, CRGB::Black);
  fill_solid(monitor_leds, GT7_MONITOR_LED_COUNT, CRGB::Black);

  speed_animation(telemetry_state, base_leds, base_left.start, base_right.end, speed_mileage);
  speed_animation(telemetry_state, monitor_leds, monitor_bottom.start, monitor_bottom.end, speed_mileage);
  rpm_animation(telemetry_state, monitor_leds, monitor_left.start, monitor_left.end, 0.0f);
  rpm_animation(telemetry_state, monitor_leds, monitor_right.start, monitor_right.end, 0.0f);
  gauge_animation(telemetry_state, base_leds, rail_right.start, rail_right.end, telemetry_state.throttle / 255.0f);
  gauge_animation(telemetry_state, base_leds, rail_left.start, rail_left.end, telemetry_state.brake / 255.0f);

  if (lap_flash_is_active(now))
  {
    white_flash_animation(telemetry_state, monitor_leds, 0, GT7_MONITOR_LED_COUNT, static_cast<float>(now - lap_flash_started_ms));
  }
  if (collision_is_active(now))
  {
    collision_blink_animation(telemetry_state, base_leds, 0, GT7_BASE_LED_COUNT, static_cast<float>(now - collision_started_ms));
    collision_blink_animation(telemetry_state, monitor_leds, monitor_bottom.start, monitor_bottom.end, static_cast<float>(now - collision_started_ms));
  }
}

void update_leds()
{
  const uint32_t now = millis();
  if ((now - last_led_render_ms) < kLedRefreshIntervalMs)
  {
    return;
  }

  const float delta_seconds = last_animation_ms == 0 ? 0.0f : (now - last_animation_ms) / 1000.0f;
  last_animation_ms = now;
  speed_mileage += telemetry_state.car_speed * delta_seconds * kMileageScale;
  if (speed_mileage > 100000.0f)
  {
    speed_mileage = fmodf(speed_mileage, 360.0f);
  }

  if (race_is_active())
  {
    render_race(now);
  }
  else
  {
    render_idle();
  }

  FastLED.show();
  last_led_render_ms = now;
}

void handle_ping(const Frame &frame)
{
  last_pc_seen_ms = millis();
  send_pong(frame.device_id);
}

void handle_pong(const Frame &frame)
{
  (void)frame;
  last_pc_seen_ms = millis();
}

void handle_bind(const Frame &frame)
{
  last_pc_seen_ms = millis();
  if (frame.payload_len >= 4)
  {
    IPAddress ip(frame.payload[0], frame.payload[1], frame.payload[2], frame.payload[3]);
    String ip_text = ip.toString();
    ip_text.toCharArray(bound_ps5_ip, sizeof(bound_ps5_ip));
    has_binding = true;
    send_bind_ack(frame.device_id, bound_ps5_ip);
  }
  else
  {
    has_binding = false;
    bound_ps5_ip[0] = '\0';
    send_bind_ack(frame.device_id, "");
  }
}

void handle_event(const Frame &frame)
{
  last_pc_seen_ms = millis();
  if (frame.payload_len < 2)
  {
    return;
  }

  const uint8_t event_id = frame.payload[0];
  const uint32_t now = millis();
  if (event_id == EventCollision)
  {
    collision_started_ms = now;
  }
  else if (event_id == EventLap)
  {
    lap_flash_started_ms = now;
  }
}

void handle_telemetry(const Frame &frame)
{
  last_pc_seen_ms = millis();
  last_telemetry_rx_ms = millis();
  if (frame.payload_len < kTelemetryPayloadSize)
  {
    return;
  }

  const uint8_t *p = frame.payload;
  auto read_f32 = [&](size_t offset) -> float
  {
    float value;
    memcpy(&value, p + offset, sizeof(float));
    return value;
  };

  telemetry_state.car_speed = read_f32(0);
  telemetry_state.engine_rpm = read_f32(4);
  telemetry_state.rpm_alert_min = read_f32(8);
  telemetry_state.rpm_alert_max = read_f32(12);
  telemetry_state.throttle = p[16];
  telemetry_state.brake = p[17];
  telemetry_state.velocity_right = read_f32(18);
  telemetry_state.play_state = p[22] == PlayRace ? PlayRace : PlayIdle;
  update_fan_and_vibration();

  (void)frame;
}

void handle_frame(const Frame &frame)
{
  switch (frame.type)
  {
  case FrameType::Ping:
    handle_ping(frame);
    break;
  case FrameType::Pong:
    handle_pong(frame);
    break;
  case FrameType::Bind:
    handle_bind(frame);
    break;
  case FrameType::Telemetry:
    handle_telemetry(frame);
    break;
  case FrameType::Event:
    handle_event(frame);
    break;
  default:
    break;
  }
}

bool link_is_healthy()
{
  const uint32_t now = millis();
  return (now - last_pc_seen_ms) <= kLinkTimeoutMs ||
         (now - last_telemetry_rx_ms) <= kTelemetryTimeoutMs;
}

void update_status_led()
{
  const uint32_t now = millis();
  const bool healthy = link_is_healthy();

  if (healthy)
  {
    digitalWrite(GT7_STATUS_LED_PIN, LOW);
    status_led_on = false;
    last_status_toggle_ms = now;
    return;
  }

  if ((now - last_status_toggle_ms) >= 250)
  {
    status_led_on = !status_led_on;
    digitalWrite(GT7_STATUS_LED_PIN, status_led_on ? HIGH : LOW);
    last_status_toggle_ms = now;
  }
}

void poll_serial()
{
  while (Serial.available() > 0)
  {
    uint8_t byte = static_cast<uint8_t>(Serial.read());
    parser.push(&byte, 1);
  }

  Frame frame;
  while (parser.pop(frame))
  {
    handle_frame(frame);
  }
}

void send_periodic_ping()
{
  const uint32_t now = millis();
  if (now - last_ping_sent_ms >= kPingIntervalMs)
  {
    send_ping();
    last_ping_sent_ms = now;
  }
}

void setup()
{
  pinMode(GT7_STATUS_LED_PIN, OUTPUT);
  digitalWrite(GT7_STATUS_LED_PIN, LOW);
  pinMode(GT7_FAN_PWM_PIN, OUTPUT);
  pinMode(GT7_VIBRATION_PIN, OUTPUT);
  digitalWrite(GT7_VIBRATION_PIN, LOW);
  ledcSetup(kFanPwmChannel, kFanPwmFrequencyHz, kFanPwmResolutionBits);
  ledcAttachPin(GT7_FAN_PWM_PIN, kFanPwmChannel);
  ledcWrite(kFanPwmChannel, kFanIdleDuty);
  Serial.begin(kBaudRate);
  Serial.setTimeout(0);
  FastLED.addLeds<LED_TYPE, GT7_BASE_LED_PIN, COLOR_ORDER>(base_leds, GT7_BASE_LED_COUNT);
  FastLED.addLeds<LED_TYPE, GT7_MONITOR_LED_PIN, COLOR_ORDER>(monitor_leds, GT7_MONITOR_LED_COUNT);
  FastLED.setBrightness(BRIGHTNESS);
  FastLED.clear(true);
  delay(300);
  send_ping();
  last_ping_sent_ms = millis();
}

void loop()
{
  poll_serial();
  send_periodic_ping();
  update_leds();
  update_fan_and_vibration();
  update_status_led();
  delay(5);
}
