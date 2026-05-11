#ifndef SEAT_CONTROLLER_H
#define SEAT_CONTROLLER_H

#include "gt7_protocol.h"
#include "hardware_controller.h"
#include "led_renderer.h"

namespace gt7
{
class SeatController
{
public:
  void setup();
  void loop();

private:
  TelemetryState telemetry_state_;
  FrameParser parser_;
  LedRenderer led_renderer_;
  HardwareController hardware_;

  uint16_t next_seq_ = 1;
  uint32_t last_ping_sent_ms_ = 0;
  uint32_t last_pc_seen_ms_ = 0;
  uint32_t last_telemetry_rx_ms_ = 0;
  uint32_t collision_started_ms_ = 0;
  uint32_t lap_flash_started_ms_ = 0;
  bool has_binding_ = false;
  char bound_ps5_ip_[16] = {};

  bool telemetryIsFresh() const;
  bool raceIsActive() const;
  bool linkIsHealthy() const;
  bool collisionIsActive(uint32_t now) const;
  bool lapFlashIsActive(uint32_t now) const;

  void pollSerial();
  void sendPeriodicPing();
  void handleFrame(const Frame &frame);
  void handlePing(const Frame &frame);
  void handlePong(const Frame &frame);
  void handleBind(const Frame &frame);
  void handleEvent(const Frame &frame);
  void handleTelemetry(const Frame &frame);
};
}  // namespace gt7

#endif  // SEAT_CONTROLLER_H
