#include "seat_controller.h"

#include <IPAddress.h>
#include <string.h>

#include "gt7_config.h"

namespace gt7
{
bool SeatController::telemetryIsFresh() const
{
  return (millis() - last_telemetry_rx_ms_) <= config::kTelemetryTimeoutMs;
}

bool SeatController::raceIsActive() const
{
  return telemetryIsFresh() && telemetry_state_.play_state == PlayRace;
}

bool SeatController::linkIsHealthy() const
{
  const uint32_t now = millis();
  return (now - last_pc_seen_ms_) <= config::kLinkTimeoutMs ||
         (now - last_telemetry_rx_ms_) <= config::kTelemetryTimeoutMs;
}

AnimationStatus SeatController::animationStatus() const
{
  if (!linkIsHealthy())
  {
    return AnimationStatus::Sleep;
  }

  return raceIsActive() ? AnimationStatus::Race : AnimationStatus::Idle;
}

bool SeatController::collisionIsActive(uint32_t now) const
{
  return collision_started_ms_ != 0 && (now - collision_started_ms_) < config::kCollisionDurationMs;
}

bool SeatController::lapFlashIsActive(uint32_t now) const
{
  return lap_flash_started_ms_ != 0 && (now - lap_flash_started_ms_) < config::kLapFlashDurationMs;
}

void SeatController::pollSerial()
{
  while (Serial.available() > 0)
  {
    const uint8_t byte = static_cast<uint8_t>(Serial.read());
    parser_.push(&byte, 1);
  }

  Frame frame;
  while (parser_.pop(frame))
  {
    handleFrame(frame);
  }
}

void SeatController::sendPeriodicPing()
{
  const uint32_t now = millis();
  if ((now - last_ping_sent_ms_) >= config::kPingIntervalMs)
  {
    sendPing(Serial, next_seq_, GT7_DEVICE_ID);
    last_ping_sent_ms_ = now;
  }
}

void SeatController::handlePing(const Frame &frame)
{
  last_pc_seen_ms_ = millis();
  sendPong(Serial, next_seq_, frame.device_id);
}

void SeatController::handlePong(const Frame &frame)
{
  (void)frame;
  last_pc_seen_ms_ = millis();
}

void SeatController::handleBind(const Frame &frame)
{
  last_pc_seen_ms_ = millis();
  if (frame.payload_len >= 4)
  {
    IPAddress ip(frame.payload[0], frame.payload[1], frame.payload[2], frame.payload[3]);
    const String ip_text = ip.toString();
    ip_text.toCharArray(bound_ps5_ip_, sizeof(bound_ps5_ip_));
    has_binding_ = true;
    sendBindAck(Serial, next_seq_, frame.device_id, bound_ps5_ip_);
    return;
  }

  has_binding_ = false;
  bound_ps5_ip_[0] = '\0';
  sendBindAck(Serial, next_seq_, frame.device_id, "");
}

void SeatController::handleEvent(const Frame &frame)
{
  last_pc_seen_ms_ = millis();
  if (frame.payload_len < 2)
  {
    return;
  }

  const uint8_t event_id = frame.payload[0];
  const uint8_t event_value = frame.payload[1];
  const uint32_t now = millis();
  if (event_id == EventCollision)
  {
    collision_started_ms_ = now;
    hardware_.triggerCollisionVibration(now, event_value);
  }
  else if (event_id == EventLap)
  {
    lap_flash_started_ms_ = now;
  }
}

void SeatController::handleSectionPreview(const Frame &frame)
{
  last_pc_seen_ms_ = millis();
  if (frame.payload_len < config::kSectionPreviewPayloadSize)
  {
    return;
  }

  const uint8_t strip_id = frame.payload[0];
  const uint16_t start_index = static_cast<uint16_t>(frame.payload[1]) |
                               (static_cast<uint16_t>(frame.payload[2]) << 8);
  const uint16_t end_index = static_cast<uint16_t>(frame.payload[3]) |
                             (static_cast<uint16_t>(frame.payload[4]) << 8);
  led_renderer_.previewSection(strip_id, start_index, end_index);
}

void SeatController::handleTelemetry(const Frame &frame)
{
  last_pc_seen_ms_ = millis();
  last_telemetry_rx_ms_ = millis();
  if (frame.payload_len < config::kTelemetryPayloadSize)
  {
    return;
  }

  const uint8_t *payload = frame.payload;
  auto read_f32 = [&](size_t offset) -> float
  {
    float value;
    memcpy(&value, payload + offset, sizeof(float));
    return value;
  };

  telemetry_state_.car_speed = read_f32(0);
  telemetry_state_.engine_rpm = read_f32(4);
  telemetry_state_.rpm_alert_min = read_f32(8);
  telemetry_state_.rpm_alert_max = read_f32(12);
  telemetry_state_.throttle = payload[16];
  telemetry_state_.brake = payload[17];
  telemetry_state_.current_gear = static_cast<int8_t>(payload[18]);
  telemetry_state_.velocity_right = read_f32(19);
  telemetry_state_.fan_speed_multiplier = read_f32(23);
  telemetry_state_.play_state = payload[27] == PlayRace ? PlayRace : PlayIdle;

  hardware_.updateActuators(telemetry_state_, true);
}

void SeatController::handleFrame(const Frame &frame)
{
  switch (frame.type)
  {
    case FrameType::Ping:
      handlePing(frame);
      break;
    case FrameType::Pong:
      handlePong(frame);
      break;
    case FrameType::Bind:
      handleBind(frame);
      break;
    case FrameType::Telemetry:
      handleTelemetry(frame);
      break;
    case FrameType::Event:
      handleEvent(frame);
      break;
    case FrameType::SectionPreview:
      handleSectionPreview(frame);
      break;
    default:
      break;
  }
}

void SeatController::setup()
{
  hardware_.setup();

  Serial.begin(config::kBaudRate);
  Serial.setTimeout(0);

  led_renderer_.setup();

  delay(300);
  sendPing(Serial, next_seq_, GT7_DEVICE_ID);
  last_ping_sent_ms_ = millis();
}

void SeatController::loop()
{
  pollSerial();
  sendPeriodicPing();

  const uint32_t now = millis();
  const AnimationStatus current_animation_status = animationStatus();
  led_renderer_.update(current_animation_status,
                       telemetry_state_,
                       collisionIsActive(now),
                       now - collision_started_ms_,
                       lapFlashIsActive(now),
                       now - lap_flash_started_ms_);

  hardware_.updateActuators(telemetry_state_, telemetryIsFresh());
  hardware_.updateStatusLed(linkIsHealthy());
  delay(5);
}
}  // namespace gt7
